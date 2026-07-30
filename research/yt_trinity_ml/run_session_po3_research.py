#!/usr/bin/env python3
"""Sixth alpha: Asia accumulation -> killzone manipulation -> distribution.

The Asia range is complete before any decision.  During the London or New York
local killzone, price must raid one side, close back through it, then confirm a
CISD/displacement and produce a causal FVG/BPR/IFVG.  The structural target is
the opposing Asia-range liquidity or a nearer confirmed external pool.  Time
only governs entry eligibility; positions never close because a session ended.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import run_cisd_bpr_ifvg_research as engine
import run_htf_ote_continuation as htf
from system.core import EventCandidate, FeatureConfig, build_causal_features


class Po3Family(str, Enum):
    SESSION_PO3_MANIPULATION_DISTRIBUTION = "SESSION_PO3_MANIPULATION_DISTRIBUTION"


@dataclass(frozen=True)
class Manipulation:
    position: int
    side: int
    session: str
    sweep_level: float
    sweep_extreme: float
    asia_high: float
    asia_low: float
    asia_mid: float
    daily_open: float
    sweep_depth_atr: float
    session_minutes: float


def numeric_row(row: pd.Series) -> dict[str, float]:
    return {
        str(key): float(value)
        for key, value in row.items()
        if isinstance(value, (int, float, np.integer, np.floating))
        and np.isfinite(value)
    }


def session_context(features: pd.DataFrame) -> pd.DataFrame:
    output = features.copy()
    basis = pd.DatetimeIndex(
        pd.to_datetime(output["bar_start"], utc=True)
        if "bar_start" in output.columns
        else output.index
    )
    utc_day = basis.floor("D")
    minutes_utc = basis.hour * 60 + basis.minute
    asia = (minutes_utc >= 0) & (minutes_utc < 5 * 60)
    asia_high_source = output["high"].where(asia)
    asia_low_source = output["low"].where(asia)
    asia_high = asia_high_source.groupby(utc_day).transform("max")
    asia_low = asia_low_source.groupby(utc_day).transform("min")
    asia_count = pd.Series(asia.astype(int), index=output.index).groupby(utc_day).transform("sum")
    complete = (minutes_utc >= 5 * 60) & (asia_count >= 55)
    output["asia_high"] = asia_high.where(complete)
    output["asia_low"] = asia_low.where(complete)
    output["asia_mid"] = ((asia_high + asia_low) / 2).where(complete)
    daily_open = output["open"].where(minutes_utc == 0).groupby(utc_day).transform("first")
    output["daily_open"] = daily_open

    london = basis.tz_convert(ZoneInfo("Europe/London"))
    new_york = basis.tz_convert(ZoneInfo("America/New_York"))
    london_minutes = london.hour * 60 + london.minute
    ny_minutes = new_york.hour * 60 + new_york.minute
    output["session_london"] = ((london_minutes >= 7 * 60) & (london_minutes < 10 * 60)).astype(float)
    output["session_new_york"] = ((ny_minutes >= 7 * 60) & (ny_minutes < 10 * 60)).astype(float)
    output["session_minutes"] = np.where(
        output["session_london"] > 0,
        london_minutes - 7 * 60,
        np.where(output["session_new_york"] > 0, ny_minutes - 7 * 60, np.nan),
    )
    output["utc_day_code"] = pd.factorize(utc_day)[0].astype(float)
    return output


def attach_hourly(five: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
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
    hourly = build_causal_features(htf.one_hour_frame(source), hourly_config)
    selected = [
        "atr",
        "ema_fast_slope_atr",
        "ema_slow_slope_atr",
        "ema_spread_atr",
        "bull_bos",
        "bear_bos",
        "rsi",
        "macd_hist_atr",
        "distance_vwap_atr",
        "volume_z",
    ]
    right = hourly[selected].rename(columns={name: f"htf_{name}" for name in selected})
    left = five.reset_index().rename(columns={five.index.name or "index": "decision_time"})
    right_frame = right.reset_index().rename(columns={right.index.name or "index": "htf_available_at"})
    merged = pd.merge_asof(
        left.sort_values("decision_time"),
        right_frame.sort_values("htf_available_at"),
        left_on="decision_time",
        right_on="htf_available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    merged.index = pd.DatetimeIndex(merged["decision_time"])
    merged.index.name = source.index.name
    return merged.drop(columns=["decision_time"])


def delivery_origin(features: pd.DataFrame, position: int, side: int) -> float | None:
    for index in range(position, max(-1, position - 8), -1):
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
        return position, float(lower), float(upper)
    for index in range(position - 1, max(2, position - 8), -1):
        row = features.iloc[index]
        lower = row.get("bull_fvg_lower" if side > 0 else "bear_fvg_lower")
        upper = row.get("bull_fvg_upper" if side > 0 else "bear_fvg_upper")
        if pd.notna(lower) and pd.notna(upper) and float(lower) < float(upper):
            return index, float(lower), float(upper)
    return None


def opposite_gap(features: pd.DataFrame, position: int, side: int):
    for index in range(position - 1, max(2, position - 20), -1):
        row = features.iloc[index]
        lower = row.get("bear_fvg_lower" if side > 0 else "bull_fvg_lower")
        upper = row.get("bear_fvg_upper" if side > 0 else "bull_fvg_upper")
        if pd.notna(lower) and pd.notna(upper) and float(lower) < float(upper):
            return index, float(lower), float(upper)
    return None


def manipulation(features: pd.DataFrame, position: int, side: int) -> Manipulation | None:
    row = features.iloc[position]
    if not (float(row.get("session_london") or 0) > 0 or float(row.get("session_new_york") or 0) > 0):
        return None
    required = ("asia_high", "asia_low", "asia_mid", "daily_open", "atr")
    if any(pd.isna(row.get(name)) for name in required):
        return None
    atr = float(row["atr"])
    if atr <= 0:
        return None
    asia_high = float(row["asia_high"])
    asia_low = float(row["asia_low"])
    asia_mid = float(row["asia_mid"])
    daily_open = float(row["daily_open"])
    if asia_high <= asia_low or (asia_high - asia_low) / atr > 7.0:
        return None
    buffer = 0.02 * atr
    if side > 0:
        level = asia_low
        extreme = float(row["low"])
        swept = extreme < level - buffer and float(row["close"]) > level
        depth = (level - extreme) / atr
    else:
        level = asia_high
        extreme = float(row["high"])
        swept = extreme > level + buffer and float(row["close"]) < level
        depth = (extreme - level) / atr
    if not swept or depth < 0.03 or depth > 2.5:
        return None
    session = "LONDON" if float(row.get("session_london") or 0) > 0 else "NEW_YORK"
    return Manipulation(
        position=position,
        side=side,
        session=session,
        sweep_level=level,
        sweep_extreme=extreme,
        asia_high=asia_high,
        asia_low=asia_low,
        asia_mid=asia_mid,
        daily_open=daily_open,
        sweep_depth_atr=depth,
        session_minutes=float(row.get("session_minutes") or 0.0),
    )


def target_for(row: pd.Series, event: Manipulation, entry: float) -> float | None:
    if event.side > 0:
        values = [
            event.asia_high,
            row.get("last_swing_high"),
            row.get("previous_day_high"),
            row.get("previous_week_high"),
        ]
        valid = sorted(float(value) for value in values if pd.notna(value) and float(value) > entry)
    else:
        values = [
            event.asia_low,
            row.get("last_swing_low"),
            row.get("previous_day_low"),
            row.get("previous_week_low"),
        ]
        valid = sorted((float(value) for value in values if pd.notna(value) and float(value) < entry), reverse=True)
    return valid[0] if valid else None


def confirmed_candidate(
    features: pd.DataFrame,
    symbol: str,
    position: int,
    event: Manipulation,
    last_key: dict[tuple[int, str, str], int],
) -> EventCandidate | None:
    row = features.iloc[position]
    atr = float(row.get("atr")) if pd.notna(row.get("atr")) else math.nan
    if not np.isfinite(atr) or atr <= 0:
        return None
    origin = delivery_origin(features, event.position, event.side)
    if origin is None:
        return None
    close = float(row["close"])
    body = float(row.get("body_atr")) if pd.notna(row.get("body_atr")) else 0.0
    if event.side > 0:
        confirmed = close > origin and body >= 0.45 and close > float(features.iloc[position - 1]["high"])
    else:
        confirmed = close < origin and body <= -0.45 and close < float(features.iloc[position - 1]["low"])
    if not confirmed:
        return None
    gap = directional_gap(features, position, event.side)
    if gap is None:
        return None
    gap_position, zone_lower, zone_upper = gap
    variant = "CISD_FVG"
    opposite = opposite_gap(features, position, event.side)
    opposite_age = math.nan
    if opposite is not None:
        opposite_position, opposite_lower, opposite_upper = opposite
        opposite_age = float(position - opposite_position)
        overlap_lower = max(zone_lower, opposite_lower)
        overlap_upper = min(zone_upper, opposite_upper)
        if overlap_lower < overlap_upper:
            variant = "BPR"
            zone_lower, zone_upper = overlap_lower, overlap_upper
        else:
            inverted = close > opposite_upper if event.side > 0 else close < opposite_lower
            if inverted:
                variant = "IFVG"
                zone_lower, zone_upper = opposite_lower, opposite_upper
    key = (event.side, event.session, variant)
    if key in last_key and position - last_key[key] < 12:
        return None
    entry = (zone_lower + zone_upper) / 2
    stop = event.sweep_extreme - 0.04 * atr if event.side > 0 else event.sweep_extreme + 0.04 * atr
    target = target_for(row, event, entry)
    if target is None:
        return None
    protective = event.side * (entry - stop)
    reward = event.side * (target - entry)
    if protective <= 0 or reward <= 0:
        return None
    raw_rr = reward / protective
    minimum_rr = 1.40 if variant == "BPR" else 1.60 if variant == "IFVG" else 1.85
    if raw_rr < minimum_rr:
        return None
    zone_distance = event.side * (close - entry) / atr
    if not -0.15 <= zone_distance <= 2.2:
        return None
    feature_row = numeric_row(row)
    for absolute in (
        "asia_high",
        "asia_low",
        "asia_mid",
        "daily_open",
        "utc_day_code",
    ):
        feature_row.pop(absolute, None)
    feature_row.update(
        {
            "alpha_session_po3": 1.0,
            "alpha_cisd_bpr_ifvg": 0.0,
            "variant_bpr": float(variant == "BPR"),
            "variant_ifvg": float(variant == "IFVG"),
            "variant_cisd_fvg": float(variant == "CISD_FVG"),
            "variant_code": engine.VARIANT_CODE[variant],
            "side": float(event.side),
            "session_london": float(event.session == "LONDON"),
            "session_new_york": float(event.session == "NEW_YORK"),
            "session_minutes_at_sweep": event.session_minutes,
            "confirmation_delay_bars": float(position - event.position),
            "asia_range_atr": (event.asia_high - event.asia_low) / atr,
            "sweep_depth_atr": event.sweep_depth_atr,
            "daily_open_distance_atr": event.side * (close - event.daily_open) / atr,
            "asia_mid_distance_atr": event.side * (close - event.asia_mid) / atr,
            "cisd_break_atr": event.side * (close - origin) / atr,
            "fvg_age_bars": float(position - gap_position),
            "opposite_fvg_age_bars": opposite_age,
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
        family=Po3Family.SESSION_PO3_MANIPULATION_DISTRIBUTION,  # type: ignore[arg-type]
        side=event.side,
        decision_price=close,
        entry_reference=entry,
        stop_reference=stop,
        target_reference=target,
        structural_level=event.sweep_level,
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
        displacement_body_atr=0.65,
        sweep_buffer_atr=0.02,
        retest_tolerance_atr=0.15,
    )
    five = build_causal_features(frame, config)
    five = session_context(five)
    features = attach_hourly(five, frame)
    pending: list[Manipulation] = []
    rows: list[EventCandidate] = []
    last_key: dict[tuple[int, str, str], int] = {}
    last_manipulation: dict[tuple[int, str, float], int] = {}
    for position in range(500, len(features)):
        for side in (1, -1):
            event = manipulation(features, position, side)
            if event is not None:
                identity = (side, event.session, float(features.iloc[position].get("utc_day_code") or -1))
                if identity not in last_manipulation:
                    last_manipulation[identity] = position
                    pending.append(event)
        next_pending: list[Manipulation] = []
        for event in pending:
            age = position - event.position
            if age < 1:
                next_pending.append(event)
                continue
            if age > 6:
                continue
            candidate = confirmed_candidate(features, symbol, position, event, last_key)
            if candidate is not None:
                rows.append(candidate)
            else:
                next_pending.append(event)
        pending = next_pending
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
    summary["strategy_id"] = "YT_TRINITY_SESSION_PO3_ACTION_VALUE_V1"
    summary["economic_hypothesis"] = "completed Asia accumulation is manipulated during local London/New York killzones; CISD and FVG/BPR distribute toward opposing session liquidity"
    path = args.output / "RUN_SUMMARY.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "RUN_SUMMARY.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  RUN_SUMMARY.json\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
