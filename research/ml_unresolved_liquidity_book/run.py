#!/usr/bin/env python3
"""Reproduce the deterministic unresolved-liquidity-book screen.

The input root must be an extracted canonical tree containing
PRE_2024_2021..2023/<symbol>/... as registered by the project.
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

SEGMENTS = ("PRE_2024_2021", "PRE_2024_2022", "PRE_2024_2023")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TIMEFRAMES = (("15m", 3, 1.0), ("1h", 2, 2.0), ("4h", 1, 4.0))
THRESHOLDS = (0.25, 0.5, 0.75, 1.0, 1.5)
COSTS = (12, 18, 24)
MAX_AGE_DAYS = 90
HALF_LIFE_DAYS = 30.0


def load_concat(root: Path, symbol: str, relative_path: str) -> pd.DataFrame:
    frames = [pd.read_parquet(root / segment / symbol / relative_path) for segment in SEGMENTS]
    out = pd.concat(frames, ignore_index=True)
    key = "start_time_ms" if "start_time_ms" in out.columns else "timestamp_ms"
    return out.sort_values(key).drop_duplicates(key, keep="last").reset_index(drop=True)


def confirmed_pivots(root: Path, symbol: str) -> pd.DataFrame:
    records: list[tuple[int, str, float, float, str, int]] = []
    for timeframe, right, weight in TIMEFRAMES:
        bars = load_concat(root, symbol, f"trade_bars/{timeframe}.parquet")
        bars = bars[bars["is_complete"]].reset_index(drop=True)
        highs = bars["high"].to_numpy(float)
        lows = bars["low"].to_numpy(float)
        for index in range(right, len(bars) - right):
            if (
                highs[index] > highs[index - right:index].max()
                and highs[index] > highs[index + 1:index + right + 1].max()
            ):
                records.append((
                    int(bars.iloc[index + right]["available_at_ms"]),
                    "H",
                    float(highs[index]),
                    float(weight),
                    timeframe,
                    int(bars.iloc[index]["start_time_ms"]),
                ))
            if (
                lows[index] < lows[index - right:index].min()
                and lows[index] < lows[index + 1:index + right + 1].min()
            ):
                records.append((
                    int(bars.iloc[index + right]["available_at_ms"]),
                    "L",
                    float(lows[index]),
                    float(weight),
                    timeframe,
                    int(bars.iloc[index]["start_time_ms"]),
                ))
    return pd.DataFrame(
        records,
        columns=["available_at_ms", "side", "price", "tf_weight", "tf", "origin_ms"],
    ).sort_values("available_at_ms").reset_index(drop=True)


def build_signals(root: Path, symbol: str) -> pd.DataFrame:
    bars = load_concat(root, symbol, "trade_bars/15m.parquet")
    bars = bars[bars["is_complete"]].reset_index(drop=True)
    previous_close = bars["close"].shift(1)
    true_range = np.maximum(
        bars["high"] - bars["low"],
        np.maximum(
            (bars["high"] - previous_close).abs(),
            (bars["low"] - previous_close).abs(),
        ),
    )
    bars["atr"] = true_range.rolling(64, min_periods=64).mean().shift(1)
    levels = confirmed_pivots(root, symbol)
    level_index = 0
    active_highs: list[tuple[float, float, int, str, int]] = []
    active_lows: list[tuple[float, float, int, str, int]] = []
    previous_direction = {threshold: 0 for threshold in THRESHOLDS}
    day_ms = 86_400_000
    rows: list[dict[str, object]] = []

    for bar in bars.itertuples(index=False):
        now = int(bar.available_at_ms)
        start = int(bar.start_time_ms)
        while level_index < len(levels) and int(levels.iloc[level_index]["available_at_ms"]) <= now:
            level = levels.iloc[level_index]
            item = (
                float(level["price"]),
                float(level["tf_weight"]),
                int(level["available_at_ms"]),
                str(level["tf"]),
                int(level["origin_ms"]),
            )
            (active_highs if level["side"] == "H" else active_lows).append(item)
            level_index += 1

        # A level that was already available before the current bar is retired
        # at its first current-bar trade-through. A level confirmed only at the
        # current close cannot be consumed retroactively by this bar.
        active_highs = [item for item in active_highs if not (item[2] <= start and float(bar.high) >= item[0])]
        active_lows = [item for item in active_lows if not (item[2] <= start and float(bar.low) <= item[0])]
        cutoff = now - MAX_AGE_DAYS * day_ms
        active_highs = [item for item in active_highs if item[2] >= cutoff]
        active_lows = [item for item in active_lows if item[2] >= cutoff]

        close = float(bar.close)
        atr = float(bar.atr) if np.isfinite(bar.atr) and float(bar.atr) > 0 else np.nan
        if not np.isfinite(atr):
            continue
        highs = [item for item in active_highs if item[0] > close]
        lows = [item for item in active_lows if item[0] < close]
        if not highs or not lows:
            continue

        def weighted(items: list[tuple[float, float, int, str, int]]) -> list[tuple[float, float, float, float, float, str, int, int]]:
            values = []
            for price, weight, available_at, timeframe, origin in items:
                distance = abs(price - close) / atr
                if distance > 20:
                    continue
                age_days = (now - available_at) / day_ms
                decay = 2.0 ** (-age_days / HALF_LIFE_DAYS)
                mass = weight * decay / (0.25 + distance)
                values.append((mass, distance, price, weight, age_days, timeframe, available_at, origin))
            return sorted(values, key=lambda value: value[1])

        upward = weighted(highs)
        downward = weighted(lows)
        if not upward or not downward:
            continue
        upward_mass = sum(value[0] for value in upward[:50])
        downward_mass = sum(value[0] for value in downward[:50])
        imbalance = math.log((upward_mass + 1e-12) / (downward_mass + 1e-12))

        for threshold in THRESHOLDS:
            direction = 1 if imbalance >= threshold else -1 if imbalance <= -threshold else 0
            if direction and previous_direction[threshold] != direction:
                target = upward[0] if direction > 0 else downward[0]
                stop = downward[0] if direction > 0 else upward[0]
                rows.append({
                    "symbol": symbol,
                    "threshold": threshold,
                    "decision_ms": now,
                    "bar_start_ms": start,
                    "direction": direction,
                    "close": close,
                    "atr": atr,
                    "imbalance": imbalance,
                    "up_mass": upward_mass,
                    "down_mass": downward_mass,
                    "target_price": target[2],
                    "target_tf": target[5],
                    "target_age_days": target[4],
                    "stop_price": stop[2],
                    "stop_tf": stop[5],
                    "stop_age_days": stop[4],
                    "target_dist_atr": target[1],
                    "stop_dist_atr": stop[1],
                    "active_up": len(upward),
                    "active_down": len(downward),
                })
            previous_direction[threshold] = direction
    return pd.DataFrame(rows)


def simulate_symbol(root: Path, symbol: str, events: pd.DataFrame) -> pd.DataFrame:
    minute = load_concat(root, symbol, "streams/trade_price_1m.parquet")
    minute = minute[minute["observed"]].reset_index(drop=True)
    minute_times = minute["start_time_ms"].to_numpy(np.int64)
    opens = minute["open"].to_numpy(float)
    highs = minute["high"].to_numpy(float)
    lows = minute["low"].to_numpy(float)
    funding = load_concat(root, symbol, "streams/funding_events.parquet")
    funding_times = funding["timestamp_ms"].to_numpy(np.int64)
    funding_rates = funding["funding_rate"].to_numpy(float)

    candidates = events.copy().sort_values("decision_ms").reset_index(drop=True)
    # A completed 15m state becomes known at the boundary. With 500ms fixed
    # latency, the minute whose open equals the boundary is already underway;
    # the first executable observed open is one minute later.
    candidates["entry_time_ms"] = candidates["decision_ms"].astype("int64") + 60_000
    locations = np.searchsorted(minute_times, candidates["entry_time_ms"].to_numpy(np.int64), side="left")
    valid = locations < len(minute_times)
    exact = np.zeros(len(candidates), dtype=bool)
    exact[valid] = minute_times[locations[valid]] == candidates.loc[valid, "entry_time_ms"].to_numpy(np.int64)
    candidates = candidates[exact].copy().reset_index(drop=True)
    locations = locations[exact]
    candidates["entry_price"] = opens[locations]
    geometry = (
        ((candidates["direction"] > 0) & (candidates["stop_price"] < candidates["entry_price"]) & (candidates["entry_price"] < candidates["target_price"]))
        | ((candidates["direction"] < 0) & (candidates["target_price"] < candidates["entry_price"]) & (candidates["entry_price"] < candidates["stop_price"]))
    )
    candidates = candidates[geometry].copy().reset_index(drop=True)

    starts: dict[int, list[int]] = {}
    for index, timestamp in enumerate(candidates["entry_time_ms"].to_numpy(np.int64)):
        starts.setdefault(int(timestamp), []).append(index)
    status = np.zeros(len(candidates), dtype=np.int8)
    exit_times = np.full(len(candidates), -1, dtype=np.int64)
    exit_prices = np.full(len(candidates), np.nan)
    exit_types = np.empty(len(candidates), dtype=object)
    long_stops: list[tuple[float, int]] = []
    long_targets: list[tuple[float, int]] = []
    short_stops: list[tuple[float, int]] = []
    short_targets: list[tuple[float, int]] = []

    for minute_index, timestamp in enumerate(minute_times):
        for candidate_index in starts.get(int(timestamp), []):
            status[candidate_index] = 1
            row = candidates.iloc[candidate_index]
            if int(row["direction"]) > 0:
                heapq.heappush(long_stops, (-float(row["stop_price"]), candidate_index))
                heapq.heappush(long_targets, (float(row["target_price"]), candidate_index))
            else:
                heapq.heappush(short_stops, (float(row["stop_price"]), candidate_index))
                heapq.heappush(short_targets, (-float(row["target_price"]), candidate_index))

        # Adverse boundary first when the one-minute path is ambiguous.
        while long_stops and -long_stops[0][0] >= lows[minute_index]:
            _, candidate_index = heapq.heappop(long_stops)
            if status[candidate_index] != 1:
                continue
            status[candidate_index] = 2
            exit_times[candidate_index] = int(timestamp)
            exit_prices[candidate_index] = min(opens[minute_index], float(candidates.iloc[candidate_index]["stop_price"]))
            exit_types[candidate_index] = "stop"
        while short_stops and short_stops[0][0] <= highs[minute_index]:
            _, candidate_index = heapq.heappop(short_stops)
            if status[candidate_index] != 1:
                continue
            status[candidate_index] = 2
            exit_times[candidate_index] = int(timestamp)
            exit_prices[candidate_index] = max(opens[minute_index], float(candidates.iloc[candidate_index]["stop_price"]))
            exit_types[candidate_index] = "stop"
        while long_targets and long_targets[0][0] <= highs[minute_index]:
            _, candidate_index = heapq.heappop(long_targets)
            if status[candidate_index] != 1:
                continue
            status[candidate_index] = 2
            exit_times[candidate_index] = int(timestamp)
            exit_prices[candidate_index] = float(candidates.iloc[candidate_index]["target_price"])
            exit_types[candidate_index] = "target"
        while short_targets and -short_targets[0][0] >= lows[minute_index]:
            _, candidate_index = heapq.heappop(short_targets)
            if status[candidate_index] != 1:
                continue
            status[candidate_index] = 2
            exit_times[candidate_index] = int(timestamp)
            exit_prices[candidate_index] = float(candidates.iloc[candidate_index]["target_price"])
            exit_types[candidate_index] = "target"

    completed = np.flatnonzero(status == 2)
    outcomes = candidates.iloc[completed].copy().reset_index(drop=True)
    outcomes["exit_time_ms"] = exit_times[completed]
    outcomes["exit_price"] = exit_prices[completed]
    outcomes["exit_type"] = exit_types[completed]
    outcomes["holding_hours"] = (outcomes["exit_time_ms"] - outcomes["entry_time_ms"]) / 3_600_000
    outcomes["gross_unit_return"] = outcomes["direction"] * (outcomes["exit_price"] / outcomes["entry_price"] - 1.0)
    funding_prefix = np.r_[0.0, np.cumsum(funding_rates)]
    left = np.searchsorted(funding_times, outcomes["entry_time_ms"].to_numpy(np.int64), side="left")
    right = np.searchsorted(funding_times, outcomes["exit_time_ms"].to_numpy(np.int64), side="left")
    outcomes["funding_signed"] = outcomes["direction"].to_numpy(float) * (funding_prefix[right] - funding_prefix[left])
    outcomes["stop_distance"] = (outcomes["stop_price"] / outcomes["entry_price"] - 1.0).abs()
    outcomes["target_distance"] = (outcomes["target_price"] / outcomes["entry_price"] - 1.0).abs()
    for cost in COSTS:
        cost_fraction = cost / 10_000.0
        unit_return = outcomes["gross_unit_return"] - cost_fraction - outcomes["funding_signed"]
        loss_per_unit = outcomes["stop_distance"] + cost_fraction
        notional_multiple = np.minimum(3.0, 0.005 / loss_per_unit)
        outcomes[f"account_return_{cost}"] = unit_return * notional_multiple
    return outcomes


def route_global_strict(outcomes: pd.DataFrame, threshold: float) -> pd.DataFrame:
    candidates = outcomes[outcomes["threshold"] == threshold].copy()
    candidates["structural_rr"] = candidates["target_distance"] / candidates["stop_distance"]
    candidates = candidates.sort_values(
        ["entry_time_ms", "structural_rr", "symbol"],
        ascending=[True, False, True],
        kind="stable",
    )
    selected: list[dict[str, object]] = []
    occupied_exit_bucket = -1
    for row in candidates.itertuples(index=False):
        if int(row.entry_time_ms) <= occupied_exit_bucket:
            continue
        selected.append(row._asdict())
        occupied_exit_bucket = int(row.exit_time_ms)
    return pd.DataFrame(selected)


def summarize(frame: pd.DataFrame, cost: int, calendar_days: int) -> dict[str, object]:
    returns = frame[f"account_return_{cost}"].to_numpy(float)
    nav = np.cumprod(1.0 + returns)
    path = np.r_[1.0, nav]
    drawdown = path / np.maximum.accumulate(path) - 1.0
    positives = returns[returns > 0]
    negatives = returns[returns < 0]
    sorted_positive = np.sort(positives)[::-1]
    return {
        "trades": int(len(frame)),
        "nav_multiple": float(nav[-1]),
        "total_return": float(nav[-1] - 1.0),
        "geometric_daily_growth": float(math.exp(math.log(float(nav[-1])) / calendar_days) - 1.0),
        "profit_factor": float(positives.sum() / -negatives.sum()),
        "maximum_drawdown": float(drawdown.min()),
        "median_account_return": float(np.median(returns)),
        "win_rate": float((returns > 0).mean()),
        "top5_positive_pnl_share": float(sorted_positive[:5].sum() / sorted_positive.sum()),
        "targets": int((frame["exit_type"] == "target").sum()),
        "stops": int((frame["exit_type"] == "stop").sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    all_outcomes = []
    counts: dict[str, object] = {}
    for symbol in SYMBOLS:
        signals = build_signals(args.root, symbol)
        outcomes = simulate_symbol(args.root, symbol, signals)
        signals.to_parquet(args.out / f"{symbol}_signals.parquet", index=False)
        outcomes.to_parquet(args.out / f"{symbol}_outcomes.parquet", index=False)
        counts[symbol] = {"signals": int(len(signals)), "resolved_outcomes": int(len(outcomes))}
        all_outcomes.append(outcomes)
    combined = pd.concat(all_outcomes, ignore_index=True)

    summary: dict[str, object] = {"counts": counts, "thresholds": {}}
    for threshold in THRESHOLDS:
        selected = route_global_strict(combined, threshold)
        selected.to_parquet(args.out / f"global_strict_{threshold}.parquet", index=False)
        summary["thresholds"][str(threshold)] = {
            str(cost): summarize(selected, cost, 1095) for cost in COSTS
        }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
