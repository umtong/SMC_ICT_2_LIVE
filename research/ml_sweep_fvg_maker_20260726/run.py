from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

CLAIM_ID = "CLM-20260726-1837-ML-SWEEP-FVG-MAKER-001"
ENGINE_VERSION = "ML-SWEEP-FVG-QUEUE-MAKER-V1"
PARENT_ARTIFACT_ID = 8626087323
PARENT_ARTIFACT_SHA256 = "90594acc23e63e97e83347f9b07eb9ac260ba7bb1b87eb72052287a8328ad4a1"
SYMBOL = "BTCUSDT"
FIT_DATE = "2022-07-01"
DEVELOPMENT_DATE = "2023-07-01"
PROHIBITED_YEARS = {2024, 2025, 2026}
INITIAL_NAV = 10_000.0
RISK_FRACTION = 0.005
NOTIONAL_CAP_MULTIPLE = 5.0
DISPLAYED_QUEUE_CAP = 0.05
PRIOR_VOLUME_CAP = 0.001
ACK_DELAY_US = 200_000
SIGNAL_COST_BPS = 12.0
MIN_EXPECTANCY_BPS = 5.0
COSTS_BPS = (8.0, 12.0, 18.0)
QTY_STEP = 0.001

LABEL_NO_FILL = 0
LABEL_TARGET = 1
LABEL_STOP = 2
LABEL_NAMES = ("NO_FILL", "FILL_TARGET_FIRST", "FILL_STOP_FIRST")

STRUCTURE_FEATURES = (
    "side",
    "target_distance_bps",
    "stop_distance_bps",
    "structural_rr",
    "leg_bps",
    "raid_overshoot_bps",
    "displacement_atr",
    "fvg_width_bps",
    "raid_to_signal_seconds",
)
L2_FEATURES = (
    "spread_bps",
    "side_depth_imbalance5",
    "side_microprice_skew_bps",
    "log_queue_ahead",
    "side_flow_500ms",
    "side_flow_1s",
    "side_flow_3s",
    "same_side_refill_500ms",
    "opposite_side_depletion_500ms",
    "book_updates_1s",
    "signal_to_order_ms",
)
FEATURES = STRUCTURE_FEATURES + L2_FEATURES


@dataclass(frozen=True)
class StructureSignal:
    event_key: str
    side: int
    raid_time_us: int
    signal_time_us: int
    raid_level: float
    raid_extreme: float
    internal_break: float
    displacement_close: float
    entry_level: float
    stop_price: float
    target_price: float
    atr: float
    fvg_width: float


@dataclass(frozen=True)
class Decision:
    event_key: str
    date: str
    side: int
    signal_time_us: int
    order_time_us: int
    fill_time_us: int | None
    end_time_us: int
    order_price: float
    stop_price: float
    target_price: float
    exit_price: float | None
    queue_ahead: float
    simulated_quantity: float
    prior_60s_volume: float
    label: int
    exit_reason: str
    features: tuple[float, ...]

    @property
    def feature_map(self) -> dict[str, float]:
        return dict(zip(FEATURES, self.features, strict=True))


@dataclass(frozen=True)
class AccountTrade:
    event_key: str
    signal_time_us: int
    fill_time_us: int
    end_time_us: int
    side: int
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    quantity: float
    notional: float
    gross_pnl: float
    cost: float
    net_pnl: float
    nav_before: float
    nav_after: float
    net_return_bps_on_notional: float
    exit_reason: str


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def find_source_manifest(parent_root: Path) -> Path:
    matches = sorted(parent_root.rglob("SOURCE_MANIFEST.json"))
    if not matches:
        raise FileNotFoundError(f"SOURCE_MANIFEST.json not found below {parent_root}")
    for path in matches:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("files"), list):
            return path
    raise RuntimeError(f"no usable source manifest in {matches}")


def download_file(url: str, path: Path, expected_sha256: str, expected_bytes: int | None = None) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and sha256_path(path) == expected_sha256:
        return {"url": url, "path": str(path), "bytes": path.stat().st_size, "sha256": expected_sha256, "reused": True}
    tmp = path.with_suffix(path.suffix + ".part")
    session = requests.Session()
    last: Exception | None = None
    for attempt in range(5):
        try:
            with session.get(url, stream=True, timeout=(30, 240)) as response:
                response.raise_for_status()
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(1 << 20):
                        if chunk:
                            handle.write(chunk)
            observed = sha256_path(tmp)
            if observed != expected_sha256:
                raise RuntimeError(f"sha256 mismatch for {url}: {observed} != {expected_sha256}")
            if expected_bytes is not None and tmp.stat().st_size != int(expected_bytes):
                raise RuntimeError(f"byte mismatch for {url}: {tmp.stat().st_size} != {expected_bytes}")
            tmp.replace(path)
            return {"url": url, "path": str(path), "bytes": path.stat().st_size, "sha256": observed, "reused": False}
        except Exception as exc:  # pragma: no cover - network retry
            last = exc
            if tmp.exists():
                tmp.unlink()
            if attempt == 4:
                raise
            time.sleep(2**attempt)
    raise RuntimeError(last)


def source_rows(parent_root: Path, date: str) -> list[dict[str, object]]:
    year = int(date[:4])
    if year in PROHIBITED_YEARS or year > 2023:
        raise ValueError(f"sealed year requested: {year}")
    manifest_path = find_source_manifest(parent_root)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = [
        row
        for row in payload["files"]
        if str(row.get("date")) == date
        and str(row.get("symbol")) == SYMBOL
        and str(row.get("data_type")) in {"book_snapshot_5", "trades"}
    ]
    types = {str(row["data_type"]) for row in rows}
    if types != {"book_snapshot_5", "trades"} or len(rows) != 2:
        raise RuntimeError(f"expected one book_snapshot_5 and one trades row for {date}, got {rows}")
    return sorted(rows, key=lambda row: str(row["data_type"]))


