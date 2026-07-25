from __future__ import annotations

import argparse
import hashlib
import io
import itertools
import json
import math
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

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
    "open_time_ms",
    "open",
    "high",
    "low",
    "close",
    "base_volume",
    "close_time_ms",
    "quote_volume",
    "trade_count",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
)
COST_PROFILES = (12.0, 18.0, 24.0)
INITIAL_EQUITY = 10_000.0
CURRENT_FIRST_DAILY_GROWTH = 0.0005730774040979547
CLAIM_ID = "CLM-20260726-0017-SPOTPERP-TAKEOVER-001"
RESULT_ID = "RES-20260726-SPOT-PERP-LEADERSHIP-001"


@dataclass(frozen=True, slots=True)
class Candidate:
    family: str
    lag: int
    shock_z: float
    ratio: float
    flow_threshold: float
    lead_window: int
    lead_threshold: float
    basis_threshold: float
    hold: int
    stop_atr: float

    @property
    def candidate_id(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


@dataclass(slots=True)
class Panel:
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
    mark_open: np.ndarray
    funding: dict[str, pd.DataFrame]


@dataclass(slots=True)
class Features:
    atr: np.ndarray
    basis_z: np.ndarray
    spot_one: np.ndarray
    perp_one: np.ndarray
    spot_ret: dict[int, np.ndarray]
    perp_ret: dict[int, np.ndarray]
    spot_ret_z: dict[int, np.ndarray]
    perp_ret_z: dict[int, np.ndarray]
    diff_z: dict[int, np.ndarray]
    spot_flow: dict[int, np.ndarray]
    perp_flow: dict[int, np.ndarray]
    leadership: dict[int, np.ndarray]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def epoch_ms(values: np.ndarray) -> tuple[np.ndarray, int]:
    out = np.asarray(values, dtype=np.int64).copy()
    micro = out > 100_000_000_000_000
    repaired = int(micro.sum())
    out[micro] //= 1_000
    if np.any(out < 0):
        raise ValueError("negative timestamp")
    return out, repaired


def months(start: str, end: str) -> list[str]:
    a, b = pd.Period(start, "M"), pd.Period(end, "M")
    if a > b:
        raise ValueError("start after end")
    return [str(item) for item in pd.period_range(a, b, freq="M")]


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


def verified_archive(session: requests.Session, path: str) -> tuple[bytes, dict]:
    payload, url = fetch(session, path)
    checksum, checksum_url = fetch(session, path + ".CHECKSUM")
    expected = checksum.decode("utf-8-sig").strip().split()[0].lower()
    observed = sha256_bytes(payload)
    if observed != expected:
        raise ValueError(f"checksum mismatch: {path}: {observed} != {expected}")
    return payload, {
        "url": url,
        "checksum_url": checksum_url,
        "sha256": observed,
        "bytes": len(payload),
        "checksum_text": checksum.decode("utf-8-sig").strip(),
    }


def archive_specs(symbol: str, month: str) -> tuple[tuple[str, str, str], ...]:
    return (
        (
            "spot_klines",
            f"{symbol}-1m-{month}.zip",
            f"/data/spot/monthly/klines/{symbol}/1m/{symbol}-1m-{month}.zip",
        ),
        (
            "perp_klines",
            f"{symbol}-1m-{month}.zip",
            f"/data/futures/um/monthly/klines/{symbol}/1m/{symbol}-1m-{month}.zip",
        ),
        (
            "mark_klines",
            f"{symbol}-1m-{month}.zip",
            f"/data/futures/um/monthly/markPriceKlines/{symbol}/1m/{symbol}-1m-{month}.zip",
        ),
        (
            "funding_rate",
            f"{symbol}-fundingRate-{month}.zip",
            f"/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip",
        ),
    )


def download_months(root: Path, start: str, end: str) -> dict:
    requested = months(start, end)
    if any(pd.Period(token, "M") >= pd.Period("2025-01", "M") for token in requested):
        raise AssertionError("2025+ is sealed for this claim")
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "SOURCE_MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "schema_version": 1,
            "provider": "Binance public data",
            "markets": ["spot", "USD-M perpetual"],
            "symbols": list(SYMBOLS),
            "records": [],
            "causal_availability": (
                "one-minute kline and mark-price bars are usable after close; "
                "funding events are usable at calc_time; strategy entry is no earlier than next minute open"
            ),
        }
    by_key = {
        (row["dtype"], row["symbol"], row["month"]): row
        for row in manifest.get("records", [])
    }
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-spot-perp-research/1.0"
        for month in requested:
            for symbol in SYMBOLS:
                for dtype, name, path in archive_specs(symbol, month):
                    key = (dtype, symbol, month)
                    destination = root / "raw" / dtype / symbol / name
                    if key in by_key and destination.exists():
                        observed = sha256_file(destination)
                        if observed != by_key[key]["sha256"]:
                            raise ValueError(f"cached archive hash mismatch: {destination}")
                        continue
                    payload, source = verified_archive(session, path)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(payload)
                    row = {
                        "dtype": dtype,
                        "symbol": symbol,
                        "month": month,
                        "path": str(destination.relative_to(root)),
                        **source,
                    }
                    by_key[key] = row
                    print(json.dumps({"downloaded": key, "bytes": len(payload)}), flush=True)
    manifest["records"] = sorted(by_key.values(), key=lambda row: (row["month"], row["symbol"], row["dtype"]))
    manifest["requested_through"] = max(requested)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _read_zip_csv(path: Path) -> tuple[pd.DataFrame, str]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected one CSV, got {names}")
        raw = archive.read(names[0])
    return pd.read_csv(io.BytesIO(raw), header=None), names[0]


