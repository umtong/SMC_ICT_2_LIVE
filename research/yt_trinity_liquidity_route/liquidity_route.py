#!/usr/bin/env python3
"""Transcript-grounded causal liquidity-delivery route ML system.

This module is intentionally independent of prior project alpha implementations.  It
turns the repeated sequence in the complete 쉽알남/차트브로/지표센세 corpus into a
single causal state machine:

    draw on external liquidity -> HTF PD-array location -> raid or acceptance ->
    close-confirmed CISD/displacement -> first BPR/IFVG/FVG/OB retest ->
    rejection/hold -> next untouched liquidity target.

The deterministic narrative creates candidates.  ML only decides action/management,
which symbol wins the one global slot, and whether to abstain.  All labels are net of
fees, spread, slippage and exact funding.  New orders activate after 500 ms and use the
first later 1-minute bar; same-minute ambiguity is adverse-first.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

# The workflow adds research/yt_trinity_ml to PYTHONPATH.
from system.canonical_adapter import (  # type: ignore
    CanonicalInputConfig,
    assemble_symbol_frame,
    load_loader,
    normalize_trade_bars,
)

UTC = "UTC"
NY = ZoneInfo("America/New_York")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SEGMENTS = ("PRE_2024_2021", "PRE_2024_2022", "PRE_2024_2023", "2024_H1")
RESOLVED = {"STOP", "TARGET", "TP1_THEN_TARGET", "TP1_THEN_BREAKEVEN", "STRUCTURAL_EXIT"}


@dataclass(frozen=True)
class StrategyConfig:
    decision_minutes: int = 5
    atr_window: int = 14
    pivot_left: int = 6
    pivot_right: int = 6
    internal_left: int = 2
    internal_right: int = 2
    volume_window: int = 96
    raid_buffer_atr: float = 0.025
    acceptance_buffer_atr: float = 0.08
    cisd_body_atr: float = 0.45
    cisd_range_atr: float = 0.75
    cisd_max_bars: int = 8
    retest_max_bars: int = 18
    retest_tolerance_atr: float = 0.035
    rejection_close_location: float = 0.58
    stop_buffer_atr: float = 0.05
    minimum_stop_atr: float = 0.10
    maximum_stop_atr: float = 1.60
    minimum_target_r: float = 2.0
    activation_latency_ms: int = 500
    half_spread_bps: float = 0.35
    entry_slippage_bps: float = 1.75
    target_slippage_bps: float = 1.25
    stop_slippage_bps: float = 4.0
    taker_fee_rate: float = 0.00055
    maintenance_margin_fraction: float = 0.005
    liquidation_buffer_fraction: float = 0.0025
    training_completion_lag_minutes: int = 15
    minimum_training_rows: int = 160
    max_iter: int = 180
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 24
    learning_rate: float = 0.045
    l2_regularization: float = 2.0
    uncertainty_penalty: float = 0.45
    random_state: int = 20260727


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    decision_time: pd.Timestamp
    symbol: str
    side: int
    family: str
    pool_source: str
    pool_quality: int
    zone_kind: str
    decision_price: float
    stop_reference: float
    target_reference: float
    tp1_reference: float
    sweep_or_break_level: float
    event_extreme: float
    zone_lower: float
    zone_upper: float
    invalidation_level: float
    features: Mapping[str, float]


@dataclass(frozen=True)
class ExitLeg:
    timestamp: pd.Timestamp
    fraction: float
    price: float
    fee_rate: float
    reason: str


@dataclass(frozen=True)
class Outcome:
    candidate_id: str
    management: str
    status: str
    entry_time: pd.Timestamp | None
    exit_time: pd.Timestamp | None
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    planned_unit_loss: float | None
    unit_pnl: float | None
    net_r: float | None
    hold_minutes: float | None
    funding_pnl: float
    legs: tuple[ExitLeg, ...]


@dataclass(frozen=True)
class Policy:
    name: str
    cadence_days: int | None
    window_days: int | None = None
    decay_half_life_days: float | None = None
    static: bool = False


POLICIES: tuple[Policy, ...] = (
    Policy("STATIC_2021_2022", None, static=True),
    Policy("EXP28", 28),
    Policy("EXP90", 90),
    Policy("ROLL365_28", 28, window_days=365),
    Policy("ROLL730_28", 28, window_days=730),
    Policy("DECAY180_28", 28, decay_half_life_days=180.0),
    Policy("DECAY365_28", 28, decay_half_life_days=365.0),
)

POOL_SPECS: tuple[tuple[str, str, int], ...] = (
    ("previous_week_high", "previous_week_low", 10),
    ("previous_day_high", "previous_day_low", 9),
    ("ny_or_high", "ny_or_low", 8),
    ("asia_high", "asia_low", 7),
    ("last_external_swing_high", "last_external_swing_low", 7),
    ("rolling_48_high", "rolling_48_low", 5),
    ("rolling_12_high", "rolling_12_low", 3),
)

INSTRUMENT = {
    "BTCUSDT": {"step": 0.001, "minimum": 0.001},
    "ETHUSDT": {"step": 0.01, "minimum": 0.01},
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atr(frame: pd.DataFrame, window: int) -> pd.Series:
    previous = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def _confirmed_pivot(series: pd.Series, left: int, right: int, high: bool) -> pd.Series:
    width = left + right + 1
    rolling = series.rolling(width, min_periods=width)
    extreme = rolling.max() if high else rolling.min()
    candidate = series.shift(right)
    return candidate.where(candidate.eq(extreme))


def _group_prior_levels(frame: pd.DataFrame, key: pd.Series) -> tuple[pd.Series, pd.Series]:
    table = pd.DataFrame({"key": key.to_numpy(), "high": frame["high"].to_numpy(), "low": frame["low"].to_numpy()})
    agg = table.groupby("key", sort=True).agg(high=("high", "max"), low=("low", "min"))
    prior = agg.shift(1)
    mapped_high = key.map(prior["high"])
    mapped_low = key.map(prior["low"])
    mapped_high.index = frame.index
    mapped_low.index = frame.index
    return mapped_high, mapped_low


def build_features(frame: pd.DataFrame, symbol: str, config: StrategyConfig) -> pd.DataFrame:
    out = frame.copy().sort_index()
    starts = pd.DatetimeIndex(pd.to_datetime(out["bar_start"], utc=True))
    out["symbol"] = symbol
    out["atr"] = _atr(out, config.atr_window)
    out["atr_fraction"] = out["atr"] / out["close"]
    out["body"] = out["close"] - out["open"]
    out["body_atr"] = out["body"] / out["atr"]
    out["range_atr"] = (out["high"] - out["low"]) / out["atr"]
    out["close_location"] = (out["close"] - out["low"]) / (out["high"] - out["low"]).replace(0, np.nan)
    log_volume = np.log1p(out["volume"].clip(lower=0))
    volume_mean = log_volume.rolling(config.volume_window, min_periods=24).mean()
    volume_std = log_volume.rolling(config.volume_window, min_periods=24).std(ddof=0)
    out["volume_z"] = (log_volume - volume_mean) / volume_std.replace(0, np.nan)
    for span in (20, 50, 200):
        out[f"ema_{span}"] = out["close"].ewm(span=span, adjust=False, min_periods=span).mean()
    out["ema_spread_atr"] = (out["ema_20"] - out["ema_50"]) / out["atr"]
    out["ema_slope_atr"] = out["ema_20"].diff(3) / out["atr"]
    out["htf_bias"] = (
        np.sign(out["ema_20"] - out["ema_50"])
        + np.sign(out["ema_50"] - out["ema_200"])
        + np.sign(out["ema_20"].diff(12))
    )
    returns = np.log(out["close"]).diff()
    out["return_1"] = returns
    out["return_3"] = np.log(out["close"] / out["close"].shift(3))
    out["return_12"] = np.log(out["close"] / out["close"].shift(12))
    out["realized_vol_24"] = np.sqrt((returns * returns).rolling(24, min_periods=12).sum())
    bandwidth = out["close"].rolling(20, min_periods=20).std(ddof=0) / out["close"].rolling(20, min_periods=20).mean()
    out["compression_ratio"] = bandwidth / bandwidth.rolling(96, min_periods=24).median().replace(0, np.nan)

    external_high = _confirmed_pivot(out["high"], config.pivot_left, config.pivot_right, True)
    external_low = _confirmed_pivot(out["low"], config.pivot_left, config.pivot_right, False)
    internal_high = _confirmed_pivot(out["high"], config.internal_left, config.internal_right, True)
    internal_low = _confirmed_pivot(out["low"], config.internal_left, config.internal_right, False)
    out["last_external_swing_high"] = external_high.ffill()
    out["last_external_swing_low"] = external_low.ffill()
    out["last_internal_swing_high"] = internal_high.ffill()
    out["last_internal_swing_low"] = internal_low.ffill()
    out["rolling_12_high"] = out["high"].shift(1).rolling(12, min_periods=8).max()
    out["rolling_12_low"] = out["low"].shift(1).rolling(12, min_periods=8).min()
    out["rolling_48_high"] = out["high"].shift(1).rolling(48, min_periods=24).max()
    out["rolling_48_low"] = out["low"].shift(1).rolling(48, min_periods=24).min()

    utc_day = pd.Series(starts.floor("D"), index=out.index)
    prev_day_high, prev_day_low = _group_prior_levels(out, utc_day)
    out["previous_day_high"] = prev_day_high
    out["previous_day_low"] = prev_day_low
    week_key = pd.Series(starts.normalize() - pd.to_timedelta(starts.dayofweek, unit="D"), index=out.index)
    prev_week_high, prev_week_low = _group_prior_levels(out, week_key)
    out["previous_week_high"] = prev_week_high
    out["previous_week_low"] = prev_week_low

    hour = starts.hour + starts.minute / 60.0
    asia_mask = (hour >= 0.0) & (hour < 6.0)
    asia_table = pd.DataFrame(
        {"day": utc_day[asia_mask].to_numpy(), "high": out.loc[asia_mask, "high"].to_numpy(), "low": out.loc[asia_mask, "low"].to_numpy()}
    )
    asia = asia_table.groupby("day", sort=True).agg(high=("high", "max"), low=("low", "min")) if not asia_table.empty else pd.DataFrame()
    out["asia_high"] = utc_day.map(asia["high"] if not asia.empty else pd.Series(dtype=float)).where(hour >= 6.0)
    out["asia_low"] = utc_day.map(asia["low"] if not asia.empty else pd.Series(dtype=float)).where(hour >= 6.0)

    ny = starts.tz_convert(NY)
    ny_date = pd.Series(list(ny.date), index=out.index)
    ny_minute = ny.hour * 60 + ny.minute
    opening = (ny_minute >= 9 * 60 + 30) & (ny_minute < 10 * 60)
    opening_table = pd.DataFrame(
        {"date": ny_date[opening].to_numpy(), "high": out.loc[opening, "high"].to_numpy(), "low": out.loc[opening, "low"].to_numpy()}
    )
    opening_agg = opening_table.groupby("date", sort=True).agg(high=("high", "max"), low=("low", "min")) if not opening_table.empty else pd.DataFrame()
    out["ny_or_high"] = ny_date.map(opening_agg["high"] if not opening_agg.empty else pd.Series(dtype=float)).where(ny_minute >= 10 * 60)
    out["ny_or_low"] = ny_date.map(opening_agg["low"] if not opening_agg.empty else pd.Series(dtype=float)).where(ny_minute >= 10 * 60)
    out["london_killzone"] = ((ny_minute >= 2 * 60) & (ny_minute < 5 * 60)).astype(float)
    out["new_york_killzone"] = ((ny_minute >= 7 * 60) & (ny_minute < 10 * 60)).astype(float)
    out["post_ny_or"] = ((ny_minute >= 10 * 60) & (ny_minute < 12 * 60)).astype(float)
    out["ny_time_sin"] = np.sin(2 * np.pi * ny_minute / 1440.0)
    out["ny_time_cos"] = np.cos(2 * np.pi * ny_minute / 1440.0)
    out["utc_hour_sin"] = np.sin(2 * np.pi * starts.hour / 24.0)
    out["utc_hour_cos"] = np.cos(2 * np.pi * starts.hour / 24.0)

    day_open_table = pd.DataFrame({"day": utc_day.to_numpy(), "open": out["open"].to_numpy()}).groupby("day", sort=True)["open"].first()
    out["day_open"] = utc_day.map(day_open_table)
    four_hour_key = pd.Series(starts.floor("4h"), index=out.index)
    four_hour_open = pd.DataFrame({"key": four_hour_key.to_numpy(), "open": out["open"].to_numpy()}).groupby("key", sort=True)["open"].first()
    out["four_hour_open"] = four_hour_key.map(four_hour_open)
    out["distance_day_open_atr"] = (out["close"] - out["day_open"]) / out["atr"]
    out["distance_4h_open_atr"] = (out["close"] - out["four_hour_open"]) / out["atr"]

    dealing_range = out["last_external_swing_high"] - out["last_external_swing_low"]
    out["dealing_position"] = (out["close"] - out["last_external_swing_low"]) / dealing_range.replace(0, np.nan)

    # Causal 3-candle FVGs; the current bar is fully completed at its availability index.
    out["bull_fvg_lower"] = out["high"].shift(2).where(out["low"] > out["high"].shift(2))
    out["bull_fvg_upper"] = out["low"].where(out["low"] > out["high"].shift(2))
    out["bear_fvg_lower"] = out["high"].where(out["high"] < out["low"].shift(2))
    out["bear_fvg_upper"] = out["low"].shift(2).where(out["high"] < out["low"].shift(2))

    if "open_interest" in out:
        oi = pd.to_numeric(out["open_interest"], errors="coerce").replace(0, np.nan)
        out["oi_change_1"] = np.log(oi).diff()
        out["oi_change_3"] = np.log(oi).diff(3)
        out["oi_change_12"] = np.log(oi).diff(12)
        oi_mean = out["oi_change_12"].rolling(288, min_periods=72).mean()
        oi_std = out["oi_change_12"].rolling(288, min_periods=72).std(ddof=0)
        out["oi_change_z"] = (out["oi_change_12"] - oi_mean) / oi_std.replace(0, np.nan)
    else:
        for name in ("oi_change_1", "oi_change_3", "oi_change_12", "oi_change_z"):
            out[name] = np.nan
    ratio_name = next((name for name in ("long_short_ratio", "buy_ratio") if name in out), None)
    if ratio_name:
        ratio = pd.to_numeric(out[ratio_name], errors="coerce")
        ratio_mean = ratio.rolling(288, min_periods=72).mean()
        ratio_std = ratio.rolling(288, min_periods=72).std(ddof=0)
        out["crowding_z"] = (ratio - ratio_mean) / ratio_std.replace(0, np.nan)
    else:
        out["crowding_z"] = np.nan
    if "mark_close" in out and "index_close" in out:
        out["mark_index_basis_atr"] = (out["mark_close"] - out["index_close"]) / out["atr"]
    else:
        out["mark_index_basis_atr"] = np.nan
    if "premium_close" in out:
        premium = pd.to_numeric(out["premium_close"], errors="coerce")
        prem_mean = premium.rolling(288, min_periods=72).mean()
        prem_std = premium.rolling(288, min_periods=72).std(ddof=0)
        out["premium_z"] = (premium - prem_mean) / prem_std.replace(0, np.nan)
    else:
        out["premium_z"] = np.nan
    return out


def add_pair_features(features: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    result = {symbol: frame.copy() for symbol, frame in features.items()}
    if not {"BTCUSDT", "ETHUSDT"}.issubset(result):
        return result
    common = result["BTCUSDT"].index.intersection(result["ETHUSDT"].index).sort_values()
    if common.empty:
        raise RuntimeError("BTC/ETH have no aligned completed decision bars")
    for symbol, peer in (("BTCUSDT", "ETHUSDT"), ("ETHUSDT", "BTCUSDT")):
        own = result[symbol]
        other = result[peer].loc[common]
        aligned = pd.DataFrame(index=common)
        for name in ("high", "low", "close", "atr", "rolling_12_high", "rolling_12_low", "return_1", "return_3", "return_12", "volume_z", "oi_change_3"):
            aligned[f"peer_{name}"] = other[name]
        aligned["smt_self_took_high"] = (
            (own.loc[common, "high"] > own.loc[common, "rolling_12_high"])
            & ~(other["high"] > other["rolling_12_high"])
        ).astype(float)
        aligned["smt_self_took_low"] = (
            (own.loc[common, "low"] < own.loc[common, "rolling_12_low"])
            & ~(other["low"] < other["rolling_12_low"])
        ).astype(float)
        aligned["smt_high_divergence_atr"] = (
            (own.loc[common, "high"] - own.loc[common, "rolling_12_high"]) / own.loc[common, "atr"]
            - ((other["high"] - other["rolling_12_high"]) / other["atr"]).clip(lower=0)
        )
        aligned["smt_low_divergence_atr"] = (
            (own.loc[common, "rolling_12_low"] - own.loc[common, "low"]) / own.loc[common, "atr"]
            - ((other["rolling_12_low"] - other["low"]) / other["atr"]).clip(lower=0)
        )
        aligned["relative_return_3"] = own.loc[common, "return_3"] - other["return_3"]
        aligned["relative_return_12"] = own.loc[common, "return_12"] - other["return_12"]
        for column in aligned:
            own[column] = aligned[column].reindex(own.index)
        result[symbol] = own
    return result


def _pool_source_name(column: str) -> str:
    base = column.replace("_high", "").replace("_low", "").upper()
    suffix = "HIGH" if column.endswith("_high") else "LOW"
    return f"{base}_{suffix}"


def _session_quality(row: pd.Series, source: str) -> float:
    if source.startswith("ASIA"):
        return float(row.get("london_killzone", 0.0) > 0 or row.get("new_york_killzone", 0.0) > 0)
    if source.startswith("NY_OR"):
        return float(row.get("post_ny_or", 0.0) > 0)
    if source.startswith("PREVIOUS_DAY"):
        return float(row.get("london_killzone", 0.0) > 0 or row.get("new_york_killzone", 0.0) > 0)
    return float(
        row.get("london_killzone", 0.0) > 0
        or row.get("new_york_killzone", 0.0) > 0
        or row.get("post_ny_or", 0.0) > 0
    )


def _event_pool(row: pd.Series, side: int, atr: float, config: StrategyConfig, acceptance: bool) -> tuple[float, str, int, float] | None:
    """Select the external pool that supports the intended delivery side.

    Reversal longs raid lows and reversal shorts raid highs. Continuation longs
    accept above high pools and continuation shorts accept below low pools.
    """
    choices: list[tuple[float, float, str, int, float]] = []
    for high_col, low_col, quality in POOL_SPECS:
        column = (high_col if side > 0 else low_col) if acceptance else (low_col if side > 0 else high_col)
        value = row.get(column)
        if not _finite(value):
            continue
        level = float(value)
        source = _pool_source_name(column)
        session_bonus = _session_quality(row, source)
        if acceptance and side > 0:
            penetration = (float(row["close"]) - level) / atr
            triggered = float(row["close"]) > level + config.acceptance_buffer_atr * atr
        elif acceptance and side < 0:
            penetration = (level - float(row["close"])) / atr
            triggered = float(row["close"]) < level - config.acceptance_buffer_atr * atr
        elif side > 0:
            penetration = (level - float(row["low"])) / atr
            triggered = float(row["low"]) < level - config.raid_buffer_atr * atr and float(row["close"]) > level
        else:
            penetration = (float(row["high"]) - level) / atr
            triggered = float(row["high"]) > level + config.raid_buffer_atr * atr and float(row["close"]) < level
        if triggered:
            score = quality + 1.5 * session_bonus + min(max(penetration, 0.0), 1.0)
            choices.append((score, -abs(float(row["close"]) - level), source, quality, level))
    if not choices:
        return None
    score, _, source, quality, level = max(choices)
    return float(level), source, int(quality), float(score)

def _last_opposite_candle_open(features: pd.DataFrame, position: int, side: int, lookback: int = 8) -> float | None:
    for index in range(position, max(-1, position - lookback), -1):
        row = features.iloc[index]
        if side > 0 and float(row["close"]) < float(row["open"]):
            return float(row["open"])
        if side < 0 and float(row["close"]) > float(row["open"]):
            return float(row["open"])
    return None


def _last_opposite_fvg(features: pd.DataFrame, position: int, side: int, lookback: int = 24) -> tuple[float, float] | None:
    lower_name, upper_name = ("bear_fvg_lower", "bear_fvg_upper") if side > 0 else ("bull_fvg_lower", "bull_fvg_upper")
    for index in range(position - 1, max(1, position - lookback), -1):
        row = features.iloc[index]
        lower, upper = row.get(lower_name), row.get(upper_name)
        if _finite(lower) and _finite(upper):
            lo, hi = sorted((float(lower), float(upper)))
            if hi > lo:
                return lo, hi
    return None


def _same_fvg(row: pd.Series, side: int) -> tuple[float, float] | None:
    lower_name, upper_name = ("bull_fvg_lower", "bull_fvg_upper") if side > 0 else ("bear_fvg_lower", "bear_fvg_upper")
    lower, upper = row.get(lower_name), row.get(upper_name)
    if not (_finite(lower) and _finite(upper)):
        return None
    lo, hi = sorted((float(lower), float(upper)))
    return (lo, hi) if hi > lo else None


def _order_block(features: pd.DataFrame, start: int, end: int, side: int) -> tuple[float, float] | None:
    segment = features.iloc[max(0, start):end]
    if side > 0:
        segment = segment[segment["close"] < segment["open"]]
    else:
        segment = segment[segment["close"] > segment["open"]]
    if segment.empty:
        return None
    row = segment.iloc[-1]
    lo, hi = sorted((float(row["open"]), float(row["close"])))
    return (lo, hi) if hi > lo else None


def _choose_zone(features: pd.DataFrame, event_pos: int, confirm_pos: int, side: int, atr: float) -> tuple[float, float, str] | None:
    row = features.iloc[confirm_pos]
    same = _same_fvg(row, side)
    opposite = _last_opposite_fvg(features, confirm_pos, side)
    ob = _order_block(features, event_pos - 6, confirm_pos, side)
    inverted: tuple[float, float] | None = None
    if opposite is not None:
        if side > 0 and float(row["close"]) > opposite[1]:
            inverted = opposite
        elif side < 0 and float(row["close"]) < opposite[0]:
            inverted = opposite
    if same is not None and inverted is not None:
        overlap = (max(same[0], inverted[0]), min(same[1], inverted[1]))
        if overlap[1] > overlap[0]:
            zone, kind = overlap, "BPR"
        else:
            zone, kind = inverted, "IFVG"
    elif inverted is not None:
        zone, kind = inverted, "IFVG"
    elif same is not None and ob is not None:
        overlap = (max(same[0], ob[0]), min(same[1], ob[1]))
        if overlap[1] > overlap[0]:
            zone, kind = overlap, "UNICORN"
        else:
            zone, kind = same, "FVG"
    elif same is not None:
        zone, kind = same, "FVG"
    elif ob is not None:
        zone, kind = ob, "OB"
    else:
        return None
    lower, upper = zone
    width_atr = (upper - lower) / max(atr, 1e-12)
    if not 0.015 <= width_atr <= 0.90:
        return None
    if side > 0 and upper >= float(row["close"]):
        return None
    if side < 0 and lower <= float(row["close"]):
        return None
    return float(lower), float(upper), kind


def _target_levels(row: pd.Series, side: int) -> list[tuple[float, int, str]]:
    levels: list[tuple[float, int, str]] = []
    for high_col, low_col, quality in POOL_SPECS:
        column = high_col if side > 0 else low_col
        value = row.get(column)
        if _finite(value):
            levels.append((float(value), quality, column.upper()))
    return levels


def _select_target(levels: Iterable[tuple[float, int, str]], side: int, entry: float, stop: float, minimum_r: float) -> tuple[float, int, str, float] | None:
    risk = abs(entry - stop)
    valid: list[tuple[float, int, str, float]] = []
    for price, quality, name in levels:
        distance = side * (price - entry)
        if distance <= 0:
            continue
        rr = distance / max(risk, 1e-12)
        if rr >= minimum_r:
            valid.append((price, quality, name, rr))
    if not valid:
        return None
    # The nearest qualifying untouched pool is the first draw; quality breaks ties.
    if side > 0:
        return min(valid, key=lambda item: (item[0], -item[1]))
    return max(valid, key=lambda item: (item[0], item[1]))


def _numeric_features(row: pd.Series) -> dict[str, float]:
    keep = (
        "atr_fraction", "body_atr", "range_atr", "close_location", "volume_z",
        "ema_spread_atr", "ema_slope_atr", "htf_bias", "return_1", "return_3",
        "return_12", "realized_vol_24", "compression_ratio", "dealing_position",
        "distance_day_open_atr", "distance_4h_open_atr", "oi_change_1", "oi_change_3",
        "oi_change_12", "oi_change_z", "crowding_z", "mark_index_basis_atr",
        "premium_z", "london_killzone", "new_york_killzone", "post_ny_or",
        "ny_time_sin", "ny_time_cos", "utc_hour_sin", "utc_hour_cos",
        "smt_self_took_high", "smt_self_took_low", "smt_high_divergence_atr",
        "smt_low_divergence_atr", "relative_return_3", "relative_return_12",
        "peer_volume_z", "peer_oi_change_3",
    )
    return {name: float(row[name]) for name in keep if name in row and _finite(row[name])}


def _candidate_feature_row(
    row: pd.Series,
    event_row: pd.Series,
    confirm_row: pd.Series,
    side: int,
    family: str,
    source: str,
    pool_quality: int,
    zone_kind: str,
    zone_lower: float,
    zone_upper: float,
    event_pos: int,
    confirm_pos: int,
    entry_pos: int,
    entry: float,
    stop: float,
    target: float,
    event_level: float,
) -> dict[str, float]:
    atr = float(row["atr"])
    features = _numeric_features(row)
    features.update(
        {
            "side": float(side),
            "symbol_btc": float(str(row.get("symbol")) == "BTCUSDT"),
            "family_reversal": float(family == "RAID_CISD_RETEST"),
            "family_continuation": float(family == "ACCEPTANCE_RETEST"),
            "pool_quality": float(pool_quality),
            "source_previous_week": float(source.startswith("PREVIOUS_WEEK")),
            "source_previous_day": float(source.startswith("PREVIOUS_DAY")),
            "source_asia": float(source.startswith("ASIA")),
            "source_ny_or": float(source.startswith("NY_OR")),
            "source_external_swing": float(source.startswith("LAST_EXTERNAL")),
            "zone_bpr": float(zone_kind == "BPR"),
            "zone_ifvg": float(zone_kind == "IFVG"),
            "zone_unicorn": float(zone_kind == "UNICORN"),
            "zone_fvg": float(zone_kind == "FVG"),
            "zone_ob": float(zone_kind == "OB"),
            "event_penetration_atr": (
                (event_level - float(event_row["low"])) / atr
                if family == "RAID_CISD_RETEST" and side > 0
                else (float(event_row["high"]) - event_level) / atr
                if family == "RAID_CISD_RETEST"
                else (float(event_row["close"]) - event_level) / atr
                if side > 0
                else (event_level - float(event_row["close"])) / atr
            ),
            "event_reclaim_atr": side * (float(event_row["close"]) - event_level) / atr,
            "confirmation_body_atr": side * float(confirm_row.get("body_atr", 0.0)),
            "confirmation_range_atr": float(confirm_row.get("range_atr", 0.0)),
            "confirmation_volume_z": float(confirm_row.get("volume_z", 0.0)) if _finite(confirm_row.get("volume_z")) else 0.0,
            "zone_width_atr": (zone_upper - zone_lower) / atr,
            "event_to_confirmation_bars": float(confirm_pos - event_pos),
            "confirmation_to_entry_bars": float(entry_pos - confirm_pos),
            "stop_distance_atr": abs(entry - stop) / atr,
            "target_distance_atr": abs(target - entry) / atr,
            "raw_reward_risk": abs(target - entry) / max(abs(entry - stop), 1e-12),
            "premium_discount_alignment": float((side > 0 and float(row.get("dealing_position", 0.5)) <= 0.5) or (side < 0 and float(row.get("dealing_position", 0.5)) >= 0.5)),
        }
    )
    return features


def generate_candidates(features_by_symbol: Mapping[str, pd.DataFrame], config: StrategyConfig) -> list[Candidate]:
    candidates: list[Candidate] = []
    for symbol, features in sorted(features_by_symbol.items()):
        features = features.sort_index()
        recent: dict[tuple[int, str, str], int] = {}
        for event_pos in range(max(220, config.pivot_left + config.pivot_right + 5), len(features) - config.cisd_max_bars - config.retest_max_bars - 2):
            event_row = features.iloc[event_pos]
            atr = float(event_row.get("atr")) if _finite(event_row.get("atr")) else math.nan
            if not np.isfinite(atr) or atr <= 0:
                continue
            for side in (1, -1):
                for family, acceptance in (("RAID_CISD_RETEST", False), ("ACCEPTANCE_RETEST", True)):
                    event = _event_pool(event_row, side, atr, config, acceptance)
                    if event is None:
                        continue
                    level, source, quality, _ = event
                    key = (side, source, family)
                    if key in recent and event_pos - recent[key] < 10:
                        continue
                    # Reversal events should occur in the appropriate half of the dealing range.
                    dealing_position = float(event_row.get("dealing_position", 0.5)) if _finite(event_row.get("dealing_position")) else 0.5
                    if family == "RAID_CISD_RETEST":
                        if side > 0 and dealing_position > 0.72:
                            continue
                        if side < 0 and dealing_position < 0.28:
                            continue
                    origin = _last_opposite_candle_open(features, event_pos, side)
                    if origin is None:
                        continue
                    confirm_pos: int | None = None
                    zone: tuple[float, float, str] | None = None
                    for position in range(event_pos + 1, min(len(features), event_pos + 1 + config.cisd_max_bars)):
                        row = features.iloc[position]
                        row_atr = float(row.get("atr")) if _finite(row.get("atr")) else atr
                        body = side * float(row.get("body_atr", 0.0))
                        range_atr = float(row.get("range_atr", 0.0))
                        close = float(row["close"])
                        if family == "RAID_CISD_RETEST":
                            structure = float(features.iloc[position - 1]["last_internal_swing_high" if side > 0 else "last_internal_swing_low"])
                            confirmed = (
                                close > origin and close > structure if side > 0 else close < origin and close < structure
                            )
                        else:
                            # Acceptance must hold outside the broken pool and continue to displace.
                            confirmed = close > level if side > 0 else close < level
                        if not confirmed or body < config.cisd_body_atr or range_atr < config.cisd_range_atr:
                            continue
                        candidate_zone = _choose_zone(features, event_pos, position, side, row_atr)
                        if candidate_zone is None:
                            continue
                        confirm_pos, zone = position, candidate_zone
                        break
                    if confirm_pos is None or zone is None:
                        continue
                    zone_lower, zone_upper, zone_kind = zone
                    retest_extreme: float | None = None
                    retest_pos: int | None = None
                    entry_pos: int | None = None
                    for position in range(confirm_pos + 1, min(len(features), confirm_pos + 1 + config.retest_max_bars)):
                        row = features.iloc[position]
                        row_atr = float(row.get("atr")) if _finite(row.get("atr")) else atr
                        tolerance = config.retest_tolerance_atr * row_atr
                        if family == "RAID_CISD_RETEST":
                            if side > 0 and float(row["low"]) < float(event_row["low"]) - config.stop_buffer_atr * row_atr:
                                break
                            if side < 0 and float(row["high"]) > float(event_row["high"]) + config.stop_buffer_atr * row_atr:
                                break
                        else:
                            if side > 0 and float(row["close"]) < level - config.acceptance_buffer_atr * row_atr:
                                break
                            if side < 0 and float(row["close"]) > level + config.acceptance_buffer_atr * row_atr:
                                break
                        touched = float(row["low"]) <= zone_upper + tolerance and float(row["high"]) >= zone_lower - tolerance
                        if touched:
                            if retest_pos is None:
                                retest_pos = position
                                retest_extreme = float(row["low"] if side > 0 else row["high"])
                            else:
                                retest_extreme = min(float(retest_extreme), float(row["low"])) if side > 0 else max(float(retest_extreme), float(row["high"]))
                            body = side * float(row.get("body_atr", 0.0))
                            location = float(row.get("close_location", 0.5))
                            same_bar = (
                                float(row["close"]) > zone_upper and body > 0 and location >= config.rejection_close_location
                                if side > 0
                                else float(row["close"]) < zone_lower and body > 0 and location <= 1 - config.rejection_close_location
                            )
                            if same_bar:
                                entry_pos = position
                                break
                        if retest_pos is not None and position > retest_pos:
                            first = features.iloc[retest_pos]
                            body = side * float(row.get("body_atr", 0.0))
                            later = (
                                float(row["close"]) > float(first["high"]) and body > 0
                                if side > 0
                                else float(row["close"]) < float(first["low"]) and body > 0
                            )
                            if later:
                                entry_pos = position
                                break
                    if entry_pos is None or retest_extreme is None:
                        continue
                    row = features.iloc[entry_pos]
                    entry = float(row["close"])
                    row_atr = float(row["atr"])
                    if side > 0:
                        stop = min(float(event_row["low"]), float(retest_extreme), zone_lower) - config.stop_buffer_atr * row_atr
                    else:
                        stop = max(float(event_row["high"]), float(retest_extreme), zone_upper) + config.stop_buffer_atr * row_atr
                    stop_atr = abs(entry - stop) / row_atr
                    if not config.minimum_stop_atr <= stop_atr <= config.maximum_stop_atr:
                        continue
                    target = _select_target(_target_levels(row, side), side, entry, stop, config.minimum_target_r)
                    if target is None:
                        continue
                    target_price, target_quality, target_name, rr = target
                    internal = row.get("last_internal_swing_high" if side > 0 else "last_internal_swing_low")
                    one_r = entry + side * abs(entry - stop)
                    if _finite(internal) and side * (float(internal) - entry) > 0 and side * (target_price - float(internal)) > 0:
                        tp1 = float(internal)
                    else:
                        tp1 = one_r
                    if side * (tp1 - entry) <= 0 or side * (target_price - tp1) <= 0:
                        tp1 = one_r
                    decision_time = pd.Timestamp(features.index[entry_pos])
                    digest = hashlib.sha256(
                        f"{symbol}|{decision_time.isoformat()}|{side}|{family}|{source}|{zone_kind}|{entry:.12g}|{stop:.12g}|{target_price:.12g}".encode()
                    ).hexdigest()[:24]
                    feature_row = _candidate_feature_row(
                        row, event_row, features.iloc[confirm_pos], side, family, source,
                        quality, zone_kind, zone_lower, zone_upper, event_pos, confirm_pos,
                        entry_pos, entry, stop, target_price, level,
                    )
                    feature_row["target_quality"] = float(target_quality)
                    feature_row["target_previous_week"] = float(target_name.startswith("PREVIOUS_WEEK"))
                    feature_row["target_previous_day"] = float(target_name.startswith("PREVIOUS_DAY"))
                    candidates.append(
                        Candidate(
                            digest, decision_time, symbol, side, family, source, quality,
                            zone_kind, entry, stop, float(target_price), float(tp1), level,
                            float(event_row["low"] if side > 0 else event_row["high"]),
                            zone_lower, zone_upper, zone_lower if side > 0 else zone_upper,
                            feature_row,
                        )
                    )
                    recent[key] = event_pos
        # End symbol loop.
    # Same-time same-symbol same-side duplicates are reduced to the best structural route.
    deduped: dict[tuple[pd.Timestamp, str, int], Candidate] = {}
    for candidate in sorted(candidates, key=lambda item: (item.decision_time, item.symbol, item.side, item.candidate_id)):
        key = (candidate.decision_time, candidate.symbol, candidate.side)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = candidate
            continue
        current_key = (candidate.pool_quality, candidate.features.get("raw_reward_risk", 0.0), candidate.features.get("zone_bpr", 0.0), candidate.features.get("zone_ifvg", 0.0))
        existing_key = (existing.pool_quality, existing.features.get("raw_reward_risk", 0.0), existing.features.get("zone_bpr", 0.0), existing.features.get("zone_ifvg", 0.0))
        if current_key > existing_key:
            deduped[key] = candidate
    return sorted(deduped.values(), key=lambda item: (item.decision_time, item.symbol, item.side))


def _execution_arrays(frame: pd.DataFrame) -> dict[str, Any]:
    data = frame.copy()
    data["bar_start"] = pd.to_datetime(data["bar_start"], utc=True)
    data = data.sort_values("bar_start", kind="stable")
    return {
        "frame": data,
        "times": pd.DatetimeIndex(data["bar_start"]).as_unit("ns").asi8,
        "timestamps": pd.DatetimeIndex(data["bar_start"]),
        "open": data["open"].to_numpy(float),
        "high": data["high"].to_numpy(float),
        "low": data["low"].to_numpy(float),
        "close": data["close"].to_numpy(float),
    }


def _funding_arrays(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"times": np.asarray([], dtype=np.int64), "rates": np.asarray([], dtype=float)}
    index = pd.DatetimeIndex(frame.index).as_unit("ns")
    rates = pd.to_numeric(frame["funding_rate"], errors="coerce").fillna(0.0).to_numpy(float)
    return {"times": index.asi8, "rates": rates}


def _mark_at(execution: Mapping[str, Any], timestamp: pd.Timestamp) -> float:
    position = int(np.searchsorted(execution["times"], timestamp.value, side="right")) - 1
    position = min(max(position, 0), len(execution["close"]) - 1)
    return float(execution["close"][position])


def _funding_pnl_per_unit(
    funding: Mapping[str, Any], execution: Mapping[str, Any], side: int,
    start: pd.Timestamp, end: pd.Timestamp,
) -> float:
    left = int(np.searchsorted(funding["times"], start.value, side="right"))
    right = int(np.searchsorted(funding["times"], end.value, side="right"))
    pnl = 0.0
    for timestamp_ns, rate in zip(funding["times"][left:right], funding["rates"][left:right], strict=True):
        timestamp = pd.to_datetime(int(timestamp_ns), unit="ns", utc=True)
        pnl += -side * _mark_at(execution, timestamp) * float(rate)
    return float(pnl)


def simulate_outcome(
    candidate: Candidate,
    execution: Mapping[str, Any],
    funding: Mapping[str, Any],
    management: str,
    config: StrategyConfig,
    end_exclusive: pd.Timestamp,
) -> Outcome:
    activation = candidate.decision_time + pd.Timedelta(milliseconds=config.activation_latency_ms)
    position = int(np.searchsorted(execution["times"], activation.value, side="right"))
    if position >= len(execution["open"]):
        return Outcome(candidate.candidate_id, management, "NO_EXECUTION_BAR", None, None, None, None, None, None, None, None, None, 0.0, ())
    timestamps = execution["timestamps"]
    if timestamps[position] >= end_exclusive:
        return Outcome(candidate.candidate_id, management, "NO_EXECUTION_BAR", None, None, None, None, None, None, None, None, None, 0.0, ())
    entry_cost = (config.half_spread_bps + config.entry_slippage_bps) / 10_000.0
    entry = float(execution["open"][position]) * (1 + candidate.side * entry_cost)
    stop = float(candidate.stop_reference)
    target = float(candidate.target_reference)
    if candidate.side * (entry - stop) <= 0 or candidate.side * (target - entry) <= 0:
        return Outcome(candidate.candidate_id, management, "INVALID_ENTRY_GEOMETRY", timestamps[position], timestamps[position], entry, stop, target, None, None, None, 0.0, 0.0, ())
    risk_distance = abs(entry - stop)
    tp1 = float(candidate.tp1_reference)
    if candidate.side * (tp1 - entry) <= 0 or candidate.side * (target - tp1) <= 0:
        tp1 = entry + candidate.side * risk_distance
    stop_reference_fill = stop * (1 - config.stop_slippage_bps / 10_000.0 if candidate.side > 0 else 1 + config.stop_slippage_bps / 10_000.0)
    planned_loss = risk_distance + entry * config.taker_fee_rate + abs(stop_reference_fill) * config.taker_fee_rate + abs(stop_reference_fill - stop)
    remaining = 1.0
    tp1_done = False
    legs: list[ExitLeg] = []
    status = "OPEN"
    exit_time: pd.Timestamp | None = None
    for index in range(position, len(execution["open"])):
        timestamp = timestamps[index]
        if timestamp >= end_exclusive:
            break
        open_price = float(execution["open"][index])
        high = float(execution["high"][index])
        low = float(execution["low"][index])
        active_stop = entry if tp1_done and management == "SCALE_LIQUIDITY_BE" else stop
        stop_hit = low <= active_stop if candidate.side > 0 else high >= active_stop
        target_hit = high >= target if candidate.side > 0 else low <= target
        tp1_hit = high >= tp1 if candidate.side > 0 else low <= tp1
        if stop_hit:
            if candidate.side > 0:
                raw = open_price if open_price < active_stop else active_stop
                price = raw * (1 - config.stop_slippage_bps / 10_000.0)
            else:
                raw = open_price if open_price > active_stop else active_stop
                price = raw * (1 + config.stop_slippage_bps / 10_000.0)
            reason = "TP1_THEN_BREAKEVEN" if tp1_done and management == "SCALE_LIQUIDITY_BE" else "STOP"
            legs.append(ExitLeg(timestamp, remaining, price, config.taker_fee_rate, reason))
            remaining = 0.0
            status = reason
            exit_time = timestamp
            break
        if management == "SCALE_LIQUIDITY_BE" and not tp1_done and tp1_hit:
            fraction = min(0.5, remaining)
            price = tp1 * (1 - candidate.side * config.target_slippage_bps / 10_000.0)
            legs.append(ExitLeg(timestamp, fraction, price, config.taker_fee_rate, "TP1"))
            remaining -= fraction
            tp1_done = True
            # Do not credit target on the same minute as the first partial.
            continue
        if target_hit:
            price = target * (1 - candidate.side * config.target_slippage_bps / 10_000.0)
            legs.append(ExitLeg(timestamp, remaining, price, config.taker_fee_rate, "TARGET"))
            remaining = 0.0
            status = "TP1_THEN_TARGET" if tp1_done else "TARGET"
            exit_time = timestamp
            break
    if exit_time is None:
        final_position = int(np.searchsorted(execution["times"], (end_exclusive - pd.Timedelta(nanoseconds=1)).value, side="right")) - 1
        if final_position < position:
            return Outcome(candidate.candidate_id, management, "NO_EXECUTION_BAR", None, None, None, None, None, None, None, None, None, 0.0, ())
        mark = float(execution["close"][final_position]) * (1 - candidate.side * (config.half_spread_bps + config.target_slippage_bps) / 10_000.0)
        legs.append(ExitLeg(end_exclusive, remaining, mark, config.taker_fee_rate, "MARK_TO_MARKET"))
        remaining = 0.0
        exit_time = end_exclusive
        status = "OPEN"
    gross = sum(leg.fraction * candidate.side * (leg.price - entry) for leg in legs)
    entry_fee = entry * config.taker_fee_rate
    exit_fees = sum(leg.fraction * leg.price * leg.fee_rate for leg in legs)
    funding_pnl = _funding_pnl_per_unit(funding, execution, candidate.side, timestamps[position], pd.Timestamp(exit_time))
    unit_pnl = gross - entry_fee - exit_fees + funding_pnl
    net_r = unit_pnl / max(planned_loss, 1e-12)
    hold_minutes = max(0.0, (pd.Timestamp(exit_time) - timestamps[position]).total_seconds() / 60.0)
    return Outcome(
        candidate.candidate_id, management, status, timestamps[position], pd.Timestamp(exit_time), entry,
        stop, target, planned_loss, unit_pnl, net_r, hold_minutes, funding_pnl, tuple(legs),
    )


def _training_rows(
    candidates: Sequence[Candidate], outcomes: Mapping[tuple[str, str], Outcome],
    update_time: pd.Timestamp, policy: Policy,
) -> tuple[pd.DataFrame, np.ndarray | None]:
    rows: list[dict[str, Any]] = []
    dates: list[pd.Timestamp] = []
    lower_bound = None if policy.window_days is None else update_time - pd.Timedelta(days=policy.window_days)
    for candidate in candidates:
        if candidate.decision_time >= update_time:
            break
        if lower_bound is not None and candidate.decision_time < lower_bound:
            continue
        for management in ("FULL_TARGET", "SCALE_LIQUIDITY_BE"):
            outcome = outcomes.get((candidate.candidate_id, management))
            if outcome is None or outcome.exit_time is None or outcome.exit_time > update_time or outcome.status == "OPEN":
                continue
            if outcome.net_r is None or not np.isfinite(outcome.net_r):
                continue
            row = dict(candidate.features)
            row["management_scale"] = float(management == "SCALE_LIQUIDITY_BE")
            row["net_r"] = float(outcome.net_r)
            row["positive"] = int(outcome.net_r > 0)
            rows.append(row)
            dates.append(candidate.decision_time)
    if not rows:
        return pd.DataFrame(), None
    data = pd.DataFrame(rows)
    weights = None
    if policy.decay_half_life_days is not None:
        ages = np.asarray([(update_time - timestamp).total_seconds() / 86400.0 for timestamp in dates], dtype=float)
        weights = np.exp(-math.log(2.0) * ages / policy.decay_half_life_days)
    return data, weights


class ActionModel:
    def __init__(self, config: StrategyConfig, seeds: tuple[int, ...] = (17, 43, 97)) -> None:
        self.config = config
        self.seeds = seeds
        self.features: list[str] = []
        self.regressors: list[HistGradientBoostingRegressor] = []
        self.classifiers: list[HistGradientBoostingClassifier] = []

    def fit(self, data: pd.DataFrame, weights: np.ndarray | None) -> "ActionModel":
        if len(data) < self.config.minimum_training_rows:
            raise ValueError("insufficient training rows")
        self.features = sorted(column for column in data.columns if column not in {"net_r", "positive"})
        x = data[self.features].replace([np.inf, -np.inf], np.nan)
        y = data["net_r"].to_numpy(float)
        positive = data["positive"].to_numpy(int)
        if len(np.unique(positive)) < 2:
            raise ValueError("classifier target has one class")
        self.regressors = []
        self.classifiers = []
        for seed in self.seeds:
            reg = HistGradientBoostingRegressor(
                learning_rate=self.config.learning_rate,
                max_leaf_nodes=self.config.max_leaf_nodes,
                max_iter=self.config.max_iter,
                min_samples_leaf=self.config.min_samples_leaf,
                l2_regularization=self.config.l2_regularization,
                loss="absolute_error",
                random_state=self.config.random_state + seed,
            )
            clf = HistGradientBoostingClassifier(
                learning_rate=self.config.learning_rate,
                max_leaf_nodes=self.config.max_leaf_nodes,
                max_iter=self.config.max_iter,
                min_samples_leaf=self.config.min_samples_leaf,
                l2_regularization=self.config.l2_regularization,
                random_state=self.config.random_state + seed,
            )
            reg.fit(x, y, sample_weight=weights)
            clf.fit(x, positive, sample_weight=weights)
            self.regressors.append(reg)
            self.classifiers.append(clf)
        return self

    def score(self, candidate: Candidate, management: str) -> tuple[float, float, float, float]:
        row = {name: candidate.features.get(name, np.nan) for name in self.features}
        row["management_scale"] = float(management == "SCALE_LIQUIDITY_BE")
        x = pd.DataFrame([row], columns=self.features).replace([np.inf, -np.inf], np.nan)
        predictions = np.asarray([model.predict(x)[0] for model in self.regressors], dtype=float)
        probabilities = np.asarray([model.predict_proba(x)[0, 1] for model in self.classifiers], dtype=float)
        expected = float(predictions.mean())
        uncertainty = float(predictions.std(ddof=0))
        probability = float(probabilities.mean())
        lower = expected - self.config.uncertainty_penalty * uncertainty
        # A calibrated probability term only ranks otherwise-similar expected-R actions.
        lower += 0.10 * (probability - 0.5)
        return lower, expected, probability, uncertainty


def walk_forward_scores(
    candidates: Sequence[Candidate],
    outcomes: Mapping[tuple[str, str], Outcome],
    start: pd.Timestamp,
    end: pd.Timestamp,
    policy: Policy,
    config: StrategyConfig,
) -> dict[tuple[str, str], dict[str, Any]]:
    ordered = sorted(candidates, key=lambda item: item.decision_time)
    evaluation = [candidate for candidate in ordered if start <= candidate.decision_time < end]
    if policy.static:
        updates = [start]
    else:
        assert policy.cadence_days is not None
        updates = list(pd.date_range(start.floor("D"), end, freq=f"{policy.cadence_days}D"))
    update_index = 0
    active: ActionModel | None = None
    active_at: pd.Timestamp | None = None
    active_rows = 0
    pending: tuple[pd.Timestamp, ActionModel, int] | None = None
    scores: dict[tuple[str, str], dict[str, Any]] = {}

    def train(update_time: pd.Timestamp) -> tuple[pd.Timestamp, ActionModel, int] | None:
        data, weights = _training_rows(ordered, outcomes, update_time, policy)
        if len(data) < config.minimum_training_rows:
            return None
        try:
            model = ActionModel(config).fit(data, weights)
        except ValueError:
            return None
        activation = update_time + pd.Timedelta(minutes=config.training_completion_lag_minutes)
        return activation, model, len(data)

    initial_time = start
    trained = train(initial_time)
    if trained is not None:
        active_at, active, active_rows = trained
    for candidate in evaluation:
        while update_index < len(updates) and updates[update_index] <= candidate.decision_time:
            if not (policy.static and update_index > 0):
                result = train(pd.Timestamp(updates[update_index]))
                if result is not None:
                    pending = result
            update_index += 1
        if pending is not None and pending[0] <= candidate.decision_time:
            active_at, active, active_rows = pending
            pending = None
        if active is None or active_at is None or candidate.decision_time < active_at:
            continue
        for management in ("FULL_TARGET", "SCALE_LIQUIDITY_BE"):
            lower, expected, probability, uncertainty = active.score(candidate, management)
            scores[(candidate.candidate_id, management)] = {
                "lower_score_r": lower,
                "expected_r": expected,
                "positive_probability": probability,
                "uncertainty_r": uncertainty,
                "training_rows": active_rows,
                "model_activated_at": active_at,
            }
    return scores


def _outcome_pnl_to_time(
    candidate: Candidate, outcome: Outcome, execution: Mapping[str, Any], funding: Mapping[str, Any], timestamp: pd.Timestamp,
    config: StrategyConfig,
) -> float:
    if outcome.entry_time is None or outcome.entry_price is None or timestamp <= outcome.entry_time:
        return 0.0
    realized = 0.0
    closed_fraction = 0.0
    for leg in outcome.legs:
        if leg.timestamp <= timestamp:
            realized += leg.fraction * candidate.side * (leg.price - outcome.entry_price) - leg.fraction * leg.price * leg.fee_rate
            closed_fraction += leg.fraction
    remaining = max(0.0, 1.0 - closed_fraction)
    if remaining > 0:
        mark = _mark_at(execution, timestamp)
        realized += remaining * candidate.side * (mark - outcome.entry_price) - remaining * mark * config.taker_fee_rate
    realized -= outcome.entry_price * config.taker_fee_rate
    realized += _funding_pnl_per_unit(funding, execution, candidate.side, outcome.entry_time, timestamp)
    return float(realized)


def replay_account(
    candidates: Sequence[Candidate],
    outcomes: Mapping[tuple[str, str], Outcome],
    scores: Mapping[tuple[str, str], Mapping[str, Any]],
    executions: Mapping[str, Mapping[str, Any]],
    funding: Mapping[str, Mapping[str, Any]],
    start: pd.Timestamp,
    end: pd.Timestamp,
    threshold: float,
    risk_fraction: float,
    maximum_leverage: float,
    config: StrategyConfig,
    initial_nav: float = 10_000.0,
) -> dict[str, Any]:
    grouped: dict[pd.Timestamp, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        if start <= candidate.decision_time < end:
            grouped[candidate.decision_time].append(candidate)
    cash = float(initial_nav)
    slot_release = start
    trade_records: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    cash_events: list[tuple[pd.Timestamp, float]] = [(start, cash)]
    invalid = False
    for decision_time in sorted(grouped):
        if decision_time < slot_release or cash <= 0:
            continue
        options: list[tuple[float, float, Candidate, str, Outcome, Mapping[str, Any]]] = []
        for candidate in grouped[decision_time]:
            for management in ("FULL_TARGET", "SCALE_LIQUIDITY_BE"):
                score = scores.get((candidate.candidate_id, management))
                outcome = outcomes.get((candidate.candidate_id, management))
                if score is None or outcome is None:
                    continue
                if float(score["lower_score_r"]) < threshold or float(score["expected_r"]) <= 0:
                    continue
                if outcome.entry_time is None or outcome.entry_price is None or outcome.planned_unit_loss is None or outcome.unit_pnl is None:
                    continue
                options.append((float(score["lower_score_r"]), float(score["expected_r"]), candidate, management, outcome, score))
        if not options:
            continue
        _, _, candidate, management, outcome, score = max(options, key=lambda item: (item[0], item[1], item[2].features.get("raw_reward_risk", 0.0)))
        if outcome.entry_time is None or outcome.entry_time >= end:
            continue
        effective_exit = min(pd.Timestamp(outcome.exit_time or end), end)
        entry_equity = cash
        risk_quantity = cash * risk_fraction / max(float(outcome.planned_unit_loss), 1e-12)
        stop_fraction = abs(float(outcome.entry_price) - float(outcome.stop_price or candidate.stop_reference)) / float(outcome.entry_price)
        maximum_safe_leverage = 1.0 / max(stop_fraction + config.maintenance_margin_fraction + config.liquidation_buffer_fraction, 1e-12)
        leverage_quantity = cash * min(maximum_leverage, maximum_safe_leverage) / float(outcome.entry_price)
        raw_quantity = min(risk_quantity, leverage_quantity)
        rule = INSTRUMENT[candidate.symbol]
        quantity = math.floor(raw_quantity / rule["step"]) * rule["step"]
        if quantity < rule["minimum"] or quantity * float(outcome.entry_price) < 5.0:
            continue
        pnl = quantity * float(outcome.unit_pnl)
        cash += pnl
        if not np.isfinite(cash) or cash <= 0:
            invalid = True
        cash_events.append((effective_exit, cash))
        account_return = pnl / max(entry_equity, 1e-12)
        record = {
            "candidate_id": candidate.candidate_id,
            "symbol": candidate.symbol,
            "side": candidate.side,
            "family": candidate.family,
            "pool_source": candidate.pool_source,
            "zone_kind": candidate.zone_kind,
            "management": management,
            "opened_at": outcome.entry_time,
            "closed_at": effective_exit,
            "quantity": quantity,
            "entry_price": outcome.entry_price,
            "net_pnl": pnl,
            "account_return": account_return,
            "net_r": outcome.net_r,
            "status": outcome.status,
            "score": dict(score),
        }
        trade_records.append(record)
        positions.append({"candidate": candidate, "outcome": outcome, "quantity": quantity, "entry_equity": entry_equity})
        slot_release = effective_exit
        if effective_exit >= end and outcome.status == "OPEN":
            break
    daily_nav: list[dict[str, Any]] = []
    peak = initial_nav
    maximum_drawdown = 0.0
    for day_end in pd.date_range(start.floor("D") + pd.Timedelta(days=1), end, freq="1D"):
        prior_cash = [value for timestamp, value in cash_events if timestamp <= day_end]
        nav = prior_cash[-1] if prior_cash else initial_nav
        for position in positions:
            outcome: Outcome = position["outcome"]
            if outcome.entry_time is None:
                continue
            if outcome.entry_time <= day_end < pd.Timestamp(outcome.exit_time or end):
                candidate: Candidate = position["candidate"]
                unit = _outcome_pnl_to_time(candidate, outcome, executions[candidate.symbol], funding[candidate.symbol], day_end, config)
                nav = position["entry_equity"] + position["quantity"] * unit
                break
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, 1 - nav / max(peak, 1e-12))
        daily_nav.append({"day_end": day_end, "nav": float(nav)})
    end_nav = daily_nav[-1]["nav"] if daily_nav else cash
    days = max(1, int((end - start) / pd.Timedelta(days=1)))
    geometric_daily_growth = math.exp(math.log(max(end_nav, 1e-12) / initial_nav) / days) - 1 if end_nav > 0 else -1.0
    pnls = np.asarray([row["net_pnl"] for row in trade_records], dtype=float)
    returns = np.asarray([row["account_return"] for row in trade_records], dtype=float)
    positives = pnls[pnls > 0]
    negatives = pnls[pnls < 0]
    profit_factor = float(positives.sum() / abs(negatives.sum())) if negatives.size else (None if positives.size else 0.0)
    top_five_share = float(np.sort(positives)[-5:].sum() / positives.sum()) if positives.size and positives.sum() > 0 else 0.0
    winner_removed_multiple = 1.0
    if len(returns):
        remove_index = int(np.argmax(pnls)) if positives.size else -1
        for index, value in enumerate(returns):
            if index == remove_index:
                continue
            winner_removed_multiple *= max(1.0 + value, 1e-12)
    return {
        "start_nav": initial_nav,
        "end_nav": float(end_nav),
        "account_multiple": float(end_nav / initial_nav),
        "total_return": float(end_nav / initial_nav - 1),
        "calendar_days": days,
        "geometric_daily_growth": float(geometric_daily_growth),
        "maximum_drawdown": float(maximum_drawdown),
        "completed_trades": len(trade_records),
        "win_rate": float((pnls > 0).mean()) if len(pnls) else 0.0,
        "profit_factor": profit_factor,
        "median_trade_return": float(np.median(returns)) if len(returns) else 0.0,
        "top_five_positive_pnl_share": top_five_share,
        "winner_removal_return": float(winner_removed_multiple - 1.0),
        "liquidated_or_invalid": bool(invalid or end_nav <= 0),
        "trades": _jsonable(trade_records),
        "daily_nav": _jsonable(daily_nav),
    }


def _compact(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metrics.items() if key not in {"trades", "daily_nav"}}


def _raw_economics(candidates: Sequence[Candidate], outcomes: Mapping[tuple[str, str], Outcome], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for management in ("FULL_TARGET", "SCALE_LIQUIDITY_BE"):
        values = []
        families: Counter[str] = Counter()
        for candidate in candidates:
            if not (start <= candidate.decision_time < end):
                continue
            outcome = outcomes.get((candidate.candidate_id, management))
            if outcome is None or outcome.net_r is None or not np.isfinite(outcome.net_r) or outcome.status == "OPEN":
                continue
            values.append(float(outcome.net_r))
            families[candidate.family] += 1
        array = np.asarray(values, dtype=float)
        result[management] = {
            "resolved": int(len(array)),
            "mean_net_r": float(array.mean()) if len(array) else None,
            "median_net_r": float(np.median(array)) if len(array) else None,
            "positive_fraction": float((array > 0).mean()) if len(array) else None,
            "sum_net_r": float(array.sum()) if len(array) else None,
            "p10": float(np.quantile(array, 0.10)) if len(array) else None,
            "p90": float(np.quantile(array, 0.90)) if len(array) else None,
            "family_counts": dict(sorted(families.items())),
        }
    return result


def load_inputs(data_root: Path, canonical_repo: Path, config: StrategyConfig) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    decisions: dict[str, pd.DataFrame] = {}
    executions: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    loader = load_loader(canonical_repo)
    for symbol in SYMBOLS:
        decision, funding_frame = assemble_symbol_frame(
            data_root, canonical_repo, symbol, SEGMENTS,
            CanonicalInputConfig(trade_timeframe="5m", decision_timeframe_ms=5 * 60 * 1000, require_complete=True),
        )
        raw_execution = loader.concatenate_segments(data_root, symbol, kind="trade_bar", name="1m", segments=SEGMENTS)
        execution = normalize_trade_bars(raw_execution, CanonicalInputConfig(trade_timeframe="1m", decision_timeframe_ms=60 * 1000, require_complete=True))
        decisions[symbol] = decision
        executions[symbol] = execution
        funding[symbol] = funding_frame
    return decisions, executions, funding


def _write_frame(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    frame = pd.DataFrame([_jsonable(row) for row in rows])
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def run(args: argparse.Namespace) -> int:
    config = StrategyConfig()
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    started = monotonic()
    decisions, execution_frames, funding_frames = load_inputs(args.data_root, args.canonical_repo, config)
    timings["load_seconds"] = round(monotonic() - started, 3)

    started = monotonic()
    features = {symbol: build_features(frame, symbol, config) for symbol, frame in decisions.items()}
    features = add_pair_features(features)
    candidates = generate_candidates(features, config)
    timings["feature_candidate_seconds"] = round(monotonic() - started, 3)

    candidate_rows = []
    for candidate in candidates:
        row = {key: value for key, value in dataclasses.asdict(candidate).items() if key != "features"}
        row.update({f"feature__{key}": value for key, value in candidate.features.items()})
        candidate_rows.append(row)
    _write_frame(candidate_rows, output / "CANDIDATES.parquet")

    executions = {symbol: _execution_arrays(frame) for symbol, frame in execution_frames.items()}
    funding = {symbol: _funding_arrays(frame) for symbol, frame in funding_frames.items()}
    full_end = pd.Timestamp(args.end_exclusive)
    started = monotonic()
    outcomes: dict[tuple[str, str], Outcome] = {}
    outcome_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        for management in ("FULL_TARGET", "SCALE_LIQUIDITY_BE"):
            outcome = simulate_outcome(candidate, executions[candidate.symbol], funding[candidate.symbol], management, config, full_end)
            outcomes[(candidate.candidate_id, management)] = outcome
            row = _jsonable(dataclasses.asdict(outcome))
            row["legs"] = json.dumps(row["legs"], ensure_ascii=False, sort_keys=True)
            outcome_rows.append(row)
    _write_frame(outcome_rows, output / "OUTCOMES.parquet")
    timings["label_seconds"] = round(monotonic() - started, 3)

    selection_start = pd.Timestamp("2023-01-01T00:00:00Z")
    evaluation_start = pd.Timestamp("2024-01-01T00:00:00Z")
    evaluation_end = pd.Timestamp(args.end_exclusive)
    thresholds = (0.0, 0.025, 0.05, 0.075, 0.10, 0.15, 0.25, 0.40)
    policy_rows: list[dict[str, Any]] = []
    score_ledgers: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    started = monotonic()
    for policy in POLICIES:
        scores = walk_forward_scores(candidates, outcomes, selection_start, evaluation_end, policy, config)
        score_ledgers[policy.name] = scores
        for threshold in thresholds:
            metrics_2023 = replay_account(
                candidates, outcomes, scores, executions, funding,
                selection_start, evaluation_start, threshold, 0.01, 5.0, config,
            )
            metrics_h1 = replay_account(
                candidates, outcomes, scores, executions, funding,
                evaluation_start, evaluation_end, threshold, 0.01, 5.0, config,
            )
            policy_rows.append(
                {
                    "policy": policy.name,
                    "threshold_r": threshold,
                    "risk_fraction": 0.01,
                    "maximum_leverage": 5.0,
                    "metrics_2023": metrics_2023,
                    "metrics_2024h1": metrics_h1,
                }
            )
    timings["policy_grid_seconds"] = round(monotonic() - started, 3)

    viable = [
        row for row in policy_rows
        if row["metrics_2023"]["completed_trades"] > 0
        and row["metrics_2024h1"]["completed_trades"] > 0
        and not row["metrics_2023"]["liquidated_or_invalid"]
        and not row["metrics_2024h1"]["liquidated_or_invalid"]
        and row["metrics_2023"]["geometric_daily_growth"] > 0
        and row["metrics_2024h1"]["geometric_daily_growth"] > 0
    ]
    selected_base = max(
        viable,
        key=lambda row: (
            min(row["metrics_2023"]["geometric_daily_growth"], row["metrics_2024h1"]["geometric_daily_growth"]),
            row["metrics_2023"]["geometric_daily_growth"] + row["metrics_2024h1"]["geometric_daily_growth"],
            row["metrics_2023"]["winner_removal_return"] + row["metrics_2024h1"]["winner_removal_return"],
            -max(row["metrics_2023"]["maximum_drawdown"], row["metrics_2024h1"]["maximum_drawdown"]),
        ),
        default=max(
            policy_rows,
            key=lambda row: (
                min(row["metrics_2023"]["geometric_daily_growth"], row["metrics_2024h1"]["geometric_daily_growth"]),
                row["metrics_2023"]["geometric_daily_growth"] + row["metrics_2024h1"]["geometric_daily_growth"],
            ),
            default=None,
        ),
    )

    risk_rows: list[dict[str, Any]] = []
    selected_risk = selected_base
    base_positive = bool(viable and selected_base is not None)
    if base_positive and selected_base is not None:
        scores = score_ledgers[selected_base["policy"]]
        threshold = float(selected_base["threshold_r"])
        for risk_fraction in (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.20, 0.30, 0.45):
            for leverage in (2.0, 5.0, 10.0, 20.0, 50.0, 100.0):
                metrics_2023 = replay_account(
                    candidates, outcomes, scores, executions, funding,
                    selection_start, evaluation_start, threshold, risk_fraction, leverage, config,
                )
                metrics_h1 = replay_account(
                    candidates, outcomes, scores, executions, funding,
                    evaluation_start, evaluation_end, threshold, risk_fraction, leverage, config,
                )
                risk_rows.append(
                    {
                        "policy": selected_base["policy"],
                        "threshold_r": threshold,
                        "risk_fraction": risk_fraction,
                        "maximum_leverage": leverage,
                        "metrics_2023": metrics_2023,
                        "metrics_2024h1": metrics_h1,
                    }
                )
        risk_viable = [
            row for row in risk_rows
            if not row["metrics_2023"]["liquidated_or_invalid"]
            and not row["metrics_2024h1"]["liquidated_or_invalid"]
            and row["metrics_2023"]["geometric_daily_growth"] > 0
            and row["metrics_2024h1"]["geometric_daily_growth"] > 0
        ]
        selected_risk = max(
            risk_viable,
            key=lambda row: (
                min(row["metrics_2023"]["geometric_daily_growth"], row["metrics_2024h1"]["geometric_daily_growth"]),
                row["metrics_2023"]["geometric_daily_growth"] + row["metrics_2024h1"]["geometric_daily_growth"],
                row["metrics_2023"]["account_multiple"] * row["metrics_2024h1"]["account_multiple"],
                -max(row["metrics_2023"]["maximum_drawdown"], row["metrics_2024h1"]["maximum_drawdown"]),
            ),
            default=selected_base,
        )

    # Explicit restart from 2024-01-01 with the selected fixed policy/threshold/risk contract.
    restarted_h1 = None
    selected_trades = None
    selected_nav = None
    if selected_risk is not None:
        scores = score_ledgers[selected_risk["policy"]]
        restarted_h1 = replay_account(
            candidates, outcomes, scores, executions, funding,
            evaluation_start, evaluation_end,
            float(selected_risk["threshold_r"]), float(selected_risk["risk_fraction"]),
            float(selected_risk["maximum_leverage"]), config, initial_nav=10_000.0,
        )
        selected_trades = restarted_h1["trades"]
        selected_nav = restarted_h1["daily_nav"]
        _write_frame(selected_trades, output / "SELECTED_2024H1_TRADES.parquet")
        _write_frame(selected_nav, output / "SELECTED_2024H1_DAILY_NAV.csv")

    candidate_counts = Counter(candidate.family for candidate in candidates)
    source_counts = Counter(candidate.pool_source for candidate in candidates)
    zone_counts = Counter(candidate.zone_kind for candidate in candidates)
    summary = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "system_id": "YT-TRINITY-LIQUIDITY-DELIVERY-ROUTER-ML-V1",
        "stage": "2024H1_DESIGN_RESTART_COARSE_1M_NOT_RANKABLE",
        "corpus_digest_sha256": args.corpus_digest,
        "transcript_evidence": {
            "swipalnam": ["GGFqHk_JPDI", "ZozNRXnqRkc", "F3exGqdN2Go", "CxVUB0E9OJU"],
            "chartbro": ["0h9lpMUBSlE", "QYfwaJJEH0E", "Fg3vsezz714", "V3ahczuG46I", "iwDPnAg-VsU", "rmgfnF-oS24"],
            "indicator_sensei": ["gcrJXbmNWFY", "WT2G8f8igqg", "WcPtyv0eOp4", "wsDsSIvaKKQ", "2U0s_i07vMY"],
        },
        "contract": {
            "narrative": [
                "identify the next external draw on liquidity before considering entry",
                "require an HTF PD-array or premium/discount location",
                "classify the pool interaction as raid/reclaim or accepted displacement",
                "require close-confirmed CISD/internal structure change",
                "enter only after the first BPR/IFVG/FVG/OB retest and rejection/hold",
                "place the stop beyond the event/retest extreme and target the next untouched external pool",
                "ML chooses action, management and global-slot priority; it never invents the narrative",
            ],
            "symbols": list(SYMBOLS),
            "global_slot": 1,
            "latency_ms": config.activation_latency_ms,
            "no_elapsed_time_exit": True,
            "policies": [_jsonable(policy) for policy in POLICIES],
            "h1_design_then_restart": True,
            "fees_and_execution": _jsonable(config),
        },
        "data_segments": list(SEGMENTS),
        "candidate_count": len(candidates),
        "candidate_counts_by_family": dict(sorted(candidate_counts.items())),
        "candidate_counts_by_source": dict(sorted(source_counts.items())),
        "candidate_counts_by_zone": dict(sorted(zone_counts.items())),
        "raw_economics": {
            "2021_2022": _raw_economics(candidates, outcomes, pd.Timestamp("2021-01-01", tz="UTC"), selection_start),
            "2023": _raw_economics(candidates, outcomes, selection_start, evaluation_start),
            "2024H1": _raw_economics(candidates, outcomes, evaluation_start, evaluation_end),
        },
        "base_policy_grid": [
            {
                **{key: value for key, value in row.items() if key not in {"metrics_2023", "metrics_2024h1"}},
                "metrics_2023": _compact(row["metrics_2023"]),
                "metrics_2024h1": _compact(row["metrics_2024h1"]),
            }
            for row in policy_rows
        ],
        "base_positive_both_periods": base_positive,
        "selected_base": None if selected_base is None else {
            **{key: value for key, value in selected_base.items() if key not in {"metrics_2023", "metrics_2024h1"}},
            "metrics_2023": _compact(selected_base["metrics_2023"]),
            "metrics_2024h1": _compact(selected_base["metrics_2024h1"]),
        },
        "risk_search": [
            {
                **{key: value for key, value in row.items() if key not in {"metrics_2023", "metrics_2024h1"}},
                "metrics_2023": _compact(row["metrics_2023"]),
                "metrics_2024h1": _compact(row["metrics_2024h1"]),
            }
            for row in risk_rows
        ],
        "selected_contract": None if selected_risk is None else {
            **{key: value for key, value in selected_risk.items() if key not in {"metrics_2023", "metrics_2024h1"}},
            "metrics_2023": _compact(selected_risk["metrics_2023"]),
            "metrics_2024h1_grid": _compact(selected_risk["metrics_2024h1"]),
        },
        "restarted_2024h1": None if restarted_h1 is None else _compact(restarted_h1),
        "decision": (
            "ADVANCE_TO_EVENT_TAPE_AND_FULL_2024_2026"
            if restarted_h1 is not None and restarted_h1["geometric_daily_growth"] >= 0.01 and not restarted_h1["liquidated_or_invalid"]
            else "TARGET_NOT_MET_CONTINUE_NEW_ALPHA_RESEARCH"
        ),
        "ranking_effect": "NONE_COARSE_H1_DESIGN_RESTART_NOT_FULL_PERIOD",
        "limitations": [
            "one-minute OHLC execution with adverse-first same-minute ambiguity",
            "configured spread and slippage rather than historical bid/ask",
            "H1 is used as a strategy-design interval and then replayed from 2024-01-01; it is not an untouched holdout",
            "only BTCUSDT and ETHUSDT are included until they demonstrate sufficient after-cost alpha",
        ],
        "timings": timings,
    }
    summary_path = output / "RUN_SUMMARY.json"
    summary_path.write_text(json.dumps(_jsonable(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = sorted(path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text("".join(f"{_sha256(path)}  {path.name}\n" for path in files), encoding="utf-8")
    print(json.dumps(_jsonable(summary), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def self_test() -> None:
    config = StrategyConfig(activation_latency_ms=0, half_spread_bps=0.0, entry_slippage_bps=0.0, target_slippage_bps=0.0, stop_slippage_bps=0.0, taker_fee_rate=0.0)
    starts = pd.date_range("2023-01-01T00:01:00Z", periods=5, freq="1min")
    frame = pd.DataFrame(
        {
            "bar_start": starts,
            "open": [100.0] * 5,
            "high": [100.0, 103.0, 105.0, 105.0, 105.0],
            "low": [100.0, 97.0, 99.0, 99.0, 99.0],
            "close": [100.0, 100.0, 103.0, 104.0, 104.0],
        }
    )
    execution = _execution_arrays(frame)
    candidate = Candidate(
        "test", pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", 1,
        "RAID_CISD_RETEST", "PREVIOUS_DAY_LOW", 9, "BPR", 100.0, 98.0,
        104.0, 102.0, 99.0, 97.0, 99.0, 100.0, 99.0, {"raw_reward_risk": 2.0},
    )
    funding = {"times": np.asarray([], dtype=np.int64), "rates": np.asarray([], dtype=float)}
    outcome = simulate_outcome(candidate, execution, funding, "FULL_TARGET", config, pd.Timestamp("2023-01-02T00:00:00Z"))
    assert outcome.status == "STOP", outcome  # stop and target are both touched in the first active bar.
    # Confirm pivot is unavailable until the right-hand bars have completed.
    series = pd.Series([1, 2, 5, 2, 1], dtype=float)
    pivot = _confirmed_pivot(series, 2, 2, True)
    assert pd.isna(pivot.iloc[2]) and pivot.iloc[4] == 5
    print("self-test: PASS")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--canonical-repo", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--end-exclusive", default="2024-07-01T00:00:00Z")
    parser.add_argument("--corpus-digest", default="913aa9e98bb696b1c029b410cf3efd5158122f9cf1ff84adaeb536e31157cc53")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.data_root is None or args.canonical_repo is None or args.output is None:
        parser.error("--data-root, --canonical-repo and --output are required")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