def acquire_sources(parent_root: Path, date: str, cache: Path) -> tuple[dict[str, Path], list[dict[str, object]]]:
    paths: dict[str, Path] = {}
    records: list[dict[str, object]] = []
    for row in source_rows(parent_root, date):
        url = str(row["url"])
        name = Path(urlparse(url).path).name or f"{row['data_type']}.csv.gz"
        path = cache / date / name
        record = download_file(
            url,
            path,
            str(row["sha256"]),
            int(row["compressed_bytes"]) if row.get("compressed_bytes") is not None else None,
        )
        record.update({"date": date, "symbol": SYMBOL, "data_type": str(row["data_type"])})
        records.append(record)
        paths[str(row["data_type"])] = path
    return paths, records


def _header(path: Path) -> list[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        line = handle.readline().strip()
    return [part.strip() for part in line.split(",")]


def _pick(columns: Sequence[str], *choices: str) -> str:
    for choice in choices:
        if choice in columns:
            return choice
    raise KeyError(f"none of {choices} present in {columns}")


def to_microseconds(values: pd.Series) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    if len(finite):
        median = float(np.nanmedian(np.abs(finite.to_numpy(float))))
        if median > 1e17:
            return (numeric / 1_000.0).round().to_numpy(np.int64)
        if median > 1e14:
            return numeric.round().to_numpy(np.int64)
        if median > 1e11:
            return (numeric * 1_000.0).round().to_numpy(np.int64)
    dt = pd.to_datetime(values, utc=True, errors="coerce", format="mixed")
    return (dt.astype("int64") // 1_000).to_numpy(np.int64)


def read_trades(path: Path) -> pd.DataFrame:
    columns = _header(path)
    time_col = _pick(columns, "local_timestamp", "timestamp")
    price_col = _pick(columns, "price")
    amount_col = _pick(columns, "amount", "quantity", "size")
    side_col = _pick(columns, "side")
    frame = pd.read_csv(path, compression="infer", usecols=[time_col, price_col, amount_col, side_col], low_memory=False)
    frame["us"] = to_microseconds(frame[time_col])
    frame["price"] = pd.to_numeric(frame[price_col], errors="coerce")
    frame["amount"] = pd.to_numeric(frame[amount_col], errors="coerce")
    frame["side"] = frame[side_col].astype(str).str.lower().str.strip()
    frame = frame[np.isfinite(frame["us"]) & np.isfinite(frame["price"]) & np.isfinite(frame["amount"])]
    frame = frame[(frame["price"] > 0) & (frame["amount"] > 0) & frame["side"].isin(["buy", "sell"])]
    frame = frame[["us", "price", "amount", "side"]].sort_values("us", kind="mergesort").reset_index(drop=True)
    if frame.empty:
        raise RuntimeError(f"zero trades parsed from {path}")
    return frame


def read_book(path: Path) -> pd.DataFrame:
    columns = _header(path)
    time_col = _pick(columns, "local_timestamp", "timestamp")
    bid_p = _pick(columns, "bids[0].price", "bid_p0", "bid")
    bid_q = _pick(columns, "bids[0].amount", "bid_q0", "bid_amount")
    ask_p = _pick(columns, "asks[0].price", "ask_p0", "ask")
    ask_q = _pick(columns, "asks[0].amount", "ask_q0", "ask_amount")
    usecols = [time_col, bid_p, bid_q, ask_p, ask_q]
    for level in range(1, 5):
        for name in (f"bids[{level}].price", f"bids[{level}].amount", f"asks[{level}].price", f"asks[{level}].amount"):
            if name in columns:
                usecols.append(name)
    frame = pd.read_csv(path, compression="infer", usecols=usecols, low_memory=False)
    result = pd.DataFrame({
        "us": to_microseconds(frame[time_col]),
        "bid": pd.to_numeric(frame[bid_p], errors="coerce"),
        "bid_q": pd.to_numeric(frame[bid_q], errors="coerce"),
        "ask": pd.to_numeric(frame[ask_p], errors="coerce"),
        "ask_q": pd.to_numeric(frame[ask_q], errors="coerce"),
    })
    bid_depth = result["bid_q"].copy()
    ask_depth = result["ask_q"].copy()
    for level in range(1, 5):
        bq = f"bids[{level}].amount"
        aq = f"asks[{level}].amount"
        if bq in frame:
            bid_depth = bid_depth + pd.to_numeric(frame[bq], errors="coerce").fillna(0.0)
        if aq in frame:
            ask_depth = ask_depth + pd.to_numeric(frame[aq], errors="coerce").fillna(0.0)
    result["bid_depth5"] = bid_depth
    result["ask_depth5"] = ask_depth
    result = result[np.isfinite(result).all(axis=1)]
    result = result[(result["bid"] > 0) & (result["ask"] > result["bid"]) & (result["bid_q"] > 0) & (result["ask_q"] > 0)]
    result = result.sort_values("us", kind="mergesort").drop_duplicates("us", keep="last").reset_index(drop=True)
    if result.empty:
        raise RuntimeError(f"zero book rows parsed from {path}")
    return result


def infer_tick(prices: np.ndarray) -> float:
    unique = np.unique(np.round(prices[np.isfinite(prices)], 8))
    diffs = np.diff(unique)
    diffs = diffs[diffs > 1e-8]
    if not len(diffs):
        return 0.5
    low = np.quantile(diffs, 0.01)
    candidates = diffs[diffs <= max(low * 2.0, low + 1e-8)]
    tick = float(np.median(candidates if len(candidates) else diffs[:100]))
    return max(tick, 1e-8)


def make_bars(trades: pd.DataFrame, seconds: int) -> pd.DataFrame:
    dt = pd.to_datetime(trades["us"].to_numpy(np.int64), unit="us", utc=True)
    indexed = trades.assign(dt=dt).set_index("dt")
    rule = f"{seconds}s"
    grouped = indexed.resample(rule, label="right", closed="left", origin="start_day")
    bars = grouped.agg(open=("price", "first"), high=("price", "max"), low=("price", "min"), close=("price", "last"), volume=("amount", "sum"), count=("price", "count"))
    bars["valid"] = bars["count"].gt(0) & np.isfinite(bars[["open", "high", "low", "close"]]).all(axis=1)
    prev_close = bars["close"].ffill().shift(1)
    tr = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev_close).abs(), (bars["low"] - prev_close).abs()], axis=1).max(axis=1)
    bars["atr20"] = tr.rolling(20, min_periods=20).mean()
    bars["close_us"] = (bars.index.astype("int64") // 1_000).astype(np.int64)
    return bars.reset_index(drop=True)


def confirmed_pivots(bars: pd.DataFrame, span: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    high = bars["high"].to_numpy(float)
    low = bars["low"].to_numpy(float)
    valid = bars["valid"].to_numpy(bool)
    close_us = bars["close_us"].to_numpy(np.int64)
    high_times: list[int] = []
    high_prices: list[float] = []
    low_times: list[int] = []
    low_prices: list[float] = []
    for origin in range(span, len(bars) - span):
        left, right = origin - span, origin + span + 1
        if not valid[left:right].all():
            continue
        hwin = high[left:right]
        lwin = low[left:right]
        confirm = origin + span
        if high[origin] == np.max(hwin) and np.count_nonzero(hwin == high[origin]) == 1:
            high_times.append(int(close_us[confirm]))
            high_prices.append(float(high[origin]))
        if low[origin] == np.min(lwin) and np.count_nonzero(lwin == low[origin]) == 1:
            low_times.append(int(close_us[confirm]))
            low_prices.append(float(low[origin]))
    return (
        np.asarray(high_times, dtype=np.int64),
        np.asarray(high_prices, dtype=float),
        np.asarray(low_times, dtype=np.int64),
        np.asarray(low_prices, dtype=float),
    )


def latest_values(query_us: np.ndarray, event_us: np.ndarray, values: np.ndarray) -> np.ndarray:
    out = np.full(len(query_us), np.nan)
    if not len(event_us):
        return out
    indexes = np.searchsorted(event_us, query_us, side="right") - 1
    mask = indexes >= 0
    out[mask] = values[indexes[mask]]
    return out


def detect_structures(trades: pd.DataFrame) -> list[StructureSignal]:
    bars5 = make_bars(trades, 5)
    bars15 = make_bars(trades, 15)
    bars60 = make_bars(trades, 60)
    e_ht, e_hp, e_lt, e_lp = confirmed_pivots(bars60, 1)
    i_ht, i_hp, i_lt, i_lp = confirmed_pivots(bars15, 1)
    times = bars5["close_us"].to_numpy(np.int64)
    bars5["external_high"] = latest_values(times, e_ht, e_hp)
    bars5["external_low"] = latest_values(times, e_lt, e_lp)
    bars5["internal_high"] = latest_values(times, i_ht, i_hp)
    bars5["internal_low"] = latest_values(times, i_lt, i_lp)
    tick = infer_tick(trades["price"].to_numpy(float))
    signals: list[StructureSignal] = []
    setup: dict[str, float | int] | None = None
    last_raid_key: tuple[int, float] | None = None
    for index in range(2, len(bars5)):
        row = bars5.iloc[index]
        prev = bars5.iloc[index - 1]
        if not bool(row["valid"]) or not bool(prev["valid"]):
            setup = None
            continue
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        atr = float(row["atr20"]) if np.isfinite(row["atr20"]) else math.nan
        if setup is not None:
            side = int(setup["side"])
            raid_extreme = float(setup["raid_extreme"])
            target = float(setup["target"])
            internal = float(setup["internal"])
            invalid = (side == 1 and low < raid_extreme - tick * 0.5) or (side == -1 and high > raid_extreme + tick * 0.5)
            target_consumed = (side == 1 and high >= target) or (side == -1 and low <= target)
            if invalid or target_consumed:
                setup = None
            elif index > int(setup["raid_index"]) and np.isfinite(atr) and atr > 0:
                body = side * (close - float(row["open"]))
                mss = (side == 1 and close > internal) or (side == -1 and close < internal)
                fvg = (side == 1 and low > float(bars5.iloc[index - 2]["high"])) or (side == -1 and high < float(bars5.iloc[index - 2]["low"]))
                fvg_width = (low - float(bars5.iloc[index - 2]["high"])) if side == 1 else (float(bars5.iloc[index - 2]["low"]) - high)
                if mss and fvg and body >= 0.5 * atr and fvg_width > tick * 0.5:
                    leg = abs(close - raid_extreme)
                    entry = close - side * 0.62 * leg
                    stop = raid_extreme - side * tick
                    ordered = (side == 1 and stop < entry < close < target) or (side == -1 and target < close < entry < stop)
                    if ordered:
                        payload = {
                            "side": side,
                            "raid_time_us": int(setup["raid_time_us"]),
                            "signal_time_us": int(row["close_us"]),
                            "raid_level": float(setup["raid_level"]),
                            "raid_extreme": raid_extreme,
                            "internal_break": internal,
                            "displacement_close": close,
                            "entry_level": entry,
                            "stop_price": stop,
                            "target_price": target,
                        }
                        signals.append(StructureSignal(
                            event_key=stable_hash(payload)[:24],
                            atr=atr,
                            fvg_width=float(fvg_width),
                            **payload,
                        ))
                    setup = None
        ext_hi = float(row["external_high"]) if np.isfinite(row["external_high"]) else math.nan
        ext_lo = float(row["external_low"]) if np.isfinite(row["external_low"]) else math.nan
        int_hi = float(row["internal_high"]) if np.isfinite(row["internal_high"]) else math.nan
        int_lo = float(row["internal_low"]) if np.isfinite(row["internal_low"]) else math.nan
        prev_close = float(prev["close"])
        high_raid = np.isfinite(ext_hi) and np.isfinite(ext_lo) and np.isfinite(int_lo) and ext_hi > prev_close and high > ext_hi and close < ext_hi and ext_lo < close
        low_raid = np.isfinite(ext_lo) and np.isfinite(ext_hi) and np.isfinite(int_hi) and ext_lo < prev_close and low < ext_lo and close > ext_lo and ext_hi > close
        if high_raid == low_raid:
            continue
        if low_raid:
            key = (1, float(ext_lo))
            if key != last_raid_key:
                setup = {
                    "side": 1,
                    "raid_index": index,
                    "raid_time_us": int(row["close_us"]),
                    "raid_level": float(ext_lo),
                    "raid_extreme": low,
                    "internal": float(int_hi),
                    "target": float(ext_hi),
                }
                last_raid_key = key
        else:
            key = (-1, float(ext_hi))
            if key != last_raid_key:
                setup = {
                    "side": -1,
                    "raid_index": index,
                    "raid_time_us": int(row["close_us"]),
                    "raid_level": float(ext_hi),
                    "raid_extreme": high,
                    "internal": float(int_lo),
                    "target": float(ext_lo),
                }
                last_raid_key = key
    return signals


def first_index(mask: np.ndarray) -> int | None:
    indexes = np.flatnonzero(mask)
    return int(indexes[0]) if len(indexes) else None


def signed_flow(trade_us: np.ndarray, prices: np.ndarray, amounts: np.ndarray, is_buy: np.ndarray, end_us: int, window_us: int, side: int) -> float:
    left = np.searchsorted(trade_us, end_us - window_us, side="left")
    right = np.searchsorted(trade_us, end_us, side="right")
    if right <= left:
        return 0.0
    buy = float(amounts[left:right][is_buy[left:right]].sum())
    sell = float(amounts[left:right][~is_buy[left:right]].sum())
    return side * (buy - sell) / max(buy + sell, 1e-12)


def _first_barrier_time(trade_us: np.ndarray, prices: np.ndarray, start_us: int, side: int, target: float, stop: float) -> tuple[int, str]:
    start = np.searchsorted(trade_us, start_us, side="right")
    tail = prices[start:]
    if side == 1:
        target_i = first_index(tail >= target)
        stop_i = first_index(tail <= stop)
    else:
        target_i = first_index(tail <= target)
        stop_i = first_index(tail >= stop)
    day_end = int(trade_us[-1]) + 1
    target_us = int(trade_us[start + target_i]) if target_i is not None else day_end
    stop_us = int(trade_us[start + stop_i]) if stop_i is not None else day_end
    if stop_us <= target_us:
        return stop_us, "pending_stop_or_ambiguity"
    return target_us, "pending_target"


def simulate_decision(signal: StructureSignal, date: str, trades: pd.DataFrame, book: pd.DataFrame) -> Decision | None:
    trade_us = trades["us"].to_numpy(np.int64)
    prices = trades["price"].to_numpy(float)
    amounts = trades["amount"].to_numpy(float)
    is_buy = trades["side"].eq("buy").to_numpy(bool)
    book_us = book["us"].to_numpy(np.int64)
    bid = book["bid"].to_numpy(float)
    ask = book["ask"].to_numpy(float)
    bid_q = book["bid_q"].to_numpy(float)
    ask_q = book["ask_q"].to_numpy(float)
    bid_depth = book["bid_depth5"].to_numpy(float)
    ask_depth = book["ask_depth5"].to_numpy(float)
    pending_end_us, pending_reason = _first_barrier_time(trade_us, prices, signal.signal_time_us, signal.side, signal.target_price, signal.stop_price)
    ack_us = signal.signal_time_us + ACK_DELAY_US
    left = np.searchsorted(book_us, ack_us, side="left")
    right = np.searchsorted(book_us, pending_end_us, side="left")
    if right <= left:
        return None
    if signal.side == 1:
        condition = (bid[left:right] <= signal.entry_level) & (bid[left:right] > signal.stop_price) & (ask[left:right] < signal.target_price)
    else:
        condition = (ask[left:right] >= signal.entry_level) & (ask[left:right] < signal.stop_price) & (bid[left:right] > signal.target_price)
    rel = first_index(condition)
    if rel is None:
        return None
    bi = left + rel
    order_time = int(book_us[bi])
    order_price = float(bid[bi] if signal.side == 1 else ask[bi])
    queue_ahead = float(bid_q[bi] if signal.side == 1 else ask_q[bi])
    prior_left = np.searchsorted(trade_us, order_time - 60_000_000, side="left")
    prior_right = np.searchsorted(trade_us, order_time, side="right")
    prior_volume = float(amounts[prior_left:prior_right].sum())
    risk_per_unit = abs(order_price - signal.stop_price) + order_price * SIGNAL_COST_BPS / 10_000.0
    raw_qty = min(
        INITIAL_NAV * RISK_FRACTION / max(risk_per_unit, 1e-12),
        queue_ahead * DISPLAYED_QUEUE_CAP,
        prior_volume * PRIOR_VOLUME_CAP,
        INITIAL_NAV * NOTIONAL_CAP_MULTIPLE / order_price,
    )
    quantity = math.floor(raw_qty / QTY_STEP) * QTY_STEP
    if quantity < QTY_STEP:
        return None
    tleft = np.searchsorted(trade_us, order_time, side="left")
    tright = np.searchsorted(trade_us, pending_end_us, side="left")
    tprice = prices[tleft:tright]
    tamount = amounts[tleft:tright]
    tbuy = is_buy[tleft:tright]
    qualifying = ((~tbuy) & (tprice <= order_price)) if signal.side == 1 else (tbuy & (tprice >= order_price))
    consumed = np.cumsum(np.where(qualifying, tamount, 0.0))
    fill_rel = first_index(consumed >= queue_ahead + quantity - 1e-12)
    fill_time: int | None = None
    label = LABEL_NO_FILL
    exit_price: float | None = None
    exit_reason = pending_reason if pending_end_us < int(trade_us[-1]) + 1 else "source_boundary_no_fill"
    end_time = pending_end_us
    if fill_rel is not None:
        fill_time = int(trade_us[tleft + fill_rel])
        if fill_time < pending_end_us:
            after = np.searchsorted(trade_us, fill_time, side="right")
            tail = prices[after:]
            if signal.side == 1:
                target_rel = first_index(tail >= signal.target_price)
                stop_rel = first_index(tail <= signal.stop_price)
            else:
                target_rel = first_index(tail <= signal.target_price)
                stop_rel = first_index(tail >= signal.stop_price)
            day_end = int(trade_us[-1]) + 1
            target_us = int(trade_us[after + target_rel]) if target_rel is not None else day_end
            stop_us = int(trade_us[after + stop_rel]) if stop_rel is not None else day_end
            if stop_us <= target_us:
                label = LABEL_STOP
                end_time = stop_us
                if stop_us < day_end:
                    observed = float(prices[after + stop_rel])
                    exit_price = min(signal.stop_price, observed) if signal.side == 1 else max(signal.stop_price, observed)
                    exit_reason = "structural_stop_or_same_timestamp"
                else:
                    exit_price = signal.stop_price
                    exit_reason = "source_boundary_full_stop"
            else:
                label = LABEL_TARGET
                end_time = target_us
                exit_price = signal.target_price
                exit_reason = "opposing_external_liquidity"
    mid = 0.5 * (bid[bi] + ask[bi])
    micro = (ask[bi] * bid_q[bi] + bid[bi] * ask_q[bi]) / max(bid_q[bi] + ask_q[bi], 1e-12)
    depth_imbalance = (bid_depth[bi] - ask_depth[bi]) / max(bid_depth[bi] + ask_depth[bi], 1e-12)
    prior_bi = max(0, np.searchsorted(book_us, order_time - 500_000, side="right") - 1)
    if signal.side == 1:
        same_refill = (bid_q[bi] - bid_q[prior_bi]) / max(bid_q[prior_bi], 1e-12) if bid[bi] == bid[prior_bi] else 0.0
        opp_depletion = (ask_q[prior_bi] - ask_q[bi]) / max(ask_q[prior_bi], 1e-12) if ask[bi] == ask[prior_bi] else 0.0
    else:
        same_refill = (ask_q[bi] - ask_q[prior_bi]) / max(ask_q[prior_bi], 1e-12) if ask[bi] == ask[prior_bi] else 0.0
        opp_depletion = (bid_q[prior_bi] - bid_q[bi]) / max(bid_q[prior_bi], 1e-12) if bid[bi] == bid[prior_bi] else 0.0
    updates_1s = bi - np.searchsorted(book_us, order_time - 1_000_000, side="left") + 1
    target_bps = signal.side * (signal.target_price - order_price) / order_price * 10_000.0
    stop_bps = -signal.side * (signal.stop_price - order_price) / order_price * 10_000.0
    stop_bps = abs(stop_bps)
    leg_bps = abs(signal.displacement_close - signal.raid_extreme) / signal.displacement_close * 10_000.0
    overshoot_bps = abs(signal.raid_extreme - signal.raid_level) / signal.raid_level * 10_000.0
    features = (
        float(signal.side),
        float(target_bps),
        float(stop_bps),
        float(target_bps / max(stop_bps, 1e-12)),
        float(leg_bps),
        float(overshoot_bps),
        float(abs(signal.displacement_close - signal.internal_break) / max(signal.atr, 1e-12)),
        float(signal.fvg_width / order_price * 10_000.0),
        float((signal.signal_time_us - signal.raid_time_us) / 1_000_000.0),
        float((ask[bi] - bid[bi]) / mid * 10_000.0),
        float(signal.side * depth_imbalance),
        float(signal.side * (micro - mid) / mid * 10_000.0),
        float(math.log1p(queue_ahead)),
        float(signed_flow(trade_us, prices, amounts, is_buy, order_time, 500_000, signal.side)),
        float(signed_flow(trade_us, prices, amounts, is_buy, order_time, 1_000_000, signal.side)),
        float(signed_flow(trade_us, prices, amounts, is_buy, order_time, 3_000_000, signal.side)),
        float(np.clip(same_refill, -10.0, 10.0)),
        float(np.clip(opp_depletion, -10.0, 10.0)),
        float(updates_1s),
        float((order_time - signal.signal_time_us) / 1_000.0),
    )
    if not np.isfinite(np.asarray(features)).all():
        return None
    return Decision(
        event_key=signal.event_key,
        date=date,
        side=signal.side,
        signal_time_us=signal.signal_time_us,
        order_time_us=order_time,
        fill_time_us=fill_time,
        end_time_us=int(end_time),
        order_price=order_price,
        stop_price=signal.stop_price,
        target_price=signal.target_price,
        exit_price=exit_price,
        queue_ahead=queue_ahead,
        simulated_quantity=quantity,
        prior_60s_volume=prior_volume,
        label=label,
        exit_reason=exit_reason,
        features=features,
    )


def materialize_date(parent_root: Path, date: str, cache: Path) -> tuple[list[Decision], list[dict[str, object]], dict[str, object]]:
    paths, records = acquire_sources(parent_root, date, cache)
    trades = read_trades(paths["trades"])
    book = read_book(paths["book_snapshot_5"])
    signals = detect_structures(trades)
    decisions: list[Decision] = []
    for signal in signals:
        decision = simulate_decision(signal, date, trades, book)
        if decision is not None:
            decisions.append(decision)
    decisions.sort(key=lambda row: (row.signal_time_us, row.event_key))
    source_summary = {
        "date": date,
        "trade_rows": int(len(trades)),
        "book_rows": int(len(book)),
        "structure_signals": int(len(signals)),
        "decision_candidates": int(len(decisions)),
        "label_counts": {LABEL_NAMES[label]: sum(row.label == label for row in decisions) for label in range(3)},
        "first_trade_us": int(trades["us"].iloc[0]),
        "last_trade_us": int(trades["us"].iloc[-1]),
    }
    return decisions, records, source_summary


def feature_matrix(decisions: Sequence[Decision], names: Sequence[str] = FEATURES) -> np.ndarray:
    indexes = [FEATURES.index(name) for name in names]
    return np.asarray([[row.features[index] for index in indexes] for row in decisions], dtype=float)


def expanded_probabilities(model: Pipeline, matrix: np.ndarray) -> np.ndarray:
    raw = model.predict_proba(matrix)
    output = np.zeros((len(matrix), 3), dtype=float)
    classes = model.named_steps["model"].classes_
    for column, label in enumerate(classes):
        output[:, int(label)] = raw[:, column]
    return output


def multiclass_brier(labels: np.ndarray, probabilities: np.ndarray) -> float:
    onehot = np.eye(3)[labels]
    return float(np.mean(np.sum((probabilities - onehot) ** 2, axis=1)))


def fit_models(train: Sequence[Decision]) -> tuple[Pipeline, Pipeline]:
    labels = np.asarray([row.label for row in train], dtype=int)
    if len(np.unique(labels)) < 3:
        raise RuntimeError(f"training slice lacks all three classes: {np.bincount(labels, minlength=3).tolist()}")
    def pipeline() -> Pipeline:
        return Pipeline([
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000, class_weight="balanced", random_state=17)),
        ])
    full = pipeline()
    baseline = pipeline()
    full.fit(feature_matrix(train), labels)
    baseline.fit(feature_matrix(train, STRUCTURE_FEATURES), labels)
    return full, baseline


