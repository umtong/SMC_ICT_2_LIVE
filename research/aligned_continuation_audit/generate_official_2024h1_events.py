#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
WARMUP_START = pd.Timestamp("2023-12-01T00:00:00Z")
EVAL_START = pd.Timestamp("2024-01-01T00:00:00Z")
EVAL_END = pd.Timestamp("2024-07-01T00:00:00Z")
BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "num_trades", "taker_buy_base_volume",
    "taker_buy_quote_volume", "ignore",
]


def import_original(path: Path):
    spec = importlib.util.spec_from_file_location("registered_absorption_flow_2024", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def months() -> list[pd.Timestamp]:
    return list(pd.date_range("2023-12-01", "2024-06-01", freq="MS", tz="UTC"))


def fetch(url: str, destination: Path, retries: int = 5) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size:
        return
    partial = destination.with_suffix(destination.suffix + ".part")
    error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "SMC-ICT-2024H1-event-freeze/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output, length=1 << 20)
            partial.replace(destination)
            return
        except Exception as exc:
            error = exc
            partial.unlink(missing_ok=True)
            time.sleep(min(2 ** attempt, 16))
    raise RuntimeError(f"download failed {url}: {error}")


def download_one(root: Path, symbol: str, month: pd.Timestamp) -> dict:
    ym = month.strftime("%Y-%m")
    name = f"{symbol}-1m-{ym}.zip"
    url = f"{BASE}/{symbol}/1m/{name}"
    archive = root / symbol / name
    checksum = archive.with_suffix(archive.suffix + ".CHECKSUM")
    fetch(url + ".CHECKSUM", checksum)
    expected = checksum.read_text(encoding="utf-8").strip().split()[0]
    fetch(url, archive)
    observed = sha256_file(archive)
    if observed != expected:
        archive.unlink(missing_ok=True)
        raise RuntimeError(f"checksum mismatch {archive}: {observed} != {expected}")
    return {
        "symbol": symbol, "month": ym, "url": url,
        "sha256": observed, "bytes": archive.stat().st_size,
    }


def read_archive(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected one CSV")
        raw = archive.read(names[0])
    frame = pd.read_csv(io.BytesIO(raw), header=None)
    if str(frame.iloc[0, 0]).strip().lower() in {"open_time", "open time"}:
        frame = frame.iloc[1:].reset_index(drop=True)
    frame = frame.iloc[:, :12]
    frame.columns = COLUMNS
    for column in COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    return frame


def materialize(root: Path, symbol: str) -> pd.DataFrame:
    frames = [read_archive(path) for path in sorted((root / symbol).glob("*.zip"))]
    frame = pd.concat(frames, ignore_index=True)
    frame["timestamp"] = pd.to_datetime(frame.open_time.astype("int64"), unit="ms", utc=True)
    frame = frame[(frame.timestamp >= WARMUP_START) & (frame.timestamp < EVAL_END)].copy()
    frame = frame[[
        "timestamp", "open", "high", "low", "close", "volume", "quote_volume",
        "num_trades", "taker_buy_base_volume", "taker_buy_quote_volume",
    ]]
    return frame.sort_values("timestamp").drop_duplicates("timestamp", keep=False).reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-source", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw_root = args.work_root / "raw"
    prepared = args.work_root / "prepared"
    prepared.mkdir(parents=True, exist_ok=True)

    records = []
    jobs = [(symbol, month) for symbol in SYMBOLS for month in months()]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download_one, raw_root, symbol, month): (symbol, month) for symbol, month in jobs}
        for number, future in enumerate(as_completed(futures), 1):
            records.append(future.result())
            if number % 8 == 0:
                print(f"downloaded {number}/{len(jobs)}", flush=True)

    original = import_original(args.original_source)
    minute = {}
    prepared_rows = []
    for symbol in SYMBOLS:
        frame = materialize(raw_root, symbol)
        path = prepared / f"{symbol}_minute.parquet"
        frame.to_parquet(path, index=False)
        minute[symbol] = original.load_minute(path)
        prepared_rows.append({
            "symbol": symbol, "rows": len(frame),
            "start": frame.timestamp.min().isoformat(), "end": frame.timestamp.max().isoformat(),
            "sha256": sha256_file(path),
        })

    five = {symbol: original.strict_resample_5m(frame) for symbol, frame in minute.items()}
    features = original.prepare_features(five)
    candidate = original.Candidate(
        family="aligned_continuation", horizon_bars=48, z_min=3.0, z_max=float("inf"),
        terminal_bars=3, flow_threshold=0.10, efficiency_min=0.45, hold_min=0.70,
        stop_buffer_atr=0.50, reward_risk=4.0, maximum_holding_minutes=720,
        cross_state="idiosyncratic",
    )
    events = original.generate_events(features, candidate, EVAL_START, EVAL_END)
    rows = []
    for event in events:
        feature_row = features[event.symbol].loc[event.signal_open_time]
        signal_close = float(feature_row.close)
        rows.append({
            "event_key": f"{event.symbol}|{event.decision_time.isoformat()}|{event.side}",
            "symbol": event.symbol,
            "signal_open_time": event.signal_open_time,
            "decision_time": event.decision_time,
            "side": event.side,
            "score": event.score,
            "atr": event.atr,
            "stop_reference": event.stop_reference,
            "displacement_extreme": event.displacement_extreme,
            "signal_close": signal_close,
            "stop_reference_ratio": event.stop_reference / signal_close,
            "atr_fraction": event.atr / signal_close,
        })
    event_frame = pd.DataFrame(rows).sort_values(["decision_time", "score"], ascending=[True, False])
    event_frame.to_parquet(args.output / "EVENT_TAPE_2024H1.parquet", index=False)
    manifest = {
        "schema_version": 1,
        "candidate_id": candidate.candidate_id,
        "warmup": [WARMUP_START.isoformat(), EVAL_START.isoformat()],
        "official_interval": [EVAL_START.isoformat(), EVAL_END.isoformat()],
        "event_count": len(event_frame),
        "raw_archives": sorted(records, key=lambda row: (row["symbol"], row["month"])),
        "prepared": prepared_rows,
        "source_sha256": sha256_file(args.original_source),
        "orders_submitted": False,
    }
    (args.output / "EVENT_MANIFEST_2024H1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"event_count": len(event_frame), "symbol_counts": event_frame.symbol.value_counts().to_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
