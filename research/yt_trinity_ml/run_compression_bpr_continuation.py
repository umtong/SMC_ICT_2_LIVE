#!/usr/bin/env python3
"""Conditional second alpha: compression -> displacement -> BPR/IFVG continuation.

This module reuses the same causal data, action-value ML, cost, risk, global-slot
and NAV machinery as the first screen while replacing the economic event
constructor.  It is intended to run only after the CISD-reversal route records a
pre-2024 economic failure.
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


class CompressionFamily(str, Enum):
    COMPRESSION_BPR_CONTINUATION = "COMPRESSION_BPR_CONTINUATION"


def numeric_row(row: pd.Series) -> dict[str, float]:
    return {
        str(key): float(value)
        for key, value in row.items()
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)
    }


def opposite_fvg(features: pd.DataFrame, position: int, long_side: bool) -> tuple[int, float, float] | None:
    for index in range(position - 1, max(2, position - 24), -1):
        row = features.iloc[index]
        lower = row.get("bear_fvg_lower" if long_side else "bull_fvg_lower")
        upper = row.get("bear_fvg_upper" if long_side else "bull_fvg_upper")
        if pd.notna(lower) and pd.notna(upper) and float(lower) < float(upper):
            return index, float(lower), float(upper)
    return None


def target_level(row: pd.Series, side: int, price: float) -> float | None:
    if side > 0:
        values = (row.get("last_swing_high"), row.get("previous_day_high"), row.get("previous_week_high"))
        valid = sorted(float(value) for value in values if pd.notna(value) and float(value) > price)
    else:
        values = (row.get("last_swing_low"), row.get("previous_day_low"), row.get("previous_week_low"))
        valid = sorted((float(value) for value in values if pd.notna(value) and float(value) < price), reverse=True)
    return valid[0] if valid else None


def make_candidate(
    features: pd.DataFrame,
    symbol: str,
    position: int,
    side: int,
    bandwidth_quantile: pd.Series,
    last_entry: dict[tuple[int, str], int],
) -> EventCandidate | None:
    row = features.iloc[position]
    atr = float(row.get("atr")) if pd.notna(row.get("atr")) else math.nan
    if not np.isfinite(atr) or atr <= 0:
        return None
    pre = features.iloc[position - 12 : position]
    if len(pre) < 12:
        return None
    bandwidth = pre["bollinger_bandwidth"].dropna()
    threshold = bandwidth_quantile.iloc[position - 1]
    if bandwidth.empty or pd.isna(threshold):
        return None
    compression_bandwidth = float(bandwidth.iloc[-6:].median())
    if compression_bandwidth > float(threshold):
        return None
    range_high = float(pre["high"].max())
    range_low = float(pre["low"].min())
    range_width = range_high - range_low
    if range_width <= 0 or range_width / atr > 4.5:
        return None
    close = float(row["close"])
    body_atr = float(row.get("body_atr")) if pd.notna(row.get("body_atr")) else 0.0
    fast = float(row.get("ema_fast")) if pd.notna(row.get("ema_fast")) else math.nan
    slow = float(row.get("ema_slow")) if pd.notna(row.get("ema_slow")) else math.nan
    long_ema = float(row.get("ema_long")) if pd.notna(row.get("ema_long")) else math.nan
    if not all(np.isfinite(value) for value in (fast, slow, long_ema)):
        return None
    if side > 0:
        trend_ok = fast > slow > long_ema and float(row.get("ema_fast_slope_atr") or 0) > 0
        breakout_ok = close > range_high and body_atr >= 0.75 and float(row.get("bull_displacement") or 0) > 0
        current_lower, current_upper = row.get("bull_fvg_lower"), row.get("bull_fvg_upper")
    else:
        trend_ok = fast < slow < long_ema and float(row.get("ema_fast_slope_atr") or 0) < 0
        breakout_ok = close < range_low and body_atr <= -0.75 and float(row.get("bear_displacement") or 0) > 0
        current_lower, current_upper = row.get("bear_fvg_lower"), row.get("bear_fvg_upper")
    if not trend_ok or not breakout_ok or pd.isna(current_lower) or pd.isna(current_upper):
        return None
    current_lower, current_upper = float(current_lower), float(current_upper)
    if current_lower >= current_upper:
        return None

    variant = "CISD_FVG"
    zone_lower, zone_upper = current_lower, current_upper
    opposite = opposite_fvg(features, position, side > 0)
    opposite_age = math.nan
    if opposite is not None:
        opposite_position, opposite_lower, opposite_upper = opposite
        opposite_age = float(position - opposite_position)
        overlap_lower = max(current_lower, opposite_lower)
        overlap_upper = min(current_upper, opposite_upper)
        if overlap_lower < overlap_upper:
            variant = "BPR"
            zone_lower, zone_upper = overlap_lower, overlap_upper
        else:
            inverted = close > opposite_upper if side > 0 else close < opposite_lower
            if inverted:
                variant = "IFVG"
                zone_lower, zone_upper = opposite_lower, opposite_upper
    if (side, variant) in last_entry and position - last_entry[(side, variant)] < 12:
        return None
    entry = (zone_lower + zone_upper) / 2
    stop = range_low - 0.05 * atr if side > 0 else range_high + 0.05 * atr
    target = target_level(row, side, close)
    if target is None:
        return None
    protective = side * (entry - stop)
    reward = side * (target - entry)
    if protective <= 0 or reward <= 0:
        return None
    raw_rr = reward / protective
    required_rr = 1.35 if variant == "BPR" else 1.55 if variant == "IFVG" else 1.85
    if raw_rr < required_rr:
        return None
    zone_distance = side * (close - entry) / atr
    if not -0.10 <= zone_distance <= 2.8:
        return None

    feature_row = numeric_row(row)
    feature_row.update(
        {
            "alpha_compression_bpr_continuation": 1.0,
            "alpha_cisd_bpr_ifvg": 0.0,
            "variant_bpr": float(variant == "BPR"),
            "variant_ifvg": float(variant == "IFVG"),
            "variant_cisd_fvg": float(variant == "CISD_FVG"),
            "variant_code": engine.VARIANT_CODE[variant],
            "side": float(side),
            "compression_bandwidth": compression_bandwidth,
            "compression_bandwidth_threshold": float(threshold),
            "compression_width_atr": range_width / atr,
            "breakout_distance_atr": side * (close - (range_high if side > 0 else range_low)) / atr,
            "zone_width_atr": (zone_upper - zone_lower) / atr,
            "zone_distance_atr": zone_distance,
            "opposite_fvg_age_bars": opposite_age,
            "raw_reward_risk": raw_rr,
            "stop_distance_fraction": protective / max(entry, 1e-12),
            "target_distance_fraction": reward / max(entry, 1e-12),
            "symbol_btc": float(symbol == "BTCUSDT"),
            "symbol_eth": float(symbol == "ETHUSDT"),
            "decision_position": float(position),
        }
    )
    last_entry[(side, variant)] = position
    return EventCandidate(
        timestamp=pd.Timestamp(features.index[position]),
        symbol=symbol,
        family=CompressionFamily.COMPRESSION_BPR_CONTINUATION,  # type: ignore[arg-type]
        side=side,
        decision_price=close,
        entry_reference=entry,
        stop_reference=stop,
        target_reference=target,
        structural_level=range_high if side > 0 else range_low,
        feature_row=feature_row,
    )


def generate_candidates(frame: pd.DataFrame, symbol: str):
    config = FeatureConfig(
        atr_window=14,
        rsi_window=14,
        fast_ema=20,
        slow_ema=50,
        long_ema=200,
        volume_window=50,
        pivot_left=3,
        pivot_right=3,
        equal_tolerance_atr=0.12,
        displacement_body_atr=0.70,
        sweep_buffer_atr=0.025,
        retest_tolerance_atr=0.15,
    )
    features = build_causal_features(frame, config)
    bandwidth_quantile = features["bollinger_bandwidth"].shift(1).rolling(288, min_periods=144).quantile(0.22)
    rows: list[EventCandidate] = []
    last_entry: dict[tuple[int, str], int] = {}
    for position in range(300, len(features)):
        for side in (1, -1):
            candidate = make_candidate(features, symbol, position, side, bandwidth_quantile, last_entry)
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
    summary["strategy_id"] = "YT_TRINITY_COMPRESSION_BPR_CONTINUATION_ACTION_VALUE_V1"
    summary["economic_hypothesis"] = "low-volatility compression followed by trend-aligned displacement acceptance and BPR/IFVG continuation repricing"
    summary["parent_failed_route"] = "YT_TRINITY_CISD_BPR_IFVG_ACTION_VALUE_V1"
    path = args.output / "RUN_SUMMARY.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.output / "RUN_SUMMARY.sha256").write_text(f"{digest}  RUN_SUMMARY.json\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
