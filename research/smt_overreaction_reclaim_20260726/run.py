from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests

import base_probe as base

CLAIM_ID = "CLM-20260726-1530-SMT-OVERREACTION-RECLAIM-001"
RESULT_ID = "RES-20260726-SMT-OVERREACTION-RECLAIM-001"
DATES = ("2023-09-24", "2023-10-22", "2023-11-26", "2023-12-31")
SYMBOLS = ("BTCUSDT", "SOLUSDT", "XRPUSDT")
FOLLOWERS = ("SOLUSDT", "XRPUSDT")
HORIZONS = (1, 2, 5)
GAPS = (0.0012, 0.0018, 0.0024)
LATENCIES = (100, 300)
PATHS = ("immediate", "mss")
COSTS = (12, 18, 24)
BINS_PER_SECOND = 10
BINS_PER_DAY = 24 * 60 * 60 * BINS_PER_SECOND
MAX_TRADE_DELAY_SECONDS = 1.0


@dataclass(slots=True)
class RawTape:
    times: np.ndarray
    prices: np.ndarray
    signed_notional: np.ndarray
    total_notional: np.ndarray
    trade_count: np.ndarray
    age_bins: np.ndarray
    flow_imbalance_1s: np.ndarray
    trade_count_1s: np.ndarray


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    x = np.nan_to_num(np.asarray(values, dtype=np.float64), nan=0.0)
    cumulative = np.concatenate((np.array([0.0]), np.cumsum(x, dtype=np.float64)))
    end = np.arange(1, len(x) + 1)
    start = np.maximum(0, end - window)
    return cumulative[end] - cumulative[start]


def age_from_count(count: np.ndarray) -> np.ndarray:
    observed = np.asarray(count) > 0
    index = np.arange(len(observed), dtype=np.int64)
    last = np.maximum.accumulate(np.where(observed, index, -1))
    return np.where(last >= 0, index - last, np.iinfo(np.int32).max).astype(np.int32)


def first_true(mask: np.ndarray, start: int) -> int | None:
    if start >= len(mask):
        return None
    hit = np.flatnonzero(np.asarray(mask[start:], dtype=bool))
    return None if not len(hit) else int(start + hit[0])


def first_run(mask: np.ndarray, start: int, length: int) -> int | None:
    if start >= len(mask) or len(mask) - start < length:
        return None
    x = np.asarray(mask[start:], dtype=np.int8)
    cumulative = np.concatenate((np.array([0], dtype=np.int64), np.cumsum(x, dtype=np.int64)))
    totals = cumulative[length:] - cumulative[:-length]
    hit = np.flatnonzero(totals == length)
    return None if not len(hit) else int(start + hit[0] + length - 1)


def normalize_timestamp_seconds(values: np.ndarray) -> np.ndarray:
    x = np.asarray(values, dtype=np.float64)
    finite = x[np.isfinite(x)]
    if not len(finite):
        return x
    scale = float(np.nanmedian(np.abs(finite)))
    if scale >= 1e14:
        return x / 1_000_000.0
    if scale >= 1e11:
        return x / 1_000.0
    return x


def resolve_column(columns: Iterable[str], names: tuple[str, ...]) -> str:
    lookup = {str(column).strip().lower(): str(column) for column in columns}
    for name in names:
        if name.lower() in lookup:
            return lookup[name.lower()]
    raise RuntimeError(f"none of required columns {names} found in {sorted(lookup)}")