def exact_expectancy_bps(row: Decision, probabilities: np.ndarray) -> float:
    target = row.side * (row.target_price - row.order_price) / row.order_price * 10_000.0
    stop = row.side * (row.stop_price - row.order_price) / row.order_price * 10_000.0
    fill_probability = probabilities[LABEL_TARGET] + probabilities[LABEL_STOP]
    return float(probabilities[LABEL_TARGET] * target + probabilities[LABEL_STOP] * stop - fill_probability * SIGNAL_COST_BPS)


def quantity_for_nav(row: Decision, nav: float, cost_bps: float) -> float:
    unit_loss = abs(row.order_price - row.stop_price) + row.order_price * cost_bps / 10_000.0
    risk_qty = nav * RISK_FRACTION / max(unit_loss, 1e-12)
    notional_qty = nav * NOTIONAL_CAP_MULTIPLE / row.order_price
    quantity = min(risk_qty, notional_qty, row.simulated_quantity)
    return math.floor(quantity / QTY_STEP) * QTY_STEP


def replay_policy(decisions: Sequence[Decision], selected: dict[str, bool], cost_bps: float, exclude: set[str] | None = None) -> tuple[list[AccountTrade], float, list[float], list[str]]:
    exclude = exclude or set()
    nav = INITIAL_NAV
    busy_until = -1
    trades: list[AccountTrade] = []
    nav_path = [nav]
    accepted: list[str] = []
    for row in sorted(decisions, key=lambda item: (item.signal_time_us, item.event_key)):
        if not selected.get(row.event_key, False) or row.event_key in exclude or row.signal_time_us < busy_until:
            continue
        accepted.append(row.event_key)
        busy_until = row.end_time_us
        if row.label == LABEL_NO_FILL or row.fill_time_us is None or row.exit_price is None:
            continue
        quantity = quantity_for_nav(row, nav, cost_bps)
        if quantity < QTY_STEP:
            continue
        nav_before = nav
        gross = quantity * row.side * (row.exit_price - row.order_price)
        cost = quantity * row.order_price * cost_bps / 10_000.0
        net = gross - cost
        nav = max(nav + net, 0.0)
        net_bps = row.side * (row.exit_price - row.order_price) / row.order_price * 10_000.0 - cost_bps
        trades.append(AccountTrade(
            event_key=row.event_key,
            signal_time_us=row.signal_time_us,
            fill_time_us=row.fill_time_us,
            end_time_us=row.end_time_us,
            side=row.side,
            entry_price=row.order_price,
            exit_price=row.exit_price,
            stop_price=row.stop_price,
            target_price=row.target_price,
            quantity=quantity,
            notional=quantity * row.order_price,
            gross_pnl=gross,
            cost=cost,
            net_pnl=net,
            nav_before=nav_before,
            nav_after=nav,
            net_return_bps_on_notional=net_bps,
            exit_reason=row.exit_reason,
        ))
        nav_path.append(nav)
        if nav <= 0:
            break
    return trades, nav, nav_path, accepted