def parse_kline_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected one CSV")
        raw = archive.read(names[0])
    first = raw.splitlines()[0].decode("utf-8-sig").split(",")[0].strip()
    has_header = not first.lstrip("-").isdigit()
    frame = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None).iloc[:, :12]
    if frame.shape[1] != 12:
        raise ValueError(f"{path}: invalid kline width {frame.shape[1]}")
    frame.columns = KLINE_COLUMNS
    for column in KLINE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["open_time_ms"], _ = epoch_ms(frame["open_time_ms"].fillna(-1).to_numpy(np.int64))
    frame["close_time_ms"], _ = epoch_ms(frame["close_time_ms"].fillna(-1).to_numpy(np.int64))
    required = ["open", "high", "low", "close", "quote_volume", "taker_buy_quote"]
    finite = np.isfinite(frame[required].to_numpy(float)).all(axis=1)
    frame = frame.loc[finite].copy()
    frame["high"] = frame[["open", "high", "low", "close"]].max(axis=1)
    frame["low"] = frame[["open", "high", "low", "close"]].min(axis=1)
    return frame.sort_values("open_time_ms").drop_duplicates("open_time_ms", keep="last").reset_index(drop=True)


def parse_funding_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected one funding CSV")
        frame = pd.read_csv(archive.open(names[0]))
    normalized = {str(column).strip().lower(): column for column in frame.columns}
    time_name = normalized.get("calc_time") or normalized.get("fundingtime") or normalized.get("funding_time")
    rate_name = normalized.get("last_funding_rate") or normalized.get("fundingrate") or normalized.get("funding_rate")
    if time_name is None or rate_name is None:
        if frame.shape[1] >= 3:
            # Official archives have symbol, calc_time, last_funding_rate.
            time_name, rate_name = frame.columns[-2], frame.columns[-1]
        else:
            raise ValueError(f"{path}: unrecognized funding columns {list(frame.columns)}")
    out = pd.DataFrame(
        {
            "time_ms": pd.to_numeric(frame[time_name], errors="coerce"),
            "rate": pd.to_numeric(frame[rate_name], errors="coerce"),
        }
    ).dropna()
    out["time_ms"], _ = epoch_ms(out["time_ms"].to_numpy(np.int64))
    return out.sort_values("time_ms").drop_duplicates("time_ms", keep="last").reset_index(drop=True)


def _concat_klines(root: Path, dtype: str, symbol: str, start: str, end: str) -> pd.DataFrame:
    frames = []
    for month in months(start, end):
        path = root / "raw" / dtype / symbol / f"{symbol}-1m-{month}.zip"
        frames.append(parse_kline_zip(path))
    return pd.concat(frames, ignore_index=True).sort_values("open_time_ms").drop_duplicates("open_time_ms", keep="last")


def _concat_funding(root: Path, symbol: str, start: str, end: str) -> pd.DataFrame:
    frames = []
    for month in months(start, end):
        path = root / "raw" / "funding_rate" / symbol / f"{symbol}-fundingRate-{month}.zip"
        frames.append(parse_funding_zip(path))
    return pd.concat(frames, ignore_index=True).sort_values("time_ms").drop_duplicates("time_ms", keep="last")


def load_panel(root: Path, start: str, end: str) -> Panel:
    streams: dict[tuple[str, str], pd.DataFrame] = {}
    common: np.ndarray | None = None
    for symbol in SYMBOLS:
        for dtype in ("spot_klines", "perp_klines", "mark_klines"):
            frame = _concat_klines(root, dtype, symbol, start, end)
            streams[(dtype, symbol)] = frame
            values = frame.open_time_ms.to_numpy(np.int64)
            common = values if common is None else np.intersect1d(common, values, assume_unique=True)
    if common is None or len(common) == 0:
        raise AssertionError("empty common spot/perp/mark minute panel")
    expected = np.arange(common[0], common[-1] + BAR_MS, BAR_MS, dtype=np.int64)
    missing = int(len(expected) - len(common))
    if missing:
        raise AssertionError(f"common spot/perp/mark panel has {missing} missing minutes; no imputation allowed")
    shape = (len(SYMBOLS), len(common))
    fields = {
        key: np.full(shape, np.nan, dtype=float)
        for key in (
            "spot_open", "spot_high", "spot_low", "spot_close", "spot_quote", "spot_buy_quote",
            "perp_open", "perp_high", "perp_low", "perp_close", "perp_quote", "perp_buy_quote",
            "mark_open",
        )
    }
    for si, symbol in enumerate(SYMBOLS):
        for prefix, dtype in (("spot", "spot_klines"), ("perp", "perp_klines")):
            frame = streams[(dtype, symbol)].set_index("open_time_ms").loc[common]
            fields[f"{prefix}_open"][si] = frame.open.to_numpy(float)
            fields[f"{prefix}_high"][si] = frame.high.to_numpy(float)
            fields[f"{prefix}_low"][si] = frame.low.to_numpy(float)
            fields[f"{prefix}_close"][si] = frame.close.to_numpy(float)
            fields[f"{prefix}_quote"][si] = frame.quote_volume.to_numpy(float)
            fields[f"{prefix}_buy_quote"][si] = frame.taker_buy_quote.to_numpy(float)
        mark = streams[("mark_klines", symbol)].set_index("open_time_ms").loc[common]
        fields["mark_open"][si] = mark.open.to_numpy(float)

    funding: dict[str, pd.DataFrame] = {}
    for si, symbol in enumerate(SYMBOLS):
        frame = _concat_funding(root, symbol, start, end)
        pos = np.searchsorted(common, frame.time_ms.to_numpy(np.int64))
        exact = (pos < len(common)) & (common[np.minimum(pos, len(common) - 1)] == frame.time_ms.to_numpy(np.int64))
        if not exact.all():
            raise AssertionError(f"{symbol}: funding events lack exact official mark minute")
        frame = frame.copy()
        frame["mark_price"] = fields["mark_open"][si, pos]
        if not np.isfinite(frame.mark_price.to_numpy(float)).all():
            raise AssertionError(f"{symbol}: nonfinite funding mark")
        funding[symbol] = frame
    return Panel(times=common, funding=funding, **fields)


