#!/usr/bin/env python3
"""Robust runner for V3: register dynamic modules and fix causal datetime access."""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# The earlier wrappers intentionally load sibling revisions by path.  Python's
# dataclass implementation expects those modules to be present in sys.modules
# during execution, so register every module produced by module_from_spec.
_ORIGINAL_MODULE_FROM_SPEC = importlib.util.module_from_spec


def _registered_module_from_spec(spec):
    module = _ORIGINAL_MODULE_FROM_SPEC(spec)
    if spec.name:
        sys.modules[spec.name] = module
    return module


importlib.util.module_from_spec = _registered_module_from_spec
import liquidity_delivery_ml_v3 as v3  # noqa: E402
v1 = v3.v1


def enrich_base_fixed(frame: pd.DataFrame, minutes: int, streams: Mapping[str, pd.DataFrame], one_minute: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy().reset_index(drop=True)
    previous_close = out["close"].shift(1)
    tr = pd.concat([
        out["high"] - out["low"],
        (out["high"] - previous_close).abs(),
        (out["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    out["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["atr_pct"] = out["atr"] / out["close"]
    out["range"] = out["high"] - out["low"]
    out["body_signed"] = out["close"] - out["open"]
    out["body_atr"] = out["body_signed"].abs() / out["atr"]
    out["range_atr"] = out["range"] / out["atr"]
    out["lower_wick"] = out[["open", "close"]].min(axis=1) - out["low"]
    out["upper_wick"] = out["high"] - out[["open", "close"]].max(axis=1)
    out["close_location"] = (out["close"] - out["low"]) / out["range"].replace(0, np.nan)
    out["volume_z"] = v1.zscore(np.log1p(out["volume"].clip(lower=0)), 288)
    out["turnover_z"] = v1.zscore(np.log1p(out["turnover"].clip(lower=0)), 288)
    out = pd.concat([out, v1.confirmed_pivots(out, 3 if minutes == 5 else 2, 3 if minutes == 5 else 2)], axis=1)
    out["internal_high"] = out["high"].shift(1).rolling(12, min_periods=6).max()
    out["internal_low"] = out["low"].shift(1).rolling(12, min_periods=6).min()

    dt = pd.to_datetime(out["start_time_ms"], unit="ms", utc=True)
    day = dt.dt.floor("D")
    daily = out.assign(day=day).groupby("day").agg(day_high=("high", "max"), day_low=("low", "min")).shift(1)
    out["prev_day_high"] = daily["day_high"].reindex(day).to_numpy()
    out["prev_day_low"] = daily["day_low"].reindex(day).to_numpy()

    hour = dt.dt.hour.to_numpy()
    bucket = np.select([hour < 7, hour < 13, hour < 21], [0, 1, 2], default=3)
    day_no = (day.astype("int64") // (v1.DAY_MS * 1_000_000)).to_numpy()
    session_id = day_no * 4 + bucket
    sessions = out.assign(session_id=session_id).groupby("session_id").agg(high=("high", "max"), low=("low", "min")).shift(1)
    out["prev_session_high"] = sessions["high"].reindex(session_id).to_numpy()
    out["prev_session_low"] = sessions["low"].reindex(session_id).to_numpy()
    out["session_bucket"] = bucket

    minute_of_day = dt.dt.hour * 60 + dt.dt.minute
    out["hour_sin"] = np.sin(2 * np.pi * minute_of_day / 1440)
    out["hour_cos"] = np.cos(2 * np.pi * minute_of_day / 1440)
    out["dow_sin"] = np.sin(2 * np.pi * dt.dt.dayofweek / 7)
    out["dow_cos"] = np.cos(2 * np.pi * dt.dt.dayofweek / 7)

    for htf, suffix in ((v1.resample(one_minute, 60), "1h"), (v1.resample(one_minute, 240), "4h")):
        if htf.empty:
            out[f"trend_{suffix}"] = np.nan
            out[f"pd_{suffix}"] = np.nan
            continue
        htf = htf.copy()
        htf["fast"] = htf["close"].ewm(span=20, adjust=False, min_periods=20).mean()
        htf["slow"] = htf["close"].ewm(span=50, adjust=False, min_periods=50).mean()
        htf[f"trend_{suffix}"] = np.tanh((htf["fast"] - htf["slow"]) / htf["close"] * 500)
        htf["range_high"] = htf["high"].shift(1).rolling(30, min_periods=10).max()
        htf["range_low"] = htf["low"].shift(1).rolling(30, min_periods=10).min()
        htf[f"pd_{suffix}"] = (htf["close"] - htf["range_low"]) / (htf["range_high"] - htf["range_low"])
        out = pd.merge_asof(
            out.sort_values("available_at_ms"),
            htf[["available_at_ms", f"trend_{suffix}", f"pd_{suffix}"]].sort_values("available_at_ms"),
            on="available_at_ms",
            direction="backward",
        ).sort_values("start_time_ms").reset_index(drop=True)

    for name, stream in streams.items():
        if stream.empty:
            out[name] = np.nan
        else:
            out = pd.merge_asof(
                out.sort_values("available_at_ms"),
                stream.sort_values("available_at_ms"),
                on="available_at_ms",
                direction="backward",
            ).sort_values("start_time_ms").reset_index(drop=True)
    out["oi_change_z"] = v1.zscore(np.log(out["open_interest"].replace(0, np.nan)).diff(), 288) if "open_interest" in out else np.nan
    out["account_ratio_z"] = v1.zscore(out["account_ratio"], 288) if "account_ratio" in out else np.nan
    if "mark" in out and "index" in out:
        out["basis_bps"] = (out["mark"] / out["index"] - 1) * 10_000
    elif "premium" in out:
        out["basis_bps"] = out["premium"] * 10_000
    else:
        out["basis_bps"] = np.nan
    out["timeframe_min"] = minutes
    return out


def enrich_v3_fixed(frame: pd.DataFrame, minutes: int, streams: Mapping[str, pd.DataFrame], one_minute: pd.DataFrame) -> pd.DataFrame:
    out = enrich_base_fixed(frame, minutes, streams, one_minute)
    dt = pd.to_datetime(out["start_time_ms"], unit="ms", utc=True)
    day = dt.dt.floor("D")
    week = day - pd.to_timedelta(dt.dt.dayofweek, unit="D")
    weekly = out.assign(week=week).groupby("week").agg(week_high=("high", "max"), week_low=("low", "min")).shift(1)
    out["prev_week_high"] = weekly["week_high"].reindex(week).to_numpy()
    out["prev_week_low"] = weekly["week_low"].reindex(week).to_numpy()

    four_hour = (out["start_time_ms"] // (240 * v1.MINUTE_MS)).astype("int64")
    h4 = out.assign(h4=four_hour).groupby("h4").agg(h4_high=("high", "max"), h4_low=("low", "min")).shift(1)
    out["prev_4h_high"] = h4["h4_high"].reindex(four_hour).to_numpy()
    out["prev_4h_low"] = h4["h4_low"].reindex(four_hour).to_numpy()

    hour = dt.dt.hour.to_numpy()
    bucket = np.select([hour < 7, hour < 13, hour < 21], [0, 1, 2], default=3)
    day_no = (day.astype("int64") // (v1.DAY_MS * 1_000_000)).to_numpy()
    session_id = day_no * 4 + bucket
    rank = pd.Series(np.arange(len(out))).groupby(session_id).cumcount()
    opening_bars = max(1, int(math.ceil(60 / minutes)))
    first_hour = rank < opening_bars
    opening_high = out["high"].where(first_hour).groupby(session_id).transform("max")
    opening_low = out["low"].where(first_hour).groupby(session_id).transform("min")
    out["opening_range_high"] = opening_high.where(rank >= opening_bars)
    out["opening_range_low"] = opening_low.where(rank >= opening_bars)

    swing_high_event = out["last_swing_high"].where(out["new_swing_high"])
    swing_low_event = out["last_swing_low"].where(out["new_swing_low"])
    prior_high = swing_high_event.ffill().shift(1)
    prior_low = swing_low_event.ffill().shift(1)
    tolerance = out["atr"] * 0.18
    out["equal_high_level"] = ((out["last_swing_high"] + prior_high) / 2).where(
        out["new_swing_high"] & ((out["last_swing_high"] - prior_high).abs() <= tolerance)
    ).ffill()
    out["equal_low_level"] = ((out["last_swing_low"] + prior_low) / 2).where(
        out["new_swing_low"] & ((out["last_swing_low"] - prior_low).abs() <= tolerance)
    ).ffill()
    return out


v3.ORIGINAL_ENRICH = enrich_base_fixed
v3.enrich_v3 = enrich_v3_fixed
v3.v1.enrich = enrich_v3_fixed

if __name__ == "__main__":
    raise SystemExit(v3.main_v3())