def maximum_drawdown(nav_path: Sequence[float]) -> float:
    values = np.asarray(nav_path, dtype=float)
    peaks = np.maximum.accumulate(values)
    return float(np.max(1.0 - values / np.maximum(peaks, 1e-12)))


def path_metrics(decisions: Sequence[Decision], selected: dict[str, bool], cost_bps: float) -> dict[str, object]:
    trades, nav, nav_path, accepted = replay_policy(decisions, selected, cost_bps)
    positive = sum(max(row.net_pnl, 0.0) for row in trades)
    negative = -sum(min(row.net_pnl, 0.0) for row in trades)
    profit_factor = positive / negative if negative > 0 else (math.inf if positive > 0 else 0.0)
    returns = [row.net_return_bps_on_notional for row in trades]
    total_return = nav / INITIAL_NAV - 1.0
    if decisions:
        start_day = pd.Timestamp(decisions[0].signal_time_us, unit="us", tz="UTC").floor("D")
        end_day = pd.Timestamp(decisions[-1].end_time_us, unit="us", tz="UTC").floor("D")
        days = max(1, int((end_day - start_day) / pd.Timedelta(days=1)) + 1)
    else:
        days = 1
    positive_trades = sorted((row for row in trades if row.net_pnl > 0), key=lambda row: row.net_pnl, reverse=True)
    removal_count = max(1, math.ceil(0.10 * len(positive_trades))) if positive_trades else 0
    excluded = {row.event_key for row in positive_trades[:removal_count]}
    _, removed_nav, _, _ = replay_policy(decisions, selected, cost_bps, excluded)
    block_returns: list[float] = []
    if decisions:
        start = min(row.signal_time_us for row in decisions)
        end = max(row.end_time_us for row in decisions) + 1
        edges = np.linspace(start, end, 4)
        for block in range(3):
            block_rows = [row for row in trades if edges[block] <= row.signal_time_us < edges[block + 1]]
            block_returns.append(float(sum(row.net_pnl for row in block_rows) / INITIAL_NAV))
    return {
        "cost_bps": cost_bps,
        "accepted_actions": len(accepted),
        "filled_trades": len(trades),
        "final_nav": nav,
        "total_return": total_return,
        "geometric_daily_growth": (nav / INITIAL_NAV) ** (1.0 / days) - 1.0 if nav > 0 else -1.0,
        "maximum_drawdown": maximum_drawdown(nav_path),
        "profit_factor": profit_factor,
        "median_net_return_bps_on_notional": float(np.median(returns)) if returns else math.nan,
        "mean_net_return_bps_on_notional": float(np.mean(returns)) if returns else math.nan,
        "top10pct_winner_removed_return": removed_nav / INITIAL_NAV - 1.0,
        "positive_time_blocks": sum(value > 0 for value in block_returns),
        "time_block_returns": block_returns,
        "liquidation": nav <= 0,
        "target_exits": sum(row.exit_reason == "opposing_external_liquidity" for row in trades),
        "stop_exits": sum(row.exit_reason != "opposing_external_liquidity" for row in trades),
    }


