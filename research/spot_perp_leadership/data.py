from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BAR_MS = 60_000
SYMBOLS = ("BTCUSDT", "ETHUSDT")
BASES = (
    "https://data.binance.vision",
    "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision",
)
KLINE_COLUMNS = (
    "open_time_ms", "open", "high", "low", "close", "base_volume",
    "close_time_ms", "quote_volume", "trade_count", "taker_buy_base",
    "taker_buy_quote", "ignore",
)

@dataclass(frozen=True, slots=True)
class PairMarket:
    times: np.ndarray
    spot_open: np.ndarray
    spot_high: np.ndarray
    spot_low: np.ndarray
    spot_close: np.ndarray
    spot_quote: np.ndarray
    spot_buy_quote: np.ndarray
    perp_open: np.ndarray
    perp_high: np.ndarray
    perp_low: np.ndarray
    perp_close: np.ndarray
    perp_quote: np.ndarray
    perp_buy_quote: np.ndarray

def normalize_epoch_ms(values: np.ndarray) -> tuple[np.ndarray, int]:
    out = np.asarray(values, dtype=np.int64).copy()
    microseconds = out > 100_000_000_000_000
    repairs = int(microseconds.sum())
    out[microseconds] //= 1_000
    if np.any(out < 0):
        raise ValueError("negative timestamp")
    return out, repairs

def month_range(start: str, end: str) -> list[str]:
    first, last = pd.Period(start, "M"), pd.Period(end, "M")
    if first > last:
        raise ValueError("start after end")
    return [str(item) for item in pd.period_range(first, last, freq="M")]

def fetch(session: requests.Session, path: str) -> tuple[bytes, str]:
    errors: list[str] = []
    for base in BASES:
        for attempt in range(4):
            url = base + path
            try:
                response = session.get(url, timeout=180)
                if response.status_code == 200:
                    return response.content, url
                errors.append(f"{url}: HTTP {response.status_code}")
            except requests.RequestException as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
            time.sleep(2**attempt)
    raise RuntimeError("; ".join(errors[-8:]))

def parse_kline_zip(payload: bytes) -> tuple[pd.DataFrame, int]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV: {names}")
        raw = archive.read(names[0])
    first = raw.splitlines()[0].decode("utf-8-sig").split(",")[0].strip()
    has_header = not first.lstrip("-").isdigit()
    frame = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None).iloc[:, :12]
    if frame.shape[1] != 12:
        raise ValueError("invalid kline width")
    frame.columns = KLINE_COLUMNS
    for column in KLINE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["open_time_ms"], first_repairs = normalize_epoch_ms(
        frame["open_time_ms"].fillna(-1).to_numpy(np.int64)
    )
    frame["close_time_ms"], second_repairs = normalize_epoch_ms(
        frame["close_time_ms"].fillna(-1).to_numpy(np.int64)
    )
    return frame, first_repairs + second_repairs

