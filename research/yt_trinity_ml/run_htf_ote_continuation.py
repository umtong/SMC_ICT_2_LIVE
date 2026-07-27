#!/usr/bin/env python3
"""Fifth alpha: completed 1h order flow -> 5m OTE/FVG/CISD continuation.

A trade exists only inside the 62%-79% retracement of a confirmed one-hour
structure/displacement leg.  The five-minute chart must then show delivery
reversal in the higher-timeframe direction and a causal FVG/BPR/IFVG entry zone.
Stops and targets remain structural; no session or elapsed-time exit exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run_cisd_bpr_ifvg_research as engine
from system.core import EventCandidate, FeatureConfig, build_causal_features


class OteFamily(str, Enum):
    HTF_OTE_FVG_CONTINUATION = "HTF_OTE_FVG_CONTINUATION"


def numeric_row(row: pd.Series) -> dict[str, float]:
    return {
        str(key): float(value)
        for key, value in row.items()
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)
    }


def one_hour_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if "bar_start" not in frame.columns:
        raise ValueError("five-minute frame lacks bar_start")
    raw = frame.copy()
    raw["hour_start"] = pd.DatetimeIndex(pd.to_datetime(raw["bar_start"], utc=True)).floor("1h")
    grouped = raw.groupby("hour_start", sort=True)
    output = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        turnover=("turnover", "sum"),
        mark_close=("mark_close", "last"),
        source_rows=("close", "size"),
    )
    output = output[output["source_rows"] == 12].copy()
    output["bar_start"] = output.index
    output.index = pd.DatetimeIndex(output["bar_start"]) + pd.Timedelta(hours=1)
    output.index.name = "available_at"
    return output.drop(columns=["source_rows"])


def bars_since_event(series: pd.Series) -> pd.Series:
    positions = np.arange(len(series), dtype=float)
    event_position = pd.Series(np.where(series.notna(), positions, np.nan), index=series.index).ffill()
    return pd.Series(positions, index=series.index) - event_position


def attach_htf_context(five: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    context = hourly.copy()
    context["htf_bull_bos_recent"] = context["bull_bos"].rolling(12, min_periods=1).max()
    context["htf_bear_bos_recent"] = context["bear_bos"].rolling(12, min_periods=1).max()
    selected = [
        "atr", "body_atr", "ema_fast", "ema_slow", "ema_long",
        "ema_fast_slope_atr", "ema_slow_slope_atr", "ema_spread_atr",
        "last_swing_high", "last_swing_low", "previous_day_high", "previous_day_low",
        "previous_week_high", "previous_week_low", "bull_bos", "bear_bos",
        "htf_bull_bos_recent", "htf_bear_bos_recent", "rsi", "macd_hist_atr",
        "volume_z", "distance_vwap_atr", "bollinger_bandwidth",
    ]
    right = context[selected].rename(columns={name: f"htf_{name}" for name in selected})
    left = five.reset_index().rename(columns={five.index.name or "index": "decision_time"})
    right_reset = right.reset_index().rename(columns={right.index.name or "index": "htf_available_at"})
    merged = pd.merge_asof(
        left.sort_values("decision_time"),
        right_reset.sort_values("htf_available_at"),
        left_on="decision_time",
        right_on="htf_available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    merged.index = pd.DatetimeIndex(merged["decision_time"])
    merged.index.name = five.index.name
    return merged.drop(columns=["decision_time"])


def delivery_origin(features: pd.DataFrame, position: int, side: int) -> float | None:
    for index in range(position - 1, max(-1, position - 8), -1):
        row = features.iloc[index]
        if side > 0 and float(row["close"]) < float(row["open"]):
            return float(row["open"])
        if side < 0 and float(row["close"]) > float(row["open"]):
            return float(row["open"])
    return None


def directional_gap(features: pd.DataFrame, position: int, side: int):
    row = features.iloc[position]
    lower = row.get("bull_fvg_lower" if side > 0 else "bear_fvg_lower")
    upper = row.get("bull_fvg_upper" if side > 0 else "bear_fvg_upper")
    if pd.notna(lower) and pd.notna(upper) and float(lower) < float(upper):
        return position, float(lower), float(upper), 0.0
    age_column = "bull_fvg_age" if side > 0 else "bear_fvg_age"
    age = row.get(age_column)
    lower = row.get("last_bull_fvg_lower" if side > 0 else "last_bear_fvg_lower")
    upper = row.get("last_bull_fvg_upper" if side > 0 else "last_bear_fvg_upper")
    if pd.notna(age) and float(age) <= 8 and pd.notna(lower) and pd.notna(upper) and float(lower) < float(upper):
        return position - int(age), float(lower), float(upper), float(age)
    return None


def opposite_gap(features: pd.DataFrame, position: int, side: int):
    for index in range(position - 1, max(2, position - 20), -1):
        row = features.iloc[index]
        lower = row.get("bear_fvg_lower" if side > 0 else "bull_fvg_lower")
        upper = row.get("bear_fvg_upper" if side > 0 else "bull_fvg_upper")
        if pd.notna(lower) and pd.notna(upper) and float(lower) < float(upper):
            return index, float(lower), float(upper)
    return None


def make_candidate(
    features: pd.DataFrame,
    symbol: str,
    position: int,
    side: int,
    last_key: dict[tuple[int, str], int],
) -> EventCandidate | None:
    row = features.iloc[position]
    required = (
        "htf_atr", "htf_ema_fast", "htf_ema_slow", "htf_ema_long",
        "htf_last_swing_high", "htf_last_swing_low",
    )
    if any(pd.isna(row.get(name)) for name in required):
        return None
    htf_atr = float(row["htf_atr"])
    atr = float(row.get("atr")) if pd.notna(row.get("atr")) else math.nan
    swing_high = float(row["htf_last_swing_high"])
    swing_low = float(row["htf_last_swing_low"])
    if not np.isfinite(atr) or atr <= 0 or htf_atr <= 0 or swing_high <= swing_low:
        return None
    leg = swing_high - swing_low
    if leg / htf_atr < 1.5 or leg / htf_atr > 12.0:
        return None
    fast, slow, long_ema = float(row["htf_ema_fast"]), float(row["htf_ema_slow"]), float(row["htf_ema_long"])
    if side > 0:
        bias = fast > slow > long_ema and float(row.get("htf_htf_bull_bos_recent") or 0) > 0
        ote_lower = swing_high - 0.79 * leg
        ote_upper = swing_high - 0.62 * leg
        structural_stop = swing_low - 0.03 * htf_atr
        structural_target = swing_high
    else:
        bias = fast < slow < long_ema and float(row.get("htf_htf_bear_bos_recent") or 0) > 0
        ote_lower = swing_low + 0.62 * leg
        ote_upper = swing_low + 0.79 * leg
        structural_stop = swing_high + 0.03 * htf_atr
        structural_target = swing_low
    if not bias:
        return None
    low, high, close = float(row["low"]), float(row["high"]), float(row["close"])
    if high < ote_lower or low > ote_upper:
        return None
    origin = delivery_origin(features, position, side)
    if origin is None:
        return None
    body = float(row.get("body_atr")) if pd.notna(row.get("body_atr")) else 0.0
    if side > 0:
        confirmed = close > origin and body >= 0.45 and close > float(features.iloc[position - 1]["high"])
    else:
        confirmed = close < origin and body <= -0.45 and close < float(features.iloc[position - 1]["low"])
    if not confirmed:
        return None
    gap = directional_gap(features, position, side)
    if gap is None:
        return None
    gap_position, gap_lower, gap_upper, gap_age = gap
    overlap_lower = max(ote_lower, gap_lower)
    overlap_upper = min(ote_upper, gap_upper)
    if overlap_lower >= overlap_upper:
        return None
    variant = "CISD_FVG"
    zone_lower, zone_upper = overlap_lower, overlap_upper
    opposite = opposite_gap(features, position, side)
    opposite_age = math.nan
    if opposite is not None:
        opposite_position, opposite_lower, opposite_upper = opposite
        opposite_age = float(position - opposite_position)
        bpr_lower = max(zone_lower, opposite_lower)
        bpr_upper = min(zone_upper, opposite_upper)
        if bpr_lower < bpr_upper:
            variant = "BPR"
            zone_lower, zone_upper = bpr_lower, bpr_upper
        else:
            inverted = close > opposite_upper if side > 0 else close < opposite_lower
            if inverted and max(ote_lower, opposite_lower) < min(ote_upper, opposite_upper):
                variant = "IFVG"
                zone_lower = max(ote_lower, opposite_lower)
                zone_upper = min(ote_upper, opposite_upper)
    key = (side, variant)
    if key in last_key and position - last_key[key] < 12:
        return None
    entry = (zone_lower + zone_upper) / 2
    stop = structural_stop
    target = structural_target
    protective = side * (entry - stop)
    reward = side * (target - entry)
    if protective <= 0 or reward <= 0:
        return None
    raw_rr = reward / protective
    minimum_rr = 1.45 if variant == "BPR" else 1.65 if variant == "IFVG" else 1.85
    if raw_rr < minimum_rr:
        return None
    zone_distance = side * (close - entry) / atr
    if not -0.15 <= zone_distance <= 2.2:
        return None
    feature_row = numeric_row(row)
    feature_row.update(
        {
            "alpha_htf_ote_continuation": 1.0,
            "alpha_cisd_bpr_ifvg": 0.0,
            "variant_bpr": float(variant == "BPR"),
            "variant_ifvg": float(variant == "IFVG"),
            "variant_cisd_fvg": float(variant == "CISD_FVG"),
            "variant_code": engine.VARIANT_CODE[variant],
            "side": float(side),
            "htf_leg_atr": leg / htf_atr,
            "ote_lower": ote_lower,
            "ote_upper": ote_upper,
            "ote_position_fraction": (close - swing_low) / leg,
            "htf_ema_spread_atr": float(row.get("htf_ema_spread_atr")) if pd.notna(row.get("htf_ema_spread_atr")) else 0.0,
            "htf_fast_slope_atr": float(row.get("htf_ema_fast_slope_atr")) if pd.notna(row.get("htf_ema_fast_slope_atr")) else 0.0,
            "htf_rsi": float(row.get("htf_rsi")) if pd.notna(row.get("htf_rsi")) else 50.0,
            "htf_macd_hist_atr": float(row.get("htf_macd_hist_atr")) if pd.notna(row.get("htf_macd_hist_atr")) else 0.0,
            "fvg_age_bars": gap_age,
            "opposite_fvg_age_bars": opposite_age,
            "cisd_break_atr": side * (close - origin) / atr,
            "zone_width_atr": (zone_upper - zone_lower) / atr,
            "zone_distance_atr": zone_distance,
            "raw_reward_risk": raw_rr,
            "stop_distance_fraction": protective / max(entry, 1e-12),
            "target_distance_fraction": reward / max(entry, 1e-12),
            "symbol_btc": float(symbol == "BTCUSDT"),
            "symbol_eth": float(symbol == "ETHUSDT"),
            "decision_position": float(position),
        }
    )
    last_key[key] = position
    return EventCandidate(
        timestamp=pd.Timestamp(features.index[position]),
        symbol=symbol,
        family=OteFamily.HTF_OTE_FVG_CONTINUATION,  # type: ignore[arg-type]
        side=side,
        decision_price=close,
        entry_reference=entry,
        stop_reference=stop,
        target_reference=target,
        structural_level=swing_low if side > 0 else swing_high,
        feature_row=feature_row,
    )


def generate_candidates(frame: pd.DataFrame, symbol: str):
    five_config = FeatureConfig(
        atr_window=14,
        rsi_window=14,
        fast_ema=20,
        slow_ema=50,
        long_ema=200,
        volume_window=50,
        pivot_left=3,
        pivot_right=3,
        equal_tolerance_atr=0.12,
        displacement_body_atr=0.65,
        sweep_buffer_atr=0.02,
        retest_tolerance_atr=0.15,
    )
    hourly_config = FeatureConfig(
        atr_window=14,
        rsi_window=14,
        fast_ema=12,
        slow_ema=36,
        long_ema=120,
        volume_window=36,
        pivot_left=2,
        pivot_right=2,
        equal_tolerance_atr=0.10,
        displacement_body_atr=0.70,
        sweep_buffer_atr=0.02,
        retest_tolerance_atr=0.12,
    )
    five = build_causal_features(frame, five_config)
    five["bull_fvg_age"] = bars_since_event(five["bull_fvg_lower"])
    five["bear_fvg_age"] = bars_since_event(five["bear_fvg_lower"])
    hourly = build_causal_features(one_hour_frame(frame), hourly_config)
    features = attach_htf_context(five, hourly)
    rows: list[EventCandidate] = []
    last_key: dict[tuple[int, str], int] = {}
    for position in range(500, len(features)):
        for side in (1, -1):
            candidate = make_candidate(features, symbol, position, side, last_key)
            if candidate is not None:
                rows.append(candidate)
    rows.sort(key=lambda row: (row.timestamp, row.symbol, row.side, row.entry_reference))
    return features, rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-start", default="2022-01-01T00:00:00Z")
    parser.add_argument("--pre2024-start", default="2023-01-01T00:00:00Z")
    parser.add_argument("--official-start", default="2024-01-01T00:00:00Z")
    parser.add_argument("--official-end-exclusive", default="2024-07-01T00:00:00Z")
    args = parser.parse_args()
    engine.generate_candidates = generate_candidates
    summary = engine.run(args)
    summary["strategy_id"] = "YT_TRINITY_HTF_OTE_FVG_ACTION_VALUE_V1"
    summary["economic_hypothesis"] = "confirmed one-hour order flow reprices from a 62-79 percent OTE retracement through five-minute CISD and FVG/BPR"
    path = args.output / "RUN_SUMMARY.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "RUN_SUMMARY.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  RUN_SUMMARY.json\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