def load_raw_tape(path: Path, date: str) -> RawTape:
    header = pd.read_csv(path, compression="gzip", nrows=0).columns
    timestamp_column = resolve_column(header, ("timestamp", "time", "trade_time"))
    price_column = resolve_column(header, ("price",))
    side_column = resolve_column(header, ("side",))
    size_column = resolve_column(header, ("size", "qty", "quantity", "volume"))
    usecols = [timestamp_column, price_column, side_column, size_column]
    day_start = float(base.utc_start(date))

    signed = np.zeros(BINS_PER_DAY, dtype=np.float64)
    total = np.zeros(BINS_PER_DAY, dtype=np.float64)
    count = np.zeros(BINS_PER_DAY, dtype=np.int32)
    raw_times: list[np.ndarray] = []
    raw_prices: list[np.ndarray] = []

    for chunk in pd.read_csv(path, compression="gzip", usecols=usecols, chunksize=500_000):
        timestamp = normalize_timestamp_seconds(
            pd.to_numeric(chunk[timestamp_column], errors="coerce").to_numpy(np.float64)
        )
        price = pd.to_numeric(chunk[price_column], errors="coerce").to_numpy(np.float64)
        size = pd.to_numeric(chunk[size_column], errors="coerce").to_numpy(np.float64)
        side = chunk[side_column].astype("string").str.lower().to_numpy()
        valid = (
            np.isfinite(timestamp)
            & np.isfinite(price)
            & np.isfinite(size)
            & (price > 0)
            & (size > 0)
        )
        if not valid.any():
            continue
        timestamp = timestamp[valid]
        price = price[valid]
        size = size[valid]
        side = side[valid]
        bin_index = np.floor((timestamp - day_start) * BINS_PER_SECOND + 1e-9).astype(np.int64)
        in_day = (bin_index >= 0) & (bin_index < BINS_PER_DAY)
        if not in_day.any():
            continue
        timestamp = timestamp[in_day]
        price = price[in_day]
        size = size[in_day]
        side = side[in_day]
        bin_index = bin_index[in_day]
        notional = price * size
        direction = np.where(np.char.lower(side.astype(str)) == "buy", 1.0, -1.0)
        total += np.bincount(bin_index, weights=notional, minlength=BINS_PER_DAY)
        signed += np.bincount(bin_index, weights=notional * direction, minlength=BINS_PER_DAY)
        count += np.bincount(bin_index, minlength=BINS_PER_DAY).astype(np.int32)
        raw_times.append(timestamp)
        raw_prices.append(price)

    if not raw_times:
        raise RuntimeError(f"no usable raw trades in {path}")
    times = np.concatenate(raw_times)
    prices = np.concatenate(raw_prices)
    order = np.argsort(times, kind="stable")
    times = times[order]
    prices = prices[order]
    age = age_from_count(count)
    signed_1s = rolling_sum(signed, 10)
    total_1s = rolling_sum(total, 10)
    count_1s = rolling_sum(count.astype(np.float64), 10)
    imbalance = np.divide(
        signed_1s,
        total_1s,
        out=np.full(BINS_PER_DAY, np.nan, dtype=np.float64),
        where=total_1s > 0,
    )
    return RawTape(
        times=times,
        prices=prices,
        signed_notional=signed,
        total_notional=total,
        trade_count=count,
        age_bins=age,
        flow_imbalance_1s=imbalance,
        trade_count_1s=count_1s,
    )