def canonicalize(frames: list[pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    merged = pd.concat(frames, ignore_index=True)
    before = len(merged)
    merged = merged.sort_values("open_time_ms").drop_duplicates("open_time_ms", keep="last")
    duplicates = before - len(merged)
    required = ["open", "high", "low", "close", "quote_volume", "taker_buy_quote"]
    finite = np.isfinite(merged[required].to_numpy(float)).all(axis=1)
    nonfinite = int((~finite).sum())
    merged = merged.loc[finite].copy()
    high = merged[["open", "high", "low", "close"]].max(axis=1)
    low = merged[["open", "high", "low", "close"]].min(axis=1)
    envelope = int(((high != merged.high) | (low != merged.low)).sum())
    merged["high"], merged["low"] = high, low
    merged = merged.sort_values("open_time_ms").reset_index(drop=True)
    diffs = np.diff(merged.open_time_ms.to_numpy(np.int64))
    return merged, {
        "rows": len(merged),
        "start_ms": int(merged.open_time_ms.iloc[0]),
        "end_ms": int(merged.open_time_ms.iloc[-1]),
        "duplicates_removed": int(duplicates),
        "nonfinite_removed": nonfinite,
        "envelope_repairs": envelope,
        "gaps": int((diffs != BAR_MS).sum()),
        "missing_bars": int(np.maximum(diffs // BAR_MS - 1, 0).sum()),
    }

def download_snapshot(destination: Path, start: str, end: str) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-spot-perp-research/1.0"
        for symbol in SYMBOLS:
            market_frames: dict[str, list[pd.DataFrame]] = {"spot": [], "perp": []}
            market_sources: dict[str, list[dict]] = {"spot": [], "perp": []}
            for market in ("spot", "perp"):
                directory = "spot" if market == "spot" else "futures/um"
                for month in month_range(start, end):
                    name = f"{symbol}-1m-{month}.zip"
                    path = f"/data/{directory}/monthly/klines/{symbol}/1m/{name}"
                    payload, url = fetch(session, path)
                    checksum, _ = fetch(session, path + ".CHECKSUM")
                    expected = checksum.decode("utf-8-sig").strip().split()[0].lower()
                    actual = hashlib.sha256(payload).hexdigest()
                    if actual != expected:
                        raise ValueError(f"checksum mismatch: {market} {name}")
                    frame, timestamp_repairs = parse_kline_zip(payload)
                    market_frames[market].append(frame)
                    market_sources[market].append({
                        "month": month,
                        "url": url,
                        "sha256": actual,
                        "bytes": len(payload),
                        "rows": len(frame),
                        "timestamp_repairs": timestamp_repairs,
                    })
                    print(json.dumps({
                        "symbol": symbol,
                        "market": market,
                        "month": month,
                        "rows": len(frame),
                    }), flush=True)
            spot, spot_audit = canonicalize(market_frames["spot"])
            perp, perp_audit = canonicalize(market_frames["perp"])
            fields = ["open_time_ms", "open", "high", "low", "close", "quote_volume", "taker_buy_quote"]
            spot = spot[fields].rename(columns={name: f"spot_{name}" for name in fields if name != "open_time_ms"})
            perp = perp[fields].rename(columns={name: f"perp_{name}" for name in fields if name != "open_time_ms"})
            pair = spot.merge(perp, on="open_time_ms", how="inner", validate="one_to_one")
            pair = pair.sort_values("open_time_ms").reset_index(drop=True)
            diffs = np.diff(pair.open_time_ms.to_numpy(np.int64))
            common_gaps = int((diffs != BAR_MS).sum())
            common_missing = int(np.maximum(diffs // BAR_MS - 1, 0).sum())
            if spot_audit["gaps"] or perp_audit["gaps"] or common_gaps or common_missing:
                raise ValueError(
                    f"non-contiguous canonical data for {symbol}: "
                    f"spot_gaps={spot_audit['gaps']} perp_gaps={perp_audit['gaps']} "
                    f"common_gaps={common_gaps} common_missing={common_missing}"
                )
            arrays = {
                column: pair[column].to_numpy(np.int64 if column == "open_time_ms" else float)
                for column in pair.columns
            }
            output = destination / f"{symbol}_spot_perp_1m.npz"
            np.savez_compressed(output, **arrays)
            records.append({
                "symbol": symbol,
                "rows": len(pair),
                "start_ms": int(pair.open_time_ms.iloc[0]),
                "end_ms": int(pair.open_time_ms.iloc[-1]),
                "common_gaps": common_gaps,
                "common_missing_bars": common_missing,
                "snapshot_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "spot_audit": spot_audit,
                "perp_audit": perp_audit,
                "spot_sources": market_sources["spot"],
                "perp_sources": market_sources["perp"],
            })
    manifest = {
        "schema_version": 1,
        "markets": ["Binance spot", "Binance USD-M perpetual futures"],
        "dataset": "exact-time aligned monthly 1m klines",
        "symbols": list(SYMBOLS),
        "start_month": start,
        "end_month": end,
        "availability_rule": "completed spot/perp minute; decision then next perpetual minute open",
        "revision_rule": "source archives identified by observed SHA-256; replacements are new revisions",
        "records": records,
    }
    (destination / "DATASET_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest

def load_pairs(root: Path) -> dict[str, PairMarket]:
    result = {}
    for symbol in SYMBOLS:
        item = dict(np.load(root / f"{symbol}_spot_perp_1m.npz"))
        result[symbol] = PairMarket(
            item["open_time_ms"],
            item["spot_open"], item["spot_high"], item["spot_low"], item["spot_close"],
            item["spot_quote_volume"], item["spot_taker_buy_quote"],
            item["perp_open"], item["perp_high"], item["perp_low"], item["perp_close"],
            item["perp_quote_volume"], item["perp_taker_buy_quote"],
        )
    return result