def evaluate_2022(decisions: Sequence[Decision]) -> tuple[dict[str, object], Pipeline | None, dict[str, bool]]:
    if len(decisions) < 10:
        return ({"status": "INSUFFICIENT_DECISIONS", "decision_count": len(decisions), "gate_pass": False, "gate_failures": ["decision_candidates"]}, None, {})
    split = max(1, int(len(decisions) * 0.60))
    train = list(decisions[:split])
    confirmation = list(decisions[split:])
    try:
        full, baseline = fit_models(train)
    except Exception as exc:
        return ({"status": "MODEL_FIT_FAILED", "error": str(exc), "decision_count": len(decisions), "train_count": len(train), "confirmation_count": len(confirmation), "gate_pass": False, "gate_failures": ["all_training_classes"]}, None, {})
    y = np.asarray([row.label for row in confirmation], dtype=int)
    full_p = expanded_probabilities(full, feature_matrix(confirmation))
    base_p = expanded_probabilities(baseline, feature_matrix(confirmation, STRUCTURE_FEATURES))
    prediction = {
        "full_log_loss": float(log_loss(y, full_p, labels=[0, 1, 2])),
        "baseline_log_loss": float(log_loss(y, base_p, labels=[0, 1, 2])),
        "full_brier": multiclass_brier(y, full_p),
        "baseline_brier": multiclass_brier(y, base_p),
        "label_counts": {LABEL_NAMES[label]: int(np.sum(y == label)) for label in range(3)},
    }
    selected: dict[str, bool] = {}
    expectancies: list[float] = []
    for row, probabilities in zip(confirmation, full_p, strict=True):
        expectancy = exact_expectancy_bps(row, probabilities)
        expectancies.append(expectancy)
        selected[row.event_key] = expectancy > MIN_EXPECTANCY_BPS
    paths = {f"{int(cost)}_bps": path_metrics(confirmation, selected, cost) for cost in COSTS_BPS}
    p12 = paths["12_bps"]
    p18 = paths["18_bps"]
    checks = {
        "decision_candidates": len(confirmation) >= 100,
        "filled_trades": int(p12["filled_trades"]) >= 20,
        "full_log_loss_better_than_structure_only": prediction["full_log_loss"] < prediction["baseline_log_loss"],
        "full_brier_better_than_structure_only": prediction["full_brier"] < prediction["baseline_brier"],
        "total_return_12bps": float(p12["total_return"]) > 0,
        "total_return_18bps": float(p18["total_return"]) > 0,
        "median_filled_trade_12bps": float(p12["median_net_return_bps_on_notional"]) > 0 if np.isfinite(p12["median_net_return_bps_on_notional"]) else False,
        "median_filled_trade_18bps": float(p18["median_net_return_bps_on_notional"]) > 0 if np.isfinite(p18["median_net_return_bps_on_notional"]) else False,
        "profit_factor_12bps": float(p12["profit_factor"]) > 1,
        "profit_factor_18bps": float(p18["profit_factor"]) > 1,
        "top10pct_winner_removed_return_12bps": float(p12["top10pct_winner_removed_return"]) > 0,
        "positive_time_blocks_12bps": int(p12["positive_time_blocks"]) >= 2,
        "no_liquidation": not bool(p12["liquidation"]) and not bool(p18["liquidation"]),
    }
    failures = [key for key, passed in checks.items() if not passed]
    result = {
        "status": "CONFIRMATION_GATE_PASS" if not failures else "HARD_VALID_ECONOMIC_FAIL",
        "decision_count": len(decisions),
        "train_count": len(train),
        "confirmation_count": len(confirmation),
        "train_label_counts": {LABEL_NAMES[label]: sum(row.label == label for row in train) for label in range(3)},
        "prediction": prediction,
        "selected_confirmation_actions": sum(selected.values()),
        "expectancy_bps": {
            "minimum": float(np.min(expectancies)) if expectancies else math.nan,
            "median": float(np.median(expectancies)) if expectancies else math.nan,
            "maximum": float(np.max(expectancies)) if expectancies else math.nan,
        },
        "account_paths": paths,
        "gate_checks": checks,
        "gate_failures": failures,
        "gate_pass": not failures,
        "confirmation_event_keys": [row.event_key for row in confirmation],
    }
    return result, full, selected