def attention(leader: dict[str, np.ndarray], follower: dict[str, np.ndarray], horizon: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(leader["mark"])
    leader_count = leader["trade_count"].reshape(-1, 10).sum(axis=1).astype(float)
    follower_count = follower["trade_count"].reshape(-1, 10).sum(axis=1).astype(float)
    leader_sum = pd.Series(leader_count).rolling(1800, min_periods=1).sum().to_numpy(float)
    follower_sum = pd.Series(follower_count).rolling(1800, min_periods=1).sum().to_numpy(float)
    trade_ratio = np.divide(
        follower_sum,
        leader_sum,
        out=np.full_like(follower_sum, np.nan),
        where=leader_sum > 0,
    )
    leader_return = pd.Series(np.log(leader["mark"][9::10])).diff()
    follower_return = pd.Series(np.log(follower["mark"][9::10])).diff()

    def volatility_state(series: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        finite = series.notna()
        count = finite.astype(np.int16).rolling(900, min_periods=1).sum().to_numpy(float)
        nonzero = (
            (series.fillna(0).abs() > 0)
            .astype(np.int16)
            .rolling(900, min_periods=1)
            .sum()
            .to_numpy(float)
        )
        squared = (series.fillna(0) ** 2).rolling(900, min_periods=1).sum().to_numpy(float)
        return squared, count, nonzero

    leader_squared, leader_valid, leader_nonzero = volatility_state(leader_return)
    follower_squared, follower_valid, follower_nonzero = volatility_state(follower_return)
    usable = (
        (leader_valid >= 600)
        & (follower_valid >= 600)
        & (leader_nonzero >= 60)
        & (follower_nonzero >= 60)
        & (leader_squared > 0)
    )
    volatility_ratio = np.full_like(leader_squared, np.nan)
    volatility_ratio[usable] = np.sqrt(follower_squared[usable] / leader_squared[usable])
    index = np.arange(n, dtype=np.int64)
    prior_second = (index + 1 - horizon * 10) // 10 - 1
    valid = (prior_second >= 0) & (prior_second < len(trade_ratio))
    trade_output = np.full(n, np.nan)
    volatility_output = np.full(n, np.nan)
    trade_output[valid] = trade_ratio[prior_second[valid]]
    volatility_output[valid] = volatility_ratio[prior_second[valid]]
    return trade_output, volatility_output


def first_rearm(mark: np.ndarray, index: int, start: int, direction: int, shock: float) -> int:
    signed = direction * np.log(mark[index:] / mark[start])
    condition = np.isfinite(signed) & (signed <= 0.25 * shock)
    release = first_run(condition, 0, 10)
    return len(mark) if release is None else int(index + release + 1)


def select_overreaction_events(
    features: dict[str, np.ndarray],
    trade_ratio: np.ndarray,
    volatility_ratio: np.ndarray,
    gap_floor: float,
) -> list[dict[str, Any]]:
    common = (
        np.isfinite(features["z"])
        & np.isfinite(features["gap"])
        & np.isfinite(features["under"])
        & np.isfinite(features["activity"])
        & np.isfinite(trade_ratio)
        & np.isfinite(volatility_ratio)
        & (features["z"] >= 3)
        & (features["leader_align"] >= 0.5)
        & (features["activity"] >= 2)
        & (trade_ratio >= 1)
        & (volatility_ratio >= 1.5)
    )
    mask = (
        common
        & (features["under"] >= 1.25)
        & (features["follower_align"] >= 0.5)
        & ((-features["gap"]) >= gap_floor)
    )
    candidates = np.flatnonzero(mask)
    events: list[dict[str, Any]] = []
    allowed = 0
    mark = features["leader_mark"]
    for raw_index in candidates:
        index = int(raw_index)
        if index < allowed:
            continue
        start = int(features["start_idx"][index])
        direction = int(features["direction"][index])
        shock = abs(float(features["btc_return"][index]))
        if start < 0 or direction == 0 or not np.isfinite(mark[start]):
            continue
        release = first_rearm(mark, index, start, direction, shock)
        allowed = max(index + 1, release)
        events.append(
            {
                "decision_bin": index,
                "start_idx": start,
                "direction": direction,
                "z": float(features["z"][index]),
                "gap": float(-features["gap"][index]),
                "expected": float(features["expected"][index]),
                "beta": float(features["beta"][index]),
                "btc_return": float(features["btc_return"][index]),
                "under": float(features["under"][index]),
                "activity": float(features["activity"][index]),
                "leader_align": float(features["leader_align"][index]),
                "follower_align": float(features["follower_align"][index]),
                "trade_ratio": float(trade_ratio[index]),
                "volatility_ratio": float(volatility_ratio[index]),
                "release_bin": int(release),
            }
        )
    return events


def first_trade(tape: RawTape, timestamp: float) -> tuple[float, float] | None:
    index = int(np.searchsorted(tape.times, timestamp, side="left"))
    if index >= len(tape.times):
        return None
    trade_time = float(tape.times[index])
    if trade_time - timestamp > MAX_TRADE_DELAY_SECONDS:
        return None
    return trade_time, float(tape.prices[index])


def event_state(
    leader: dict[str, np.ndarray],
    follower: dict[str, np.ndarray],
    leader_age: np.ndarray,
    follower_age: np.ndarray,
    event: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    start = int(event["start_idx"])
    direction = int(event["direction"])
    beta = float(event["beta"])
    leader_start = float(leader["mark"][start])
    follower_start = float(follower["mark"][start])
    with np.errstate(divide="ignore", invalid="ignore"):
        leader_move = direction * np.log(leader["mark"] / leader_start)
        follower_move = direction * np.log(follower["mark"] / follower_start)
    residual = follower_move - beta * leader_move
    fresh = (
        np.isfinite(residual)
        & np.isfinite(leader_move)
        & (leader_age <= 10)
        & (follower_age <= 10)
    )
    return residual, leader_move, fresh


def synthetic_stop_trade(
    event: dict[str, Any],
    path: str,
    latency_ms: int,
    entry_time: float,
    entry_price: float,
    exit_time: float,
    reason: str,
    unavailable: bool,
) -> dict[str, Any]:
    gap = float(event["gap"])
    return {
        "event_id": event["event_id"],
        "date": event["date"],
        "symbol": event["symbol"],
        "horizon": int(event["horizon"]),
        "gap_floor_bps": int(event["gap_floor_bps"]),
        "path": path,
        "latency_ms": latency_ms,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "entry_price": entry_price,
        "exit_price": None,
        "gross_bps": -0.5 * gap * 10_000.0,
        "event_gap_bps": gap * 10_000.0,
        "z": float(event["z"]),
        "exit_reason": reason,
        "boundary_loss": reason == "SOURCE_BOUNDARY_FULL_STOP",
        "unavailable": bool(unavailable),
    }


def simulate_event(
    leader: dict[str, np.ndarray],
    follower: dict[str, np.ndarray],
    leader_age: np.ndarray,
    tape: RawTape,
    event: dict[str, Any],
    path: str,
    latency_ms: int,
) -> tuple[dict[str, Any] | None, str]:
    day_start = float(base.utc_start(event["date"]))
    day_end = day_start + 24 * 60 * 60
    residual, leader_move, fresh = event_state(
        leader, follower, leader_age, tape.age_bins, event
    )
    decision = int(event["decision_bin"])
    gap = float(event["gap"])
    direction = int(event["direction"])

    instant_invalidation = fresh & ((residual >= 1.5 * gap) | (leader_move <= 0))
    stale_run = first_run(~fresh, decision + 1, 10)
    if path == "mss":
        opposite_flow = (
            np.isfinite(tape.flow_imbalance_1s)
            & (direction * tape.flow_imbalance_1s < 0)
            & (tape.trade_count_1s >= 3)
        )
        confirmation_mask = (
            fresh
            & (residual <= 0.8 * gap)
            & (residual > 0.25 * gap)
            & opposite_flow
        )
        confirmation = first_true(confirmation_mask, decision + 1)
        pre_invalidation = first_true(instant_invalidation, decision + 1)
        earliest_failure = min(
            [value for value in (pre_invalidation, stale_run) if value is not None],
            default=None,
        )
        if confirmation is None:
            return None, "NO_MSS_CONFIRMATION"
        if earliest_failure is not None and earliest_failure <= confirmation:
            return None, "INVALID_BEFORE_MSS"
        activation_bin = confirmation
    else:
        activation_bin = decision

    activation_time = day_start + (activation_bin + 1) / BINS_PER_SECOND
    entry = first_trade(tape, activation_time + latency_ms / 1000.0)
    if entry is None:
        return None, "UNAVAILABLE_ENTRY"
    entry_time, entry_price = entry
    entry_bin = int(math.floor((entry_time - day_start) * BINS_PER_SECOND))
    entry_bin = max(decision + 1, min(BINS_PER_DAY - 1, entry_bin))
    interim_failure = first_true(instant_invalidation, activation_bin + 1)
    if interim_failure is not None and interim_failure <= entry_bin:
        return None, "INVALID_DURING_ENTRY_LATENCY"

    with np.errstate(divide="ignore", invalid="ignore"):
        extension = direction * np.log(follower["mark"] / entry_price)
    invalidation = fresh & (
        (residual >= 1.5 * gap)
        | (extension >= 0.5 * gap)
        | (leader_move <= 0)
    )
    target = fresh & (residual <= 0.25 * gap)
    scan_start = max(decision + 1, entry_bin + 1)
    target_index = first_run(target, scan_start, 10)
    invalidation_index = first_true(invalidation, scan_start)
    unavailable_index = first_run(~fresh, scan_start, 10)

    candidates = [
        (invalidation_index, "INVALIDATION"),
        (unavailable_index, "STATE_GAP_FULL_STOP"),
        (target_index, "EQUILIBRIUM_RECLAIM"),
    ]
    candidates = [(index, reason) for index, reason in candidates if index is not None]
    if not candidates:
        return (
            synthetic_stop_trade(
                event,
                path,
                latency_ms,
                entry_time,
                entry_price,
                day_end,
                "SOURCE_BOUNDARY_FULL_STOP",
                False,
            ),
            "TRADE",
        )
    candidates.sort(key=lambda item: (item[0], 0 if item[1] != "EQUILIBRIUM_RECLAIM" else 1))
    exit_bin, exit_reason = candidates[0]
    if exit_reason == "STATE_GAP_FULL_STOP":
        return (
            synthetic_stop_trade(
                event,
                path,
                latency_ms,
                entry_time,
                entry_price,
                day_start + (exit_bin + 1) / BINS_PER_SECOND,
                exit_reason,
                True,
            ),
            "TRADE",
        )

    trigger_time = day_start + (exit_bin + 1) / BINS_PER_SECOND
    exit_trade = first_trade(tape, trigger_time + latency_ms / 1000.0)
    if exit_trade is None:
        return (
            synthetic_stop_trade(
                event,
                path,
                latency_ms,
                entry_time,
                entry_price,
                trigger_time,
                "UNAVAILABLE_EXIT_FULL_STOP",
                True,
            ),
            "TRADE",
        )
    exit_time, exit_price = exit_trade
    side = -direction
    gross_bps = side * math.log(exit_price / entry_price) * 10_000.0
    return (
        {
            "event_id": event["event_id"],
            "date": event["date"],
            "symbol": event["symbol"],
            "horizon": int(event["horizon"]),
            "gap_floor_bps": int(event["gap_floor_bps"]),
            "path": path,
            "latency_ms": latency_ms,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "gross_bps": gross_bps,
            "event_gap_bps": gap * 10_000.0,
            "z": float(event["z"]),
            "exit_reason": exit_reason,
            "boundary_loss": False,
            "unavailable": False,
        },
        "TRADE",
    )


def policy_key(path: str, horizon: int, gap_bps: int, latency_ms: int) -> str:
    return f"{path}|h{horizon}|g{gap_bps}|l{latency_ms}"


def candidate_specs() -> list[tuple[str, int, int, int]]:
    return [
        (path, horizon, gap_bps, latency)
        for path in PATHS
        for horizon in HORIZONS
        for gap_bps in (12, 18, 24)
        for latency in LATENCIES
    ]


def route_trades(
    potential: list[dict[str, Any]], excluded_event_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    excluded = excluded_event_ids or set()
    accepted: list[dict[str, Any]] = []
    for date in DATES:
        rows = [
            row
            for row in potential
            if row["date"] == date and row["event_id"] not in excluded
        ]
        rows.sort(
            key=lambda row: (
                row["entry_time"],
                -row["event_gap_bps"],
                -row["z"],
                row["symbol"],
                row["event_id"],
            )
        )
        slot_free = -math.inf
        for row in rows:
            if row["entry_time"] <= slot_free:
                continue
            accepted.append(row)
            slot_free = float(row["exit_time"])
    accepted.sort(key=lambda row: (row["entry_time"], row["symbol"], row["event_id"]))
    return accepted


def account_return(row: dict[str, Any], cost_bps: int) -> tuple[float, float]:
    gap_fraction = float(row["event_gap_bps"]) / 10_000.0
    planned_loss_per_notional = 0.5 * gap_fraction + cost_bps / 10_000.0
    leverage = min(3.0, 0.01 / planned_loss_per_notional)
    value = leverage * (float(row["gross_bps"]) - cost_bps) / 10_000.0
    return max(-0.999999, value), leverage


def account_metrics(trades: list[dict[str, Any]], cost_bps: int) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda row: (row["entry_time"], row["event_id"]))
    net_bps = np.array([float(row["gross_bps"]) - cost_bps for row in ordered], dtype=float)
    account_returns: list[float] = []
    leverages: list[float] = []
    nav = 1.0
    peak = 1.0
    maximum_drawdown = 0.0
    daily_factor = {date: 1.0 for date in DATES}
    for row in ordered:
        value, leverage = account_return(row, cost_bps)
        account_returns.append(value)
        leverages.append(leverage)
        nav *= 1.0 + value
        daily_factor[row["date"]] *= 1.0 + value
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, 1.0 - nav / peak)
    positive_bps = net_bps[net_bps > 0]
    negative_bps = net_bps[net_bps < 0]
    if len(negative_bps):
        profit_factor = float(positive_bps.sum() / abs(negative_bps.sum()))
    elif len(positive_bps):
        profit_factor = 999.0
    else:
        profit_factor = 0.0
    positive_account = np.array([value for value in account_returns if value > 0], dtype=float)
    top_five_share = (
        float(np.sort(positive_account)[-5:].sum() / positive_account.sum())
        if len(positive_account) and positive_account.sum() > 0
        else 1.0
    )
    total_return = nav - 1.0
    geometric_sample_day = nav ** (1.0 / len(DATES)) - 1.0 if nav > 0 else -1.0
    return {
        "trade_count": len(ordered),
        "mean_net_bps": float(net_bps.mean()) if len(net_bps) else None,
        "median_net_bps": float(np.median(net_bps)) if len(net_bps) else None,
        "profit_factor": profit_factor,
        "total_return": total_return,
        "geometric_sample_day_growth": geometric_sample_day,
        "maximum_drawdown": maximum_drawdown,
        "positive_dates": int(sum(value > 1.0 for value in daily_factor.values())),
        "daily_returns": {date: value - 1.0 for date, value in daily_factor.items()},
        "top_five_positive_pnl_share": top_five_share,
        "boundary_loss_count": int(sum(bool(row["boundary_loss"]) for row in ordered)),
        "unavailable_trade_count": int(sum(bool(row["unavailable"]) for row in ordered)),
        "median_leverage": float(np.median(leverages)) if leverages else 0.0,
    }


def top_winner_exclusions(trades: list[dict[str, Any]]) -> set[str]:
    if not trades:
        return set()
    positive: list[tuple[float, str]] = []
    for row in trades:
        value, _ = account_return(row, 18)
        if value > 0:
            positive.append((value, str(row["event_id"])))
    positive.sort(reverse=True)
    removal_count = int(math.ceil(0.10 * len(trades)))
    return {event_id for _, event_id in positive[:removal_count]}


def write_csv(path: Path, rows: list[dict[str, Any]], compress: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        if compress:
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                stream.write("")
        else:
            path.write_text("", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row})
    opener = gzip.open if compress else open
    kwargs = {"mode": "wt", "encoding": "utf-8", "newline": ""} if compress else {"mode": "w", "encoding": "utf-8", "newline": ""}
    with opener(path, **kwargs) as stream:  # type: ignore[arg-type]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def process_date(
    date: str,
    cache: Path,
    potential: dict[str, list[dict[str, Any]]],
    diagnostics: dict[str, dict[str, int]],
    event_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
) -> None:
    arrays: dict[str, dict[str, np.ndarray]] = {}
    tapes: dict[str, RawTape] = {}
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-smt-overreaction-reclaim/1.0"
        for symbol in SYMBOLS:
            url = f"https://public.bybit.com/trading/{symbol}/{symbol}{date}.csv.gz"
            target = cache / symbol / f"{symbol}{date}.csv.gz"
            payload = base._download(session, url, target)
            record = base.inspect_source(target, symbol, date, url, payload)
            if not record.timestamp_monotonic:
                raise RuntimeError(f"nonmonotonic source {url}")
            arrays[symbol] = base.aggregate(target, date)
            source_rows.append(asdict(record))
            if symbol in FOLLOWERS:
                tapes[symbol] = load_raw_tape(target, date)
            print(stable_json(asdict(record)), flush=True)

    leader = arrays["BTCUSDT"]
    leader_age = age_from_count(leader["trade_count"])
    for symbol in FOLLOWERS:
        follower = arrays[symbol]
        tape = tapes[symbol]
        for horizon in HORIZONS:
            features = base.continuous_features(leader, follower, horizon)
            trade_ratio, volatility_ratio = attention(leader, follower, horizon)
            for gap in GAPS:
                gap_bps = int(round(gap * 10_000))
                events = select_overreaction_events(features, trade_ratio, volatility_ratio, gap)
                for event in events:
                    event.update(
                        {
                            "date": date,
                            "symbol": symbol,
                            "horizon": horizon,
                            "gap_floor_bps": gap_bps,
                        }
                    )
                    event["event_id"] = hashlib.sha256(
                        stable_json(
                            [date, symbol, horizon, gap_bps, event["decision_bin"]]
                        ).encode()
                    ).hexdigest()[:24]
                    event_rows.append(dict(event))
                    for path in PATHS:
                        for latency in LATENCIES:
                            key = policy_key(path, horizon, gap_bps, latency)
                            trade, status = simulate_event(
                                leader,
                                follower,
                                leader_age,
                                tape,
                                event,
                                path,
                                latency,
                            )
                            diagnostics[key][status] = diagnostics[key].get(status, 0) + 1
                            if trade is not None:
                                potential[key].append(trade)
            del features, trade_ratio, volatility_ratio
    del arrays, tapes


def evaluate(
    potential: dict[str, list[dict[str, Any]]],
    diagnostics: dict[str, dict[str, int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    candidate_results: list[dict[str, Any]] = []
    routed_ledger: list[dict[str, Any]] = []
    for path, horizon, gap_bps, latency in candidate_specs():
        key = policy_key(path, horizon, gap_bps, latency)
        routed = route_trades(potential[key])
        excluded = top_winner_exclusions(routed)
        rerouted = route_trades(potential[key], excluded)
        base_metrics = {str(cost): account_metrics(routed, cost) for cost in COSTS}
        removed_metrics = account_metrics(rerouted, 18)
        unavailable_attempts = sum(
            count
            for status, count in diagnostics[key].items()
            if status.startswith("UNAVAILABLE")
        )
        result = {
            "candidate_id": hashlib.sha256(key.encode()).hexdigest()[:20],
            "policy_key": key,
            "path": path,
            "horizon_seconds": horizon,
            "gap_floor_bps": gap_bps,
            "latency_ms": latency,
            "potential_trade_count": len(potential[key]),
            "diagnostics": diagnostics[key],
            "unavailable_attempt_count": unavailable_attempts,
            "base_metrics": base_metrics,
            "winner_removed_event_ids": sorted(excluded),
            "winner_removed_18bp_metrics": removed_metrics,
        }
        candidate_results.append(result)
        for row in routed:
            routed_ledger.append({"policy_key": key, **row})

    by_pair: dict[tuple[str, int, int], dict[int, dict[str, Any]]] = {}
    for result in candidate_results:
        pair = (result["path"], result["horizon_seconds"], result["gap_floor_bps"])
        by_pair.setdefault(pair, {})[result["latency_ms"]] = result

    pair_results: list[dict[str, Any]] = []
    for pair, latency_results in sorted(by_pair.items()):
        path, horizon, gap_bps = pair
        checks: dict[str, bool] = {}
        for latency in LATENCIES:
            result = latency_results[latency]
            metrics_24 = result["base_metrics"]["24"]
            metrics_18 = result["base_metrics"]["18"]
            removed = result["winner_removed_18bp_metrics"]
            prefix = f"latency_{latency}ms"
            checks[f"{prefix}_minimum_20_trades"] = metrics_24["trade_count"] >= 20
            checks[f"{prefix}_positive_24bp_mean"] = (
                metrics_24["mean_net_bps"] is not None and metrics_24["mean_net_bps"] > 0
            )
            checks[f"{prefix}_positive_24bp_median"] = (
                metrics_24["median_net_bps"] is not None and metrics_24["median_net_bps"] > 0
            )
            checks[f"{prefix}_positive_removed_18bp_return"] = removed["total_return"] > 0
            checks[f"{prefix}_three_positive_dates_18bp"] = metrics_18["positive_dates"] >= 3
            checks[f"{prefix}_top_five_share_at_most_0_4"] = (
                metrics_18["top_five_positive_pnl_share"] <= 0.4
            )
            checks[f"{prefix}_zero_unavailable"] = (
                result["unavailable_attempt_count"] == 0
                and metrics_18["unavailable_trade_count"] == 0
            )
            checks[f"{prefix}_removed_geometric_growth_at_least_1pct"] = (
                removed["geometric_sample_day_growth"] >= 0.01
            )
        passed = all(checks.values())
        pair_result = {
            "path": path,
            "horizon_seconds": horizon,
            "gap_floor_bps": gap_bps,
            "gate_passed": passed,
            "main_strategy_eligible": path == "mss" and passed,
            "gate_checks": checks,
            "candidate_ids": {
                str(latency): latency_results[latency]["candidate_id"] for latency in LATENCIES
            },
        }
        pair_results.append(pair_result)
        for latency in LATENCIES:
            latency_results[latency]["pair_gate_passed"] = passed
            latency_results[latency]["main_strategy_eligible"] = path == "mss" and passed
    return candidate_results, pair_results, routed_ledger


def flatten_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        row = {
            "candidate_id": result["candidate_id"],
            "policy_key": result["policy_key"],
            "path": result["path"],
            "horizon_seconds": result["horizon_seconds"],
            "gap_floor_bps": result["gap_floor_bps"],
            "latency_ms": result["latency_ms"],
            "potential_trade_count": result["potential_trade_count"],
            "unavailable_attempt_count": result["unavailable_attempt_count"],
            "pair_gate_passed": result["pair_gate_passed"],
            "main_strategy_eligible": result["main_strategy_eligible"],
        }
        for cost in COSTS:
            metrics = result["base_metrics"][str(cost)]
            for key in (
                "trade_count",
                "mean_net_bps",
                "median_net_bps",
                "profit_factor",
                "total_return",
                "geometric_sample_day_growth",
                "maximum_drawdown",
                "positive_dates",
                "top_five_positive_pnl_share",
                "boundary_loss_count",
                "unavailable_trade_count",
                "median_leverage",
            ):
                row[f"cost_{cost}_{key}"] = metrics[key]
        removed = result["winner_removed_18bp_metrics"]
        for key in (
            "trade_count",
            "total_return",
            "geometric_sample_day_growth",
            "maximum_drawdown",
            "positive_dates",
        ):
            row[f"removed_18_{key}"] = removed[key]
        rows.append(row)
    return rows


def self_test() -> None:
    assert len(candidate_specs()) == 36
    mask = np.array([False, True, True, True, False])
    assert first_run(mask, 0, 3) == 3
    assert first_true(mask, 2) == 2
    seconds = normalize_timestamp_seconds(np.array([1_700_000_000_000.0]))
    assert abs(seconds[0] - 1_700_000_000.0) < 1e-6
    sample = [
        {"date": DATES[0], "entry_time": 1.0, "exit_time": 3.0, "event_gap_bps": 20.0, "z": 4.0, "symbol": "SOLUSDT", "event_id": "a"},
        {"date": DATES[0], "entry_time": 2.0, "exit_time": 4.0, "event_gap_bps": 30.0, "z": 5.0, "symbol": "XRPUSDT", "event_id": "b"},
        {"date": DATES[0], "entry_time": 4.0, "exit_time": 5.0, "event_gap_bps": 10.0, "z": 3.0, "symbol": "SOLUSDT", "event_id": "c"},
    ]
    routed = route_trades(sample)
    assert [row["event_id"] for row in routed] == ["a", "c"]
    stop_row = {"event_gap_bps": 20.0, "gross_bps": -10.0}
    value, leverage = account_return(stop_row, 18)
    assert leverage <= 3.0 and value < 0
    print("SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.cache is None or args.output is None:
        parser.error("--cache and --output are required unless --self-test is used")
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    potential = {policy_key(*spec): [] for spec in candidate_specs()}
    diagnostics = {policy_key(*spec): {} for spec in candidate_specs()}
    event_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    started = time.time()
    for date in DATES:
        process_date(date, args.cache, potential, diagnostics, event_rows, source_rows)
        print(stable_json({"completed_date": date, "elapsed_seconds": time.time() - started}), flush=True)

    candidate_results, pair_results, routed_ledger = evaluate(potential, diagnostics)
    main_survivors = [row for row in pair_results if row["main_strategy_eligible"]]
    control_survivors = [row for row in pair_results if row["gate_passed"] and row["path"] == "immediate"]
    best = max(
        candidate_results,
        key=lambda row: (
            row["winner_removed_18bp_metrics"]["geometric_sample_day_growth"],
            row["base_metrics"]["18"]["geometric_sample_day_growth"],
            row["base_metrics"]["18"]["trade_count"],
        ),
    )
    source_fingerprint = hashlib.sha256(stable_json(source_rows).encode()).hexdigest()
    result = {
        "schema_version": 1,
        "result_id": RESULT_ID,
        "claim_id": CLAIM_ID,
        "status": "FATAL_SCREEN_SURVIVOR" if main_survivors else "TESTED_BELOW_GATE",
        "hard_validity": "PASS",
        "economic_status": "MAIN_MSS_GATE_PASS" if main_survivors else "MAIN_MSS_GATE_FAILED",
        "ranking_role": "NOT_RANK_ELIGIBLE_PRE2024_FATAL_SCREEN",
        "candidate_count": len(candidate_results),
        "pair_count": len(pair_results),
        "main_mss_survivor_count": len(main_survivors),
        "immediate_control_survivor_count": len(control_survivors),
        "main_survivors": main_survivors,
        "control_survivors": control_survivors,
        "best_raw_candidate": best,
        "opportunity_event_rows": len(event_rows),
        "source_count": len(source_rows),
        "source_fingerprint": source_fingerprint,
        "dates": list(DATES),
        "official_2024_opened": False,
        "official_2025_opened": False,
        "official_2026_opened": False,
        "orders_submitted": False,
        "paper_or_live_enabled": False,
        "funding_included": False,
        "execution_note": "Public target trades plus explicit 12/18/24-bp all-in stress; any MSS survivor requires exact Bybit BBO/depth and funding reconstruction before official 2024.",
        "elapsed_seconds": time.time() - started,
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "candidate_results.json").write_text(json.dumps(candidate_results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "pair_results.json").write_text(json.dumps(pair_results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "source_manifest.json").write_text(json.dumps(source_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_csv(output / "candidate_metrics.csv", flatten_candidates(candidate_results))
    write_csv(output / "events.csv.gz", event_rows, compress=True)
    write_csv(output / "routed_trade_ledger.csv.gz", routed_ledger, compress=True)
    summary = [
        "# SMT overreaction MSS reclaim fatal screen",
        "",
        f"- status: `{result['status']}`",
        f"- hard validity: `{result['hard_validity']}`",
        f"- candidates: `{result['candidate_count']}`",
        f"- main MSS survivors: `{result['main_mss_survivor_count']}`",
        f"- immediate-control survivors: `{result['immediate_control_survivor_count']}`",
        f"- opportunity event rows: `{result['opportunity_event_rows']}`",
        f"- best raw policy: `{best['policy_key']}`",
        f"- best winner-removed 18-bp sample-day growth: `{best['winner_removed_18bp_metrics']['geometric_sample_day_growth']:.8%}`",
        "",
        "No 2024-2026 source or order path was opened.",
    ]
    (output / "SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    hashes = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "OUTPUT_SHA256SUMS.txt":
            hashes.append(f"{sha256_file(path)}  {path.relative_to(output)}")
    (output / "OUTPUT_SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")
    print(stable_json(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