def _prior_z(values: np.ndarray, window: int, minimum: int) -> np.ndarray:
    series = pd.Series(values)
    mean = series.rolling(window, min_periods=minimum).mean().shift(1)
    std = series.rolling(window, min_periods=minimum).std(ddof=0).shift(1)
    return ((series - mean) / std.replace(0.0, np.nan)).to_numpy(float)


def _rolling_flow(signed: np.ndarray, quote: np.ndarray, lag: int) -> np.ndarray:
    numerator = pd.Series(signed).rolling(lag, min_periods=lag).sum()
    denominator = pd.Series(quote).rolling(lag, min_periods=lag).sum()
    return (numerator / denominator.replace(0.0, np.nan)).to_numpy(float)


def make_features(panel: Panel) -> Features:
    log_spot = np.log(panel.spot_close)
    log_perp = np.log(panel.perp_close)
    spot_one = np.full_like(log_spot, np.nan)
    perp_one = np.full_like(log_perp, np.nan)
    spot_one[:, 1:] = log_spot[:, 1:] - log_spot[:, :-1]
    perp_one[:, 1:] = log_perp[:, 1:] - log_perp[:, :-1]

    atr = np.full_like(panel.perp_close, np.nan)
    basis_z = np.full_like(panel.perp_close, np.nan)
    for si in range(len(SYMBOLS)):
        previous = np.r_[np.nan, panel.perp_close[si, :-1]]
        tr = np.maximum(
            panel.perp_high[si] - panel.perp_low[si],
            np.maximum(abs(panel.perp_high[si] - previous), abs(panel.perp_low[si] - previous)),
        )
        atr[si] = pd.Series(tr).rolling(60, min_periods=30).mean().shift(1).to_numpy(float)
        basis = log_perp[si] - log_spot[si]
        basis_z[si] = _prior_z(basis, 10_080, 4_320)

    spot_ret: dict[int, np.ndarray] = {}
    perp_ret: dict[int, np.ndarray] = {}
    spot_ret_z: dict[int, np.ndarray] = {}
    perp_ret_z: dict[int, np.ndarray] = {}
    diff_z: dict[int, np.ndarray] = {}
    spot_flow: dict[int, np.ndarray] = {}
    perp_flow: dict[int, np.ndarray] = {}
    spot_signed = 2.0 * panel.spot_buy_quote - panel.spot_quote
    perp_signed = 2.0 * panel.perp_buy_quote - panel.perp_quote
    for lag in (1, 3, 5):
        sr = np.full_like(log_spot, np.nan)
        pr = np.full_like(log_perp, np.nan)
        sr[:, lag:] = log_spot[:, lag:] - log_spot[:, :-lag]
        pr[:, lag:] = log_perp[:, lag:] - log_perp[:, :-lag]
        spot_ret[lag], perp_ret[lag] = sr, pr
        sz, pz, dz = np.full_like(sr, np.nan), np.full_like(pr, np.nan), np.full_like(sr, np.nan)
        sf, pf = np.full_like(sr, np.nan), np.full_like(pr, np.nan)
        for si in range(len(SYMBOLS)):
            sz[si] = _prior_z(sr[si], 4_320, 1_440)
            pz[si] = _prior_z(pr[si], 4_320, 1_440)
            dz[si] = _prior_z(sr[si] - pr[si], 4_320, 1_440)
            sf[si] = _rolling_flow(spot_signed[si], panel.spot_quote[si], lag)
            pf[si] = _rolling_flow(perp_signed[si], panel.perp_quote[si], lag)
        spot_ret_z[lag], perp_ret_z[lag], diff_z[lag] = sz, pz, dz
        spot_flow[lag], perp_flow[lag] = sf, pf

    leadership: dict[int, np.ndarray] = {}
    for window in (1_440, 4_320):
        values = np.full_like(spot_one, np.nan)
        minimum = window // 2
        for si in range(len(SYMBOLS)):
            spot_lag = pd.Series(spot_one[si]).shift(1)
            perp_now = pd.Series(perp_one[si])
            perp_lag = pd.Series(perp_one[si]).shift(1)
            spot_now = pd.Series(spot_one[si])
            spot_leads = spot_lag.rolling(window, min_periods=minimum).corr(perp_now).shift(1)
            perp_leads = perp_lag.rolling(window, min_periods=minimum).corr(spot_now).shift(1)
            values[si] = (spot_leads - perp_leads).to_numpy(float)
        leadership[window] = values
    return Features(
        atr=atr,
        basis_z=basis_z,
        spot_one=spot_one,
        perp_one=perp_one,
        spot_ret=spot_ret,
        perp_ret=perp_ret,
        spot_ret_z=spot_ret_z,
        perp_ret_z=perp_ret_z,
        diff_z=diff_z,
        spot_flow=spot_flow,
        perp_flow=perp_flow,
        leadership=leadership,
    )


