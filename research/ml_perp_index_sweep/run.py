#!/usr/bin/env python3
"""Reproduce RES-20260730-ML-PERP-INDEX-SWEEP-001 from extracted canonical shards."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.market_data.load_canonical_bybit import load_stream, load_trade_bar

SEGMENTS = ("PRE_2024_2021", "PRE_2024_2022", "PRE_2024_2023")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
COSTS = (12, 18, 24)


def aggregate_5m(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    x = frame[frame["observed"]].copy()
    x["start_time_ms"] = x["start_time_ms"] // 300_000 * 300_000
    out = x.groupby("start_time_ms", sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), rows=("available_at_ms", "size"),
    ).reset_index()
    out = out[out["rows"] == 5].drop(columns="rows")
    return out.rename(columns={c: f"{prefix}_{c}" for c in ("open", "high", "low", "close")})


def build_frame(root: Path, segment: str, symbol: str):
    trade5 = load_trade_bar(root, segment, symbol, "5m")
    trade5 = trade5[trade5["is_complete"]].copy()
    index5 = aggregate_5m(load_stream(root, segment, symbol, "index_price_1m"), "idx")
    mark5 = aggregate_5m(load_stream(root, segment, symbol, "mark_price_1m"), "mark")
    minute = load_stream(root, segment, symbol, "trade_price_1m")
    minute = minute[minute["observed"]].sort_values("start_time_ms").reset_index(drop=True)
    funding = load_stream(root, segment, symbol, "funding_events").sort_values("timestamp_ms")
    frame = trade5.merge(index5, on="start_time_ms", how="inner").merge(mark5, on="start_time_ms", how="inner")
    frame = frame.sort_values("start_time_ms").reset_index(drop=True)
    frame["dt"] = pd.to_datetime(frame["start_time_ms"], unit="ms", utc=True)
    frame["day"] = frame["dt"].dt.floor("D")
    previous_close = frame["close"].shift(1)
    true_range = np.maximum(
        frame["high"] - frame["low"],
        np.maximum((frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()),
    )
    frame["atr14_prior"] = true_range.rolling(14, min_periods=14).mean().shift(1)
    return attach_paired_levels(frame), minute, funding


def attach_paired_levels(frame: pd.DataFrame) -> pd.DataFrame:
    records = []
    for day, group in frame.groupby("day", sort=True):
        high_row = group.loc[group["high"].idxmax()]
        low_row = group.loc[group["low"].idxmin()]
        records.append({
            "day": day,
            "d_open": float(group.iloc[0]["open"]),
            "d_high": float(high_row["high"]),
            "d_low": float(low_row["low"]),
            "d_close": float(group.iloc[-1]["close"]),
            "high_idx_level": float(high_row["idx_high"]),
            "low_idx_level": float(low_row["idx_low"]),
        })
    daily = pd.DataFrame(records).set_index("day").sort_index().shift(1).add_prefix("prev_")
    out = frame.join(daily, on="day")
    out["prev_mid"] = (out["prev_d_high"] + out["prev_d_low"]) / 2.0
    return out


def build_events(frame: pd.DataFrame, segment: str, symbol: str) -> pd.DataFrame:
    short = (
        (frame["high"] > frame["prev_d_high"])
        & (frame["idx_high"] <= frame["prev_high_idx_level"])
        & (frame["close"] < frame["prev_d_high"])
    )
    long = (
        (frame["low"] < frame["prev_d_low"])
        & (frame["idx_low"] >= frame["prev_low_idx_level"])
        & (frame["close"] > frame["prev_d_low"])
    )
    events = frame[short | long].copy()
    events["direction"] = np.where(long.loc[events.index], 1, -1)
    first_high = frame[frame["high"] > frame["prev_d_high"]].groupby("day")["start_time_ms"].min()
    first_low = frame[frame["low"] < frame["prev_d_low"]].groupby("day")["start_time_ms"].min()
    events["first_consumption_ms"] = np.where(
        events["direction"] > 0, events["day"].map(first_low), events["day"].map(first_high)
    )
    events = events[events["start_time_ms"] == events["first_consumption_ms"]].copy()
    events["level"] = np.where(events["direction"] > 0, events["prev_d_low"], events["prev_d_high"])
    events["idx_level"] = np.where(
        events["direction"] > 0, events["prev_low_idx_level"], events["prev_high_idx_level"]
    )
    events["raid_extreme"] = np.where(events["direction"] > 0, events["low"], events["high"])
    events["raid_depth_atr"] = np.where(
        events["direction"] > 0,
        (events["level"] - events["low"]) / events["atr14_prior"],
        (events["high"] - events["level"]) / events["atr14_prior"],
    )
    events["symbol"] = symbol
    events["segment"] = segment
    events["year"] = int(segment[-4:])
    return events


def first_at_or_after(values: np.ndarray, timestamp_ms: int) -> int:
    return int(np.searchsorted(values, timestamp_ms, side="left"))


def target_for(row: pd.Series, entry: float) -> float | None:
    refs = [float(row["prev_d_open"]), float(row["prev_mid"]), float(row["prev_d_close"])]
    if int(row["direction"]) > 0:
        candidates = [value for value in refs if np.isfinite(value) and value > entry]
        return min(candidates) if candidates else None
    candidates = [value for value in refs if np.isfinite(value) and value < entry]
    return max(candidates) if candidates else None


def simulate(row: pd.Series, frame: pd.DataFrame, minute: pd.DataFrame, funding: pd.DataFrame):
    direction = int(row["direction"])
    decision_ms = int(row["available_at_ms"])
    entry_time_ms = decision_ms + 60_000
    minute_times = minute["start_time_ms"].to_numpy(np.int64)
    entry_index = first_at_or_after(minute_times, entry_time_ms)
    if entry_index >= len(minute) or int(minute_times[entry_index]) != entry_time_ms:
        return None
    entry = float(minute.iloc[entry_index]["open"])
    atr = float(row["atr14_prior"])
    stop = float(row["raid_extreme"]) - 0.10 * atr if direction > 0 else float(row["raid_extreme"]) + 0.10 * atr
    target = target_for(row, entry)
    if target is None or (direction > 0 and not stop < entry < target) or (direction < 0 and not target < entry < stop):
        return None

    later = frame[frame["start_time_ms"] > int(row["start_time_ms"])]
    if direction > 0:
        lost = later[(later["close"] < float(row["level"])) & (later["idx_close"] < float(row["idx_level"]))]
    else:
        lost = later[(later["close"] > float(row["level"])) & (later["idx_close"] > float(row["idx_level"]))]
    loss_time = int(lost.iloc[0]["available_at_ms"]) + 60_000 if not lost.empty else None
    scan_end = loss_time if loss_time is not None else int(minute_times[-1]) + 1
    end_index = first_at_or_after(minute_times, scan_end)
    exit_time = exit_price = exit_type = None
    for index in range(entry_index, min(end_index + 1, len(minute))):
        bar = minute.iloc[index]
        opened, high, low, timestamp = float(bar["open"]), float(bar["high"]), float(bar["low"]), int(bar["start_time_ms"])
        if direction > 0:
            if low <= stop:
                exit_time, exit_price, exit_type = timestamp, min(opened, stop), "stop"
                break
            if high >= target:
                exit_time, exit_price, exit_type = timestamp, target, "target"
                break
        else:
            if high >= stop:
                exit_time, exit_price, exit_type = timestamp, max(opened, stop), "stop"
                break
            if low <= target:
                exit_time, exit_price, exit_type = timestamp, target, "target"
                break
    if exit_time is None and loss_time is not None:
        index = first_at_or_after(minute_times, loss_time)
        if index < len(minute) and int(minute_times[index]) == loss_time:
            exit_time, exit_price, exit_type = loss_time, float(minute.iloc[index]["open"]), "state_loss"
    if exit_time is None:
        return None

    settlements = funding[(funding["timestamp_ms"] >= entry_time_ms) & (funding["timestamp_ms"] < exit_time)]
    signed_funding = float(direction * settlements["funding_rate"].sum())
    result = {
        "entry_time_ms": entry_time_ms, "exit_time_ms": int(exit_time), "entry_price": entry,
        "exit_price": float(exit_price), "stop_price": stop, "target_price": target, "exit_type": exit_type,
        "holding_hours": (int(exit_time) - entry_time_ms) / 3_600_000,
        "gross_unit_return": direction * (float(exit_price) / entry - 1.0),
        "stop_distance": abs(stop / entry - 1.0), "target_distance": abs(target / entry - 1.0),
        "funding_signed": signed_funding,
    }
    for cost in COSTS:
        unit_return = result["gross_unit_return"] - cost / 10_000.0 - signed_funding
        loss_per_unit = result["stop_distance"] + cost / 10_000.0
        notional_multiple = min(3.0, 0.005 / loss_per_unit)
        result[f"account_return_{cost}"] = unit_return * notional_multiple
    return result


def route_global_slot(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    routed = frame.copy()
    routed["structural_rr"] = routed["target_distance"] / routed["stop_distance"]
    routed = routed.sort_values(
        ["entry_time_ms", "structural_rr", "symbol"], ascending=[True, False, True], kind="stable"
    )
    selected, free_at = [], -1
    for _, row in routed.iterrows():
        if int(row["entry_time_ms"]) < free_at:
            continue
        selected.append(row)
        free_at = int(row["exit_time_ms"])
    return pd.DataFrame(selected)


def summarize(frame: pd.DataFrame, cost: int, calendar_days: int) -> dict:
    if frame.empty:
        return {"trades": 0}
    returns = frame[f"account_return_{cost}"].astype(float).to_numpy()
    nav = np.cumprod(1.0 + returns)
    path = np.r_[1.0, nav]
    drawdown = path / np.maximum.accumulate(path) - 1.0
    positives = np.sort(returns[returns > 0])[::-1]
    return {
        "trades": int(len(frame)), "nav_multiple": float(nav[-1]), "return": float(nav[-1] - 1.0),
        "geometric_daily_growth": float(math.exp(math.log(float(nav[-1])) / calendar_days) - 1.0),
        "profit_factor": float(returns[returns > 0].sum() / -returns[returns < 0].sum()),
        "max_drawdown": float(drawdown.min()), "median_account_return": float(np.median(returns)),
        "positive_fraction": float((returns > 0).mean()),
        "top5_positive_pnl_share": float(positives[:5].sum() / positives.sum()) if positives.sum() else None,
        "stops": int((frame["exit_type"] == "stop").sum()),
        "targets": int((frame["exit_type"] == "target").sum()),
        "state_loss_exits": int((frame["exit_type"] == "state_loss").sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="Extracted canonical root containing segment/symbol")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    candidates = []
    event_counts = {}
    for segment in SEGMENTS:
        for symbol in SYMBOLS:
            market, minute, funding = build_frame(args.root, segment, symbol)
            events = build_events(market, segment, symbol)
            event_counts[f"{segment}:{symbol}"] = int(len(events))
            for _, event in events.iterrows():
                outcome = simulate(event, market, minute, funding)
                if outcome is not None:
                    record = event.to_dict()
                    record.update(outcome)
                    candidates.append(record)
    candidate_frame = pd.DataFrame(candidates).sort_values("entry_time_ms").reset_index(drop=True)
    selected_frames, summary = [], {"event_counts": event_counts}
    for year in (2021, 2022, 2023):
        selected = route_global_slot(candidate_frame[candidate_frame["year"] == year])
        selected_frames.append(selected)
        summary[str(year)] = {str(cost): summarize(selected, cost, 365) for cost in COSTS}
    all_selected = pd.concat(selected_frames, ignore_index=True).sort_values("entry_time_ms").reset_index(drop=True)
    summary["diagnostic_2021_2023"] = {str(cost): summarize(all_selected, cost, 1095) for cost in COSTS}
    candidate_frame.to_parquet(args.out / "candidate_outcomes.parquet", index=False)
    all_selected.to_parquet(args.out / "global_slot_outcomes.parquet", index=False)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