def evaluate_development(decisions: Sequence[Decision], model: Pipeline) -> dict[str, object]:
    if not decisions:
        return {"status": "NO_DEVELOPMENT_DECISIONS"}
    probabilities = expanded_probabilities(model, feature_matrix(decisions))
    selected = {row.event_key: exact_expectancy_bps(row, p) > MIN_EXPECTANCY_BPS for row, p in zip(decisions, probabilities, strict=True)}
    return {
        "status": "DEVELOPMENT_REPLAYED",
        "decision_count": len(decisions),
        "label_counts": {LABEL_NAMES[label]: sum(row.label == label for row in decisions) for label in range(3)},
        "selected_actions": sum(selected.values()),
        "account_paths": {f"{int(cost)}_bps": path_metrics(decisions, selected, cost) for cost in COSTS_BPS},
    }


def write_decisions(path: Path, decisions: Sequence[Decision]) -> None:
    rows = []
    for row in decisions:
        payload = asdict(row)
        payload["label_name"] = LABEL_NAMES[row.label]
        payload.update({f"feature__{name}": value for name, value in row.feature_map.items()})
        payload.pop("features", None)
        rows.append(payload)
    pd.DataFrame(rows).to_csv(path, index=False)


def self_test() -> int:
    query = np.asarray([10, 20, 30], dtype=np.int64)
    events = np.asarray([5, 25], dtype=np.int64)
    values = np.asarray([1.0, 2.0])
    observed = latest_values(query, events, values)
    np.testing.assert_allclose(observed[:2], [1.0, 1.0])
    assert observed[2] == 2.0
    try:
        source_rows(Path("."), "2024-01-01")
    except ValueError as exc:
        assert "sealed year" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("sealed year was not rejected")
    dummy = Decision(
        event_key="x", date=FIT_DATE, side=1, signal_time_us=0, order_time_us=1, fill_time_us=2, end_time_us=3,
        order_price=100.0, stop_price=99.0, target_price=102.0, exit_price=102.0, queue_ahead=1.0,
        simulated_quantity=0.01, prior_60s_volume=100.0, label=LABEL_TARGET, exit_reason="opposing_external_liquidity",
        features=tuple([1.0] * len(FEATURES)),
    )
    expectancy = exact_expectancy_bps(dummy, np.asarray([0.2, 0.6, 0.2]))
    assert expectancy > 0
    selected = {"x": True}
    low = path_metrics([dummy], selected, 8.0)["final_nav"]
    high = path_metrics([dummy], selected, 18.0)["final_nav"]
    assert low > high
    print(json.dumps({"self_test": "PASS", "feature_count": len(FEATURES)}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-root", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("/tmp/ml-sweep-fvg-maker-cache"))
    parser.add_argument("--output", type=Path, default=Path("research_runs/ml_sweep_fvg_maker_20260726/r11"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.parent_root is None:
        parser.error("--parent-root is required")
    args.output.mkdir(parents=True, exist_ok=True)
    fit_decisions, source_records, fit_source = materialize_date(args.parent_root, FIT_DATE, args.cache)
    fit_result, model, _ = evaluate_2022(fit_decisions)
    development_result: dict[str, object] = {"status": "SEALED_NOT_OPENED"}
    development_source: dict[str, object] | None = None
    development_decisions: list[Decision] = []
    if bool(fit_result.get("gate_pass")):
        development_decisions, dev_records, development_source = materialize_date(args.parent_root, DEVELOPMENT_DATE, args.cache)
        source_records.extend(dev_records)
        if model is None:
            raise RuntimeError("gate passed without fitted model")
        development_result = evaluate_development(development_decisions, model)
    result = {
        "schema_version": 1,
        "result_id": "RES-20260726-ML-SWEEP-FVG-MAKER-001",
        "claim_id": CLAIM_ID,
        "engine_version": ENGINE_VERSION,
        "status": fit_result["status"],
        "decision": "OPEN_DEVELOPMENT" if fit_result.get("gate_pass") else "KILL_EXACT_ROUTE_NO_ADJACENT_TUNING",
        "ranking_role": "NONE_INITIAL_PRE2024_SCREEN",
        "source": {
            "parent_artifact_id": PARENT_ARTIFACT_ID,
            "parent_artifact_sha256": PARENT_ARTIFACT_SHA256,
            "fit": fit_source,
            "development": development_source,
            "download_records": source_records,
        },
        "fit_confirmation": fit_result,
        "development": development_result,
        "sealed": {
            "calendar_2023_opened": bool(fit_result.get("gate_pass")),
            "2024_opened": False,
            "2025_opened": False,
            "2026_opened": False,
        },
        "orders_submitted": False,
        "live_permission_changed": False,
    }
    result["evaluation_contract_sha256"] = stable_hash({
        "engine": ENGINE_VERSION,
        "features": FEATURES,
        "costs": COSTS_BPS,
        "signal_cost": SIGNAL_COST_BPS,
        "min_expectancy": MIN_EXPECTANCY_BPS,
        "risk": RISK_FRACTION,
        "notional_cap": NOTIONAL_CAP_MULTIPLE,
        "ack_delay_us": ACK_DELAY_US,
    })
    (args.output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (args.output / "SOURCE_RECORDS.json").write_text(json.dumps(source_records, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    write_decisions(args.output / "FIT_DECISIONS.csv", fit_decisions)
    if development_decisions:
        write_decisions(args.output / "DEVELOPMENT_DECISIONS.csv", development_decisions)
    print(json.dumps({
        "status": result["status"],
        "decision": result["decision"],
        "fit_decisions": len(fit_decisions),
        "confirmation_gate_pass": bool(fit_result.get("gate_pass")),
        "gate_failures": fit_result.get("gate_failures", []),
        "development_opened": bool(fit_result.get("gate_pass")),
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