def candidates() -> list[Candidate]:
    out: list[Candidate] = []
    for family in ("spot_lead_continuation", "perp_overshoot_reversal"):
        for lag, shock, ratio, flow, lead_window, lead_threshold, hold, stop in itertools.product(
            (1, 3, 5),
            (2.0, 2.5),
            (0.35, 0.60),
            (0.0, 0.15),
            (1_440,),
            (0.0, 0.03),
            (3, 10),
            (1.5, 2.0),
        ):
            out.append(Candidate(family, lag, shock, ratio, flow, lead_window, lead_threshold, 1.5, hold, stop))
    for basis_threshold, lag, flow, hold, stop in itertools.product(
        (2.0, 2.5, 3.0), (1, 3), (0.0, 0.10), (3, 10), (1.5, 2.0)
    ):
        out.append(Candidate(
            "basis_convergence", lag, 0.0, 0.0, flow, 1_440, 0.0, basis_threshold, hold, stop
        ))
    for lag, shock, lead_window, lead_threshold, hold, stop in itertools.product(
        (1, 3), (2.0, 2.5), (1_440, 4_320), (0.03, 0.06), (3, 10), (1.5, 2.0)
    ):
        out.append(Candidate(
            "leadership_state_router", lag, shock, 0.60, 0.10,
            lead_window, lead_threshold, 1.5, hold, stop
        ))
    ids = [item.candidate_id for item in out]
    if len(ids) != len(set(ids)):
        raise AssertionError("duplicate candidate IDs")
    return out


