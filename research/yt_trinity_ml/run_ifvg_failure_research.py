#!/usr/bin/env python3
"""Fourth independent alpha: failed displacement -> IFVG/BPR reversal.

A prior displacement/FVG is treated as accepted delivery only until price closes
through its opposite boundary.  That inversion traps continuation inventory and
creates a structural mean-reversion path toward the displacement origin or the
next external liquidity.  No external-liquidity sweep is required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd

import run_cisd_bpr_ifvg_research as engine
from system.core import EventCandidate, FeatureConfig, build_causal_features


class FailureFamily(str, Enum):
    FAILED_DISPLACEMENT_IFVG_REVERSAL = "FAILED_DISPLACEMENT_IFVG_REVERSAL"


def numeric_row(row: pd.Series) -> dict[str, float]:
    return {
        str(key): float(value)
        for key, value in row.items()
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)
    }


def external_target(row: pd.Series, side: int, price: float, fallback: float) -> float | None:
    if side > 0:
        values = (row.get("last_swing_high"), row.get("previous_day_high"), row.get("previous_week_high"), fallback)
        valid = sorted(float(value) for value in values if pd.notna(value) and float(value) > price)
    else:
        values = (row.get("last_swing_low"), row.get("previous_day_low"), row.get("previous_week_low"), fallback)
        valid = sorted((float(value) for value in values if pd.notna(value) and float(value) < price), reverse=True)
    return valid[0] if valid else None


def original_gap(features: pd.DataFrame, position: int, bullish_original: bool):
    for index in range(position - 2, max(2, position - 16), -1):
        row = features.iloc[index]
        lower = row.get("bull_fvg_lower" if bullish_original else "bear_fvg_lower")
        upper = row.get("bull_fvg_upper" if bullish_original else "bear_fvg_upper")
        displacement = float(row.get("bull_displacement" if bullish_original else "bear_displacement") or 0.0)
        body = float(row.get("body_atr")) if pd.notna(row.get("body_atr")) else 0.0
        volume_z = float(row.get("volume_z")) if pd.notna(row.get("volume_z")) else 0.0
        body_ok = body >= 0.80 if bullish_original else body <= -0.80
        if pd.notna(lower) and pd.notna(upper) and float(lower) < float(upper) and displacement > 0 and body_ok:
            return index, float(lower), float(upper), body, volume_z
    return None


def make_candidate(
    features: pd.DataFrame,
    symbol: str,
    position: int,
    side: int,
    last_key: dict[tuple[int, str], int],
) -> EventCandidate | None:
    # side > 0 means a failed bearish delivery; side < 0 means failed bullish delivery.
    bullish_original = side < 0
    gap = original_gap(features, position, bullish_original)
    if gap is None:
        return None
    origin_position, gap_lower, gap_upper, origin_body, origin_volume_z = gap
    row = features.iloc[position]
    previous = features.iloc[position - 1]
    atr = float(row.get("atr")) if pd.notna(row.get("atr")) else math.nan
    if not np.isfinite(atr) or atr <= 0:
        return None
    close = float(row["close"])
    body = float(row.get("body_atr")) if pd.notna(row.get("body_atr")) else 0.0
    if side > 0:
        inverted = close > gap_upper and float(previous["close"]) <= gap_upper and body >= 0.50
        current_lower, current_upper = row.get("bull_fvg_lower"), row.get("bull_fvg_upper")
        post_extreme = float(features.iloc[origin_position : position + 1]["low"].min())
        pre_origin = float(features.iloc[max(0, origin_position - 8) : origin_position]["high"].max())
    else:
        inverted = close < gap_lower and float(previous["close"]) >= gap_lower and body <= -0.50
        current_lower, current_upper = row.get("bear_fvg_lower"), row.get("bear_fvg_upper")
        post_extreme = float(features.iloc[origin_position : position + 1]["high"].max())
        pre_origin = float(features.iloc[max(0, origin_position - 8) : origin_position]["low"].min())
    if not inverted:
        return None
    age = position - origin_position
    if not 2 <= age <= 15:
        return None
    extension = (
        (gap_lower - post_extreme) / atr if side > 0 else (post_extreme - gap_upper) / atr
    )
    # The failed move must have delivered enough to attract continuation inventory,
    # but extreme capitulation is excluded because the structural stop becomes too wide.
    if extension < 0.05 or extension > 3.5:
        return None

    variant = "IFVG"
    zone_lower, zone_upper = gap_lower, gap_upper
    if pd.notna(current_lower) and pd.notna(current_upper):
        current_lower, current_upper = float(current_lower), float(current_upper)
        if current_lower < current_upper:
            overlap_lower = max(gap_lower, current_lower)
            overlap_upper = min(gap_upper, current_upper)
            if overlap_lower < overlap_upper:
                variant = "BPR"
                zone_lower, zone_upper = overlap_lower, overlap_upper
            else:
                variant = "CISD_FVG"
                zone_lower, zone_upper = current_lower, current_upper
    key = (side, variant)
    if key in last_key and position - last_key[key] < 10:
        return None
    entry = (zone_lower + zone_upper) / 2
    buffer = 0.05 * atr
    stop = post_extreme - buffer if side > 0 else post_extreme + buffer
    target = external_target(row, side, close, pre_origin)
    if target is None:
        return None
    protective = side * (entry - stop)
    reward = side * (target - entry)
    if protective <= 0 or reward <= 0:
        return None
    raw_rr = reward / protective
    minimum_rr = 1.30 if variant == "BPR" else 1.50 if variant == "IFVG" else 1.75
    if raw_rr < minimum_rr:
        return None
    zone_distance = side * (close - entry) / atr
    if not -0.10 <= zone_distance <= 2.2:
        return None
    rsi_now = float(row.get("rsi")) if pd.notna(row.get("rsi")) else 50.0
    rsi_origin = float(features.iloc[origin_position].get("rsi")) if pd.notna(features.iloc[origin_position].get("rsi")) else 50.0
    macd_now = float(row.get("macd_hist_atr")) if pd.notna(row.get("macd_hist_atr")) else 0.0
    macd_origin = float(features.iloc[origin_position].get("macd_hist_atr")) if pd.notna(features.iloc[origin_position].get("macd_hist_atr")) else 0.0
    feature_row = numeric_row(row)
    feature_row.update(
        {
            "alpha_failed_displacement_ifvg": 1.0,
            "alpha_cisd_bpr_ifvg": 0.0,
            "variant_bpr": float(variant == "BPR"),
            "variant_ifvg": float(variant == "IFVG"),
            "variant_cisd_fvg": float(variant == "CISD_FVG"),
            "variant_code": engine.VARIANT_CODE[variant],
            "side": float(side),
            "failed_delivery_age_bars": float(age),
            "original_displacement_body_atr": origin_body,
            "original_displacement_volume_z": origin_volume_z,
            "failed_extension_atr": extension,
            "inversion_body_atr": body,
            "rsi_change_from_delivery": rsi_now - rsi_origin,
            "macd_hist_change_from_delivery": macd_now - macd_origin,
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
        family=FailureFamily.FAILED_DISPLACEMENT_IFVG_REVERSAL,  # type: ignore[arg-type]
        side=side,
        decision_price=close,
        entry_reference=entry,
        stop_reference=stop,
        target_reference=target,
        structural_level=gap_lower if side > 0 else gap_upper,
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
        displacement_body_atr=0.75,
        sweep_buffer_atr=0.02,
        retest_tolerance_atr=0.15,
    )
    features = build_causal_features(frame, config)
    rows: list[EventCandidate] = []
    last_key: dict[tuple[int, str], int] = {}
    for position in range(205, len(features)):
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
    summary["strategy_id"] = "YT_TRINITY_FAILED_DISPLACEMENT_IFVG_ACTION_VALUE_V1"
    summary["economic_hypothesis"] = "failed displacement delivery traps continuation inventory; IFVG/BPR retest reprices toward origin or external liquidity"
    summary["parent_routes"] = [
        "YT_TRINITY_CISD_BPR_IFVG_ACTION_VALUE_V1",
        "YT_TRINITY_COMPRESSION_BPR_CONTINUATION_ACTION_VALUE_V1",
        "YT_TRINITY_SMT_CISD_BPR_ACTION_VALUE_V1",
        "YT_TRINITY_PRE2024_POSITIVE_FAMILY_POOL_V1",
    ]
    path = args.output / "RUN_SUMMARY.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.output / "RUN_SUMMARY.sha256").write_text(f"{digest}  RUN_SUMMARY.json\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