def signal_events(
    candidate: Candidate,
    panel: Panel,
    feature: Features,
    start_ms: int,
    end_ms: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    lag = candidate.lag
    sr, pr = feature.spot_ret[lag], feature.perp_ret[lag]
    sz, pz = feature.spot_ret_z[lag], feature.perp_ret_z[lag]
    sf, pf = feature.spot_flow[lag], feature.perp_flow[lag]
    basis = feature.basis_z
    lead = feature.leadership[candidate.lead_window]
    time_ok = (panel.times >= start_ms) & (panel.times < end_ms)
    time_ok &= np.r_[np.diff(panel.times) == BAR_MS, False]
    base = np.broadcast_to(time_ok, sr.shape).copy()
    finite = np.isfinite(sr) & np.isfinite(pr) & np.isfinite(sz) & np.isfinite(pz)
    finite &= np.isfinite(sf) & np.isfinite(pf) & np.isfinite(basis) & np.isfinite(lead)
    base &= finite

    if candidate.family == "spot_lead_continuation":
        shock_side = np.sign(sr)
        mask = base & (np.abs(sz) >= candidate.shock_z)
        mask &= np.abs(pr) <= candidate.ratio * np.abs(sr)
        mask &= shock_side * sf >= candidate.flow_threshold
        mask &= lead >= candidate.lead_threshold
        side = np.nan_to_num(shock_side, nan=0.0).astype(np.int8)
        score = np.abs(sz) + np.maximum(shock_side * feature.diff_z[lag], 0.0) + np.maximum(lead, 0.0)
    elif candidate.family == "perp_overshoot_reversal":
        shock_side = np.sign(pr)
        mask = base & (np.abs(pz) >= candidate.shock_z)
        mask &= np.abs(sr) <= candidate.ratio * np.abs(pr)
        mask &= shock_side * pf >= candidate.flow_threshold
        mask &= shock_side * basis >= candidate.basis_threshold
        mask &= lead <= -candidate.lead_threshold
        side = np.nan_to_num(-shock_side, nan=0.0).astype(np.int8)
        score = np.abs(pz) + np.maximum(shock_side * basis, 0.0) + np.maximum(-lead, 0.0)
    elif candidate.family == "basis_convergence":
        basis_side = np.sign(basis)
        mask = base & (np.abs(basis) >= candidate.basis_threshold)
        mask &= basis_side * (pf - sf) >= candidate.flow_threshold
        mask &= basis_side * (pr - sr) > 0.0
        side = np.nan_to_num(-basis_side, nan=0.0).astype(np.int8)
        score = np.abs(basis) + np.maximum(basis_side * (pf - sf), 0.0)
    elif candidate.family == "leadership_state_router":
        spot_side = np.sign(sr)
        perp_side = np.sign(pr)
        continuation = base & (lead >= candidate.lead_threshold)
        continuation &= np.abs(sz) >= candidate.shock_z
        continuation &= np.abs(pr) <= candidate.ratio * np.abs(sr)
        continuation &= spot_side * sf >= candidate.flow_threshold
        reversal = base & (lead <= -candidate.lead_threshold)
        reversal &= np.abs(pz) >= candidate.shock_z
        reversal &= np.abs(sr) <= candidate.ratio * np.abs(pr)
        reversal &= perp_side * pf >= candidate.flow_threshold
        reversal &= perp_side * basis >= candidate.basis_threshold
        mask = continuation | reversal
        side = np.nan_to_num(np.where(continuation, spot_side, -perp_side), nan=0.0).astype(np.int8)
        score = np.where(
            continuation,
            np.abs(sz) + np.maximum(lead, 0.0),
            np.abs(pz) + np.maximum(-lead, 0.0) + np.maximum(perp_side * basis, 0.0),
        )
    else:
        raise ValueError(candidate.family)

    mask &= side != 0
    symbol_index, bar_index = np.nonzero(mask)
    if len(bar_index) == 0:
        empty_i = np.empty(0, dtype=np.int64)
        empty_s = np.empty(0, dtype=np.int8)
        empty_f = np.empty(0, dtype=float)
        return empty_i, empty_s, empty_s.copy(), empty_f
    raw_score = score[symbol_index, bar_index]
    raw_side = side[symbol_index, bar_index]
    order = np.lexsort((-raw_score, bar_index))
    symbol_index, bar_index, raw_side, raw_score = (
        symbol_index[order], bar_index[order], raw_side[order], raw_score[order]
    )
    keep = np.r_[True, bar_index[1:] != bar_index[:-1]]
    return (
        bar_index[keep].astype(np.int64),
        symbol_index[keep].astype(np.int8),
        raw_side[keep].astype(np.int8),
        raw_score[keep].astype(float),
    )


def funding_cash(
    frame: pd.DataFrame,
    entry_ms: int,
    exit_ms: int,
    side: int,
    quantity: float,
) -> tuple[float, int]:
    times = frame.time_ms.to_numpy(np.int64)
    a = int(np.searchsorted(times, entry_ms, side="right"))
    b = int(np.searchsorted(times, exit_ms, side="right"))
    if b <= a:
        return 0.0, 0
    block = frame.iloc[a:b]
    cash = float((-side * quantity * block.mark_price.to_numpy(float) * block.rate.to_numpy(float)).sum())
    return cash, len(block)


def _metrics(
    returns: list[float],
    pnls: list[float],
    equities: list[float],
    start_ms: int,
    end_ms: int,
    times: list[int],
    symbols: list[str],
) -> dict:
    n = len(returns)
    days = max(1.0, (end_ms - start_ms) / 86_400_000)
    if n == 0:
        return {
            "trade_count": 0,
            "total_return": 0.0,
            "geometric_daily_growth": 0.0,
            "profit_factor": 0.0,
            "maximum_drawdown": 0.0,
            "median_account_return_bps": 0.0,
            "top5_positive_share": 1.0,
            "top10pct_removed_return": 0.0,
            "positive_half_count": 0,
            "positive_month_fraction": 0.0,
            "symbol_counts": {},
        }
    ar = np.asarray(returns, dtype=float)
    pnl = np.asarray(pnls, dtype=float)
    ending = float(equities[-1])
    peaks = np.maximum.accumulate(np.asarray(equities, dtype=float))
    mdd = float(np.max(1.0 - np.asarray(equities, dtype=float) / peaks))
    pos, neg = pnl[pnl > 0], -pnl[pnl < 0]
    positive_sum = float(pos.sum())
    top5 = float(np.sort(pos)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0
    removed = max(1, int(math.ceil(n * 0.10)))
    remove_indices = np.argsort(ar)[-removed:]
    kept = ar.copy()
    kept[remove_indices] = 0.0
    top_removed = float(np.prod(1.0 + kept) - 1.0)
    dt = pd.to_datetime(np.asarray(times, dtype=np.int64), unit="ms", utc=True)
    split = start_ms + (end_ms - start_ms) // 2
    half_returns = []
    for lo, hi in ((start_ms, split), (split, end_ms)):
        mask = (np.asarray(times) >= lo) & (np.asarray(times) < hi)
        half_returns.append(float(np.prod(1.0 + ar[mask]) - 1.0))
    month_frame = pd.DataFrame({"month": dt.to_period("M").astype(str), "ret": ar})
    monthly = month_frame.groupby("month").ret.apply(lambda x: float(np.prod(1.0 + x) - 1.0))
    counts = pd.Series(symbols, dtype=str).value_counts().to_dict()
    return {
        "trade_count": n,
        "total_return": ending / INITIAL_EQUITY - 1.0,
        "geometric_daily_growth": math.exp(math.log(ending / INITIAL_EQUITY) / days) - 1.0,
        "profit_factor": float(pos.sum() / neg.sum()) if neg.sum() > 0 else (999.0 if pos.sum() > 0 else 0.0),
        "maximum_drawdown": mdd,
        "median_account_return_bps": float(np.median(ar) * 10_000.0),
        "top5_positive_share": top5,
        "top10pct_removed_return": top_removed,
        "positive_half_count": int(sum(item > 0 for item in half_returns)),
        "positive_month_fraction": float((monthly > 0).mean()) if len(monthly) else 0.0,
        "worst_month": float(monthly.min()) if len(monthly) else 0.0,
        "symbol_counts": {str(k): int(v) for k, v in counts.items()},
    }


def simulate_candidate(
    candidate: Candidate,
    panel: Panel,
    feature: Features,
    start_ms: int,
    end_ms: int,
    include_ledger: bool = False,
) -> tuple[dict[str, dict], list[dict]]:
    bars, sy, sides, scores = signal_events(candidate, panel, feature, start_ms, end_ms)
    state = {
        cost: {
            "equity": INITIAL_EQUITY,
            "returns": [],
            "pnls": [],
            "equities": [INITIAL_EQUITY],
            "times": [],
            "symbols": [],
        }
        for cost in COST_PROFILES
    }
    ledger: list[dict] = []
    free_bar = -1
    for event_number in range(len(bars)):
        signal = int(bars[event_number])
        if signal < free_bar:
            continue
        si, side = int(sy[event_number]), int(sides[event_number])
        entry_i = signal + 1
        timeout_i = entry_i + candidate.hold
        if timeout_i >= len(panel.times):
            continue
        if panel.times[entry_i] != panel.times[signal] + BAR_MS:
            continue
        if panel.times[timeout_i] != panel.times[entry_i] + candidate.hold * BAR_MS:
            continue
        entry = float(panel.perp_open[si, entry_i])
        current_atr = float(feature.atr[si, signal])
        quote_capacity = float(panel.perp_quote[si, signal]) * 0.001
        if not (np.isfinite(entry) and np.isfinite(current_atr) and np.isfinite(quote_capacity)):
            continue
        if entry <= 0 or current_atr <= 0 or quote_capacity <= 0:
            continue
        distance = max(candidate.stop_atr * current_atr, entry * 0.0005)
        if distance / entry > 0.05:
            continue
        stop = entry - side * distance
        exit_i, exit_price, stopped, reason = timeout_i, float(panel.perp_open[si, timeout_i]), False, "timeout"
        valid = True
        for bar in range(entry_i, timeout_i):
            o = float(panel.perp_open[si, bar])
            h = float(panel.perp_high[si, bar])
            l = float(panel.perp_low[si, bar])
            if not (np.isfinite(o) and np.isfinite(h) and np.isfinite(l)):
                valid = False
                break
            if side > 0 and l <= stop:
                exit_i, exit_price, stopped, reason = bar, (o if o < stop else stop), True, "stop"
                break
            if side < 0 and h >= stop:
                exit_i, exit_price, stopped, reason = bar, (o if o > stop else stop), True, "stop"
                break
        if not valid or not np.isfinite(exit_price):
            continue
        gross_fraction = side * (exit_price / entry - 1.0)
        profile_rows = {}
        for cost in COST_PROFILES:
            item = state[cost]
            equity = float(item["equity"])
            planned_loss = distance / entry + 0.0026
            notional = min(equity * 0.005 / planned_loss, equity * 3.0, quote_capacity)
            if notional <= 0:
                continue
            quantity = notional / entry
            funding_pnl, funding_count = funding_cash(
                panel.funding[SYMBOLS[si]], int(panel.times[entry_i]), int(panel.times[exit_i]), side, quantity
            )
            applied_cost = cost + (2.0 if stopped else 0.0)
            pnl = gross_fraction * notional - applied_cost / 10_000.0 * notional + funding_pnl
            if pnl <= -equity:
                raise AssertionError("irrecoverable account path under capped exposure")
            account_return = pnl / equity
            equity_after = equity + pnl
            item["equity"] = equity_after
            item["returns"].append(account_return)
            item["pnls"].append(pnl)
            item["equities"].append(equity_after)
            item["times"].append(int(panel.times[exit_i]))
            item["symbols"].append(SYMBOLS[si])
            profile_rows[str(int(cost))] = {
                "notional": notional,
                "funding_pnl": funding_pnl,
                "funding_event_count": funding_count,
                "pnl": pnl,
                "account_return": account_return,
                "equity_after": equity_after,
            }
        if include_ledger:
            ledger.append({
                "candidate_id": candidate.candidate_id,
                "family": candidate.family,
                "signal_time_ms": int(panel.times[signal]),
                "entry_time_ms": int(panel.times[entry_i]),
                "exit_time_ms": int(panel.times[exit_i]),
                "symbol": SYMBOLS[si],
                "side": side,
                "score": float(scores[event_number]),
                "entry_price": entry,
                "exit_price": exit_price,
                "stop_price": stop,
                "stopped": stopped,
                "exit_reason": reason,
                "gross_fraction": gross_fraction,
                "profiles": profile_rows,
            })
        free_bar = exit_i + 1
    metrics = {
        str(int(cost)): _metrics(
            state[cost]["returns"],
            state[cost]["pnls"],
            state[cost]["equities"],
            start_ms,
            end_ms,
            state[cost]["times"],
            state[cost]["symbols"],
        )
        for cost in COST_PROFILES
    }
    return metrics, ledger


def economic_gate(metrics: dict[str, dict]) -> tuple[bool, list[str]]:
    m12, m18 = metrics["12"], metrics["18"]
    checks = {
        "trade_count_at_least_150": m12["trade_count"] >= 150,
        "positive_12bp_growth": m12["geometric_daily_growth"] > 0.0,
        "positive_18bp_growth": m18["geometric_daily_growth"] > 0.0,
        "positive_12bp_top10_removed": m12["top10pct_removed_return"] > 0.0,
        "positive_18bp_top10_removed": m18["top10pct_removed_return"] > 0.0,
        "profit_factor_at_least_1_10": m12["profit_factor"] >= 1.10,
        "maximum_drawdown_at_most_15pct": m12["maximum_drawdown"] <= 0.15,
        "top5_share_at_most_35pct": m12["top5_positive_share"] <= 0.35,
        "positive_median_trade": m12["median_account_return_bps"] > 0.0,
        "both_halves_positive": m12["positive_half_count"] == 2,
    }
    return all(checks.values()), [name for name, passed in checks.items() if not passed]


def flatten_result(candidate: Candidate, metrics: dict[str, dict], passed: bool, failures: list[str]) -> dict:
    row = {**asdict(candidate), "candidate_id": candidate.candidate_id, "gate_pass": passed}
    row["gate_failures"] = ";".join(failures)
    for cost in ("12", "18", "24"):
        for key, value in metrics[cost].items():
            if key == "symbol_counts":
                row[f"{key}_{cost}bps"] = json.dumps(value, sort_keys=True, separators=(",", ":"))
            else:
                row[f"{key}_{cost}bps"] = value
    return row


def screen(
    panel: Panel,
    feature: Features,
    selected: Iterable[Candidate],
    start: str,
    end: str,
    output: Path,
    label: str,
) -> tuple[list[dict], list[Candidate]]:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    start_ms, end_ms = int(start_ts.timestamp() * 1000), int(end_ts.timestamp() * 1000)
    rows: list[dict] = []
    passed_candidates: list[Candidate] = []
    for index, candidate in enumerate(selected, start=1):
        metrics, _ = simulate_candidate(candidate, panel, feature, start_ms, end_ms)
        passed, failures = economic_gate(metrics)
        rows.append(flatten_result(candidate, metrics, passed, failures))
        if passed:
            passed_candidates.append(candidate)
        if index % 50 == 0:
            print(json.dumps({"stage": label, "completed": index, "gate_passes": len(passed_candidates)}), flush=True)
    frame = pd.DataFrame(rows)
    frame = frame.sort_values(
        ["geometric_daily_growth_12bps", "top10pct_removed_return_12bps", "maximum_drawdown_12bps"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    output.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output / f"{label}_candidate_results.csv", index=False)
    return frame.to_dict("records"), passed_candidates


def freeze_one_per_family(rows: list[dict], passed: list[Candidate]) -> list[Candidate]:
    lookup = {item.candidate_id: item for item in passed}
    frozen: list[Candidate] = []
    for family in sorted({item.family for item in passed}):
        eligible = [row for row in rows if row["gate_pass"] and row["family"] == family]
        eligible.sort(
            key=lambda row: (
                row["geometric_daily_growth_18bps"],
                row["top10pct_removed_return_18bps"],
                -row["maximum_drawdown_12bps"],
            ),
            reverse=True,
        )
        if eligible:
            frozen.append(lookup[eligible[0]["candidate_id"]])
    return frozen


def result_summary(
    dev_rows: list[dict],
    dev_survivors: list[Candidate],
    frozen: list[Candidate],
    selection_rows: list[dict] | None,
    selection_survivors: list[Candidate],
    validation_rows: list[dict] | None,
    output: Path,
) -> dict:
    best = dev_rows[0] if dev_rows else None
    best_growth = float(best["geometric_daily_growth_12bps"]) if best else float("-inf")
    target_gap = 0.01 - best_growth if best else None
    ranking_decision = (
        "PROVISIONAL_FIRST_PLACE_CHALLENGE"
        if best is not None and best_growth > CURRENT_FIRST_DAILY_GROWTH
        else "CURRENT_FIRST_PLACE_UNCHANGED"
    )
    status = "TESTED_BELOW_GATE"
    if validation_rows and any(bool(row["gate_pass"]) for row in validation_rows):
        status = "VALIDATION_SURVIVOR"
    elif selection_rows and selection_survivors:
        status = "SELECTION_SURVIVOR"
    summary = {
        "schema_version": 1,
        "result_id": RESULT_ID,
        "claim_id": CLAIM_ID,
        "status": status,
        "hard_validity_status": "PASS",
        "economic_status": "ABOVE_INITIAL_GATE" if dev_survivors else "BELOW_GATE",
        "target_status": "MET" if best_growth >= 0.01 else "NOT_MET",
        "candidate_count": len(dev_rows),
        "development_survivor_count": len(dev_survivors),
        "frozen_candidate_count": len(frozen),
        "selection_opened": selection_rows is not None,
        "selection_survivor_count": len(selection_survivors),
        "validation_opened": validation_rows is not None,
        "best_development_candidate": best,
        "best_geometric_daily_growth_12bps": best_growth if best is not None else None,
        "target_gap": target_gap,
        "current_first_daily_growth": CURRENT_FIRST_DAILY_GROWTH,
        "ranking_decision": ranking_decision,
        "sealed_periods": ["2025", "2026"],
        "execution_contract": {
            "signal": "completed one-minute spot and USD-M bars",
            "entry": "next contiguous USD-M one-minute open",
            "exit": "fixed hold or adverse stop-first, with gap stop at observed open",
            "cost_profiles_round_trip_bps": list(COST_PROFILES),
            "funding": "official fundingRate with official mark-price open at exact calc_time",
            "account": "one global slot, 0.5% planned-loss risk, 3x notional cap, 0.1% prior quote-volume participation",
        },
        "known_limits": [
            "Minute bars cannot establish sub-minute price discovery or queue position.",
            "Historical bid/ask spread and partial fills are represented by 12/18/24bp all-in cost profiles.",
            "A ranking challenge remains provisional because windows and execution contracts differ from existing studies.",
        ],
    }
    (output / "result_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print("SPOT_PERP_RESULT_JSON=" + json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return summary


def staged_run(output: Path) -> dict:
    raw = output / "dataset"
    preregistration = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "symbols": list(SYMBOLS),
        "warmup": ["2021-10-01", "2022-01-01"],
        "development": ["2022-01-01", "2023-01-01"],
        "conditional_selection": ["2023-01-01", "2024-01-01"],
        "conditional_validation": ["2024-01-01", "2025-01-01"],
        "sealed": ["2025-01-01", "2027-01-01"],
        "candidate_count": len(candidates()),
        "families": sorted({item.family for item in candidates()}),
        "gate": {
            "minimum_trades": 150,
            "positive_growth_at_bps": [12, 18],
            "positive_top10pct_removed_at_bps": [12, 18],
            "profit_factor_min": 1.10,
            "maximum_drawdown_max": 0.15,
            "top5_positive_share_max": 0.35,
            "positive_median_trade": True,
            "positive_both_half_years": True,
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "preregistration.json").write_text(
        json.dumps(preregistration, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    download_months(raw, "2021-10", "2022-12")
    panel = load_panel(raw, "2021-10", "2022-12")
    feature = make_features(panel)
    all_candidates = candidates()
    dev_rows, dev_survivors = screen(
        panel, feature, all_candidates, "2022-01-01", "2023-01-01", output, "development_2022"
    )
    frozen = freeze_one_per_family(dev_rows, dev_survivors)
    selection_rows: list[dict] | None = None
    selection_survivors: list[Candidate] = []
    validation_rows: list[dict] | None = None

    if frozen:
        download_months(raw, "2023-01", "2023-12")
        panel = load_panel(raw, "2021-10", "2023-12")
        feature = make_features(panel)
        selection_rows, selection_survivors = screen(
            panel, feature, frozen, "2023-01-01", "2024-01-01", output, "selection_2023"
        )
    else:
        print("STAGE_DECISION=selection_2023_unopened_zero_development_survivors", flush=True)

    if selection_survivors:
        download_months(raw, "2024-01", "2024-12")
        panel = load_panel(raw, "2021-10", "2024-12")
        feature = make_features(panel)
        validation_rows, _ = screen(
            panel, feature, selection_survivors, "2024-01-01", "2025-01-01", output, "validation_2024"
        )
    else:
        print("STAGE_DECISION=validation_2024_unopened_zero_selection_survivors", flush=True)

    summary = result_summary(
        dev_rows, dev_survivors, frozen, selection_rows, selection_survivors, validation_rows, output
    )
    if dev_rows:
        best_id = dev_rows[0]["candidate_id"]
        best = next(item for item in all_candidates if item.candidate_id == best_id)
        _, ledger = simulate_candidate(
            best,
            panel if selection_rows is not None else panel,
            feature if selection_rows is not None else feature,
            int(pd.Timestamp("2022-01-01", tz="UTC").timestamp() * 1000),
            int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000),
            include_ledger=True,
        )
        (output / "best_development_ledger.json").write_text(
            json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    inventory = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "FILE_MANIFEST.sha256":
            inventory.append(f"{sha256_file(path)}  {path.relative_to(output)}")
    (output / "FILE_MANIFEST.sha256").write_text("\n".join(inventory) + "\n", encoding="utf-8")
    return summary


def synthetic_panel(length: int = 20_000) -> Panel:
    rng = np.random.default_rng(7)
    times = np.arange(length, dtype=np.int64) * BAR_MS + 1_600_000_000_000
    base = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.0005, size=(2, length)), axis=1))
    spot = base * np.exp(rng.normal(0.0, 0.00005, size=(2, length)))
    perp = base * np.exp(rng.normal(0.0, 0.00008, size=(2, length)))
    def ohlc(close: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        op = np.c_[close[:, :1], close[:, :-1]]
        spread = abs(rng.normal(0.0, 0.0004, size=close.shape))
        hi = np.maximum(op, close) * (1.0 + spread)
        lo = np.minimum(op, close) * (1.0 - spread)
        return op, hi, lo, close
    so, sh, sl, sc = ohlc(spot)
    po, ph, pl, pc = ohlc(perp)
    quote = np.full((2, length), 10_000_000.0)
    buy = quote * (0.5 + rng.normal(0.0, 0.05, size=(2, length))).clip(0.05, 0.95)
    funding = {
        symbol: pd.DataFrame({"time_ms": times[::480], "rate": 0.0001, "mark_price": perp[si, ::480]})
        for si, symbol in enumerate(SYMBOLS)
    }
    return Panel(
        times, so, sh, sl, sc, quote, buy,
        po, ph, pl, pc, quote.copy(), buy.copy(), perp.copy(), funding
    )


def self_test() -> None:
    assert len(candidates()) == 496
    assert len({item.candidate_id for item in candidates()}) == 496
    panel = synthetic_panel()
    full = make_features(panel)
    prefix = 15_000
    short_panel = Panel(
        times=panel.times[:prefix],
        spot_open=panel.spot_open[:, :prefix],
        spot_high=panel.spot_high[:, :prefix],
        spot_low=panel.spot_low[:, :prefix],
        spot_close=panel.spot_close[:, :prefix],
        spot_quote=panel.spot_quote[:, :prefix],
        spot_buy_quote=panel.spot_buy_quote[:, :prefix],
        perp_open=panel.perp_open[:, :prefix],
        perp_high=panel.perp_high[:, :prefix],
        perp_low=panel.perp_low[:, :prefix],
        perp_close=panel.perp_close[:, :prefix],
        perp_quote=panel.perp_quote[:, :prefix],
        perp_buy_quote=panel.perp_buy_quote[:, :prefix],
        mark_open=panel.mark_open[:, :prefix],
        funding={symbol: frame[frame.time_ms < panel.times[prefix]].copy() for symbol, frame in panel.funding.items()},
    )
    short = make_features(short_panel)
    for lag in (1, 3, 5):
        assert np.allclose(full.spot_ret_z[lag][:, :prefix], short.spot_ret_z[lag], equal_nan=True)
        assert np.allclose(full.diff_z[lag][:, :prefix], short.diff_z[lag], equal_nan=True)
    for window in (1_440, 4_320):
        assert np.allclose(full.leadership[window][:, :prefix], short.leadership[window], equal_nan=True)
    frame = pd.DataFrame({
        "time_ms": [panel.times[10], panel.times[20]],
        "rate": [0.001, -0.001],
        "mark_price": [100.0, 100.0],
    })
    long_cash, n = funding_cash(frame, int(panel.times[9]), int(panel.times[10]), 1, 1.0)
    short_cash, _ = funding_cash(frame, int(panel.times[9]), int(panel.times[10]), -1, 1.0)
    assert n == 1 and math.isclose(long_cash, -0.1) and math.isclose(short_cash, 0.1)
    test_candidate = Candidate("basis_convergence", 1, 0.0, 0.0, 0.0, 1_440, 0.0, 2.0, 3, 1.5)
    bars, _, _, _ = signal_events(
        test_candidate, panel, full, int(panel.times[12_000]), int(panel.times[-10])
    )
    if len(bars):
        assert np.all(panel.times[bars + 1] == panel.times[bars] + BAR_MS)
    print("SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    staged = sub.add_parser("staged-run")
    staged.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    elif args.command == "staged-run":
        staged_run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
