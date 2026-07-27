#!/usr/bin/env python3
"""Causal SMT / opening-range BPR-CISD alpha screen.

This experiment is deliberately independent of the existing candidate generator. It
implements the compact sequence repeated across the complete YT Trinity corpus:

1. knowable session / prior-period liquidity or BTC-ETH SMT divergence;
2. a sweep and reclaim;
3. close-confirmed CISD / displacement;
4. an IFVG, BPR, FVG or order-block retest;
5. rejection entry with a local protected-swing stop;
6. either a full external-liquidity target or a 1R partial + breakeven runner.

The result is a conservative 1-minute OHLC economic screen. It is not rankable because
historical bid/ask, queue depth and exact funding are not present in the public archive.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression

try:
    from system.public_archive import load_public_archive, utc_timestamp
except ImportError:  # pragma: no cover - permits direct local self-test
    load_public_archive = None

NY = ZoneInfo("America/New_York")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
RESOLVED = {"STOP", "TARGET", "BREAKEVEN", "TP1_THEN_TARGET", "TP1_THEN_BREAKEVEN"}


@dataclass(frozen=True)
class ScreenConfig:
    decision_minutes: int = 5
    atr_window: int = 14
    sweep_buffer_atr: float = 0.025
    confirmation_body_atr: float = 0.45
    confirmation_range_atr: float = 0.75
    confirmation_close_location: float = 0.64
    confirmation_max_bars: int = 8
    retest_max_bars: int = 18
    retest_tolerance_atr: float = 0.035
    rejection_close_location: float = 0.56
    stop_buffer_atr: float = 0.035
    minimum_stop_atr: float = 0.08
    maximum_stop_atr: float = 1.25
    minimum_target_r: float = 2.0
    partial_fraction: float = 0.50
    tp1_r: float = 1.0
    activation_latency_ms: int = 500
    half_spread_bps: float = 0.25
    entry_slippage_bps: float = 2.0
    stop_slippage_bps: float = 4.0
    taker_fee_rate: float = 0.00055
    conservative_funding_rate_8h: float = 0.00010
    update_cadence_days: int = 28
    training_completion_lag_minutes: int = 15
    minimum_training_rows: int = 80
    min_samples_leaf: int = 18
    max_leaf_nodes: int = 15
    max_iter: int = 220
    learning_rate: float = 0.05
    l2_regularization: float = 2.0
    score_penalty: float = 0.35
    random_state: int = 20260727


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    decision_time: pd.Timestamp
    symbol: str
    side: int
    family: str
    source: str
    source_quality: int
    entry_reference: float
    stop_reference: float
    target_reference: float
    tp1_reference: float
    sweep_level: float
    sweep_extreme: float
    zone_lower: float
    zone_upper: float
    zone_kind: str
    features: Mapping[str, float]


@dataclass(frozen=True)
class Leg:
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
    legs: tuple[Leg, ...]


@dataclass(frozen=True)
class ModelScore:
    candidate_id: str
    decision_time: pd.Timestamp
    lower_score_r: float
    expected_r: float
    win_probability: float
    training_rows: int
    model_activated_at: pd.Timestamp


@dataclass(frozen=True)
class TradeRecord:
    candidate_id: str
    symbol: str
    side: int
    family: str
    source: str
    opened_at: pd.Timestamp
    closed_at: pd.Timestamp
    quantity: float
    entry_price: float
    net_pnl: float
    account_return: float
    net_r: float
    status: str


def _finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _jsonable(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _atr(frame: pd.DataFrame, window: int) -> pd.Series:
    previous_close = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def _resample_decision(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    raw = frame.copy()
    raw["bar_start"] = pd.to_datetime(raw["bar_start"], utc=True)
    raw = raw.set_index("bar_start", drop=False).sort_index()
    rule = f"{minutes}min"
    result = raw.resample(rule, closed="left", label="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    result = result.dropna(subset=["open", "high", "low", "close"])
    result["bar_start"] = result.index
    result["available_at"] = result.index + pd.Timedelta(minutes=minutes)
    result.index = pd.DatetimeIndex(result["available_at"])
    result.index.name = "decision_time"
    return result


def _completed_daily_levels(out: pd.DataFrame) -> None:
    starts = pd.DatetimeIndex(out["bar_start"])
    day = starts.floor("D")
    table = pd.DataFrame(
        {"day": day, "high": out["high"].to_numpy(), "low": out["low"].to_numpy()},
        index=out.index,
    )
    aggregate = table.groupby("day", sort=True).agg(high=("high", "max"), low=("low", "min"))
    prior = aggregate.shift(1)
    key = pd.Series(day, index=out.index)
    out["previous_day_high"] = key.map(prior["high"])
    out["previous_day_low"] = key.map(prior["low"])


def _completed_session_levels(out: pd.DataFrame) -> None:
    starts = pd.DatetimeIndex(out["bar_start"])
    utc_day = starts.floor("D")
    utc_hour = starts.hour + starts.minute / 60.0
    asia = (utc_hour >= 0.0) & (utc_hour < 6.0)
    asia_table = pd.DataFrame(
        {"day": utc_day[asia], "high": out.loc[asia, "high"].to_numpy(), "low": out.loc[asia, "low"].to_numpy()}
    )
    asia_agg = asia_table.groupby("day", sort=True).agg(high=("high", "max"), low=("low", "min"))
    day_key = pd.Series(utc_day, index=out.index)
    available = utc_hour >= 6.0
    out["asia_high"] = day_key.map(asia_agg["high"]).where(available)
    out["asia_low"] = day_key.map(asia_agg["low"]).where(available)

    ny = starts.tz_convert(NY)
    ny_date = pd.Index(ny.date)
    ny_minutes = ny.hour * 60 + ny.minute
    opening = (ny_minutes >= 9 * 60 + 30) & (ny_minutes < 10 * 60)
    opening_table = pd.DataFrame(
        {"date": ny_date[opening], "high": out.loc[opening, "high"].to_numpy(), "low": out.loc[opening, "low"].to_numpy()}
    )
    if opening_table.empty:
        out["ny_or_high"] = np.nan
        out["ny_or_low"] = np.nan
    else:
        opening_agg = opening_table.groupby("date", sort=True).agg(high=("high", "max"), low=("low", "min"))
        date_key = pd.Series(list(ny_date), index=out.index)
        opening_available = ny_minutes >= 10 * 60
        out["ny_or_high"] = date_key.map(opening_agg["high"]).where(opening_available)
        out["ny_or_low"] = date_key.map(opening_agg["low"]).where(opening_available)

    out["ny_minutes"] = ny_minutes.astype(float)
    out["london_killzone"] = ((ny_minutes >= 2 * 60) & (ny_minutes < 5 * 60)).astype(float)
    out["new_york_killzone"] = ((ny_minutes >= 7 * 60) & (ny_minutes < 10 * 60)).astype(float)
    out["post_or_window"] = ((ny_minutes >= 10 * 60) & (ny_minutes < 12 * 60)).astype(float)


def build_features(frame: pd.DataFrame, config: ScreenConfig) -> pd.DataFrame:
    out = _resample_decision(frame, config.decision_minutes)
    out["atr"] = _atr(out, config.atr_window)
    out["body"] = out["close"] - out["open"]
    out["body_atr"] = out["body"] / out["atr"]
    out["range_atr"] = (out["high"] - out["low"]) / out["atr"]
    out["close_location"] = (out["close"] - out["low"]) / (out["high"] - out["low"]).replace(0, np.nan)
    out["volume_log"] = np.log1p(out["volume"])
    volume_mean = out["volume_log"].rolling(96, min_periods=24).mean()
    volume_std = out["volume_log"].rolling(96, min_periods=24).std(ddof=0)
    out["volume_z"] = (out["volume_log"] - volume_mean) / volume_std.replace(0, np.nan)
    out["ema_20"] = out["close"].ewm(span=20, adjust=False, min_periods=20).mean()
    out["ema_50"] = out["close"].ewm(span=50, adjust=False, min_periods=50).mean()
    out["ema_200"] = out["close"].ewm(span=200, adjust=False, min_periods=200).mean()
    out["ema_spread_atr"] = (out["ema_20"] - out["ema_50"]) / out["atr"]
    out["ema_slope_atr"] = out["ema_20"].diff(3) / out["atr"]
    out["trend_alignment"] = np.sign(out["ema_spread_atr"]) + np.sign(out["ema_slope_atr"]) + np.sign(out["close"] - out["ema_200"])
    out["prior_high_3"] = out["high"].shift(1).rolling(3, min_periods=3).max()
    out["prior_low_3"] = out["low"].shift(1).rolling(3, min_periods=3).min()
    out["prior_high_12"] = out["high"].shift(1).rolling(12, min_periods=8).max()
    out["prior_low_12"] = out["low"].shift(1).rolling(12, min_periods=8).min()
    out["prior_high_48"] = out["high"].shift(1).rolling(48, min_periods=24).max()
    out["prior_low_48"] = out["low"].shift(1).rolling(48, min_periods=24).min()
    returns = np.log(out["close"]).diff()
    out["realized_vol_24"] = np.sqrt((returns * returns).rolling(24, min_periods=12).sum())
    bandwidth = out["close"].rolling(20, min_periods=20).std(ddof=0) / out["close"].rolling(20, min_periods=20).mean()
    out["compression_ratio"] = bandwidth / bandwidth.rolling(96, min_periods=24).median().replace(0, np.nan)

    out["bull_fvg_lower"] = out["high"].shift(2).where(out["low"] > out["high"].shift(2))
    out["bull_fvg_upper"] = out["low"].where(out["low"] > out["high"].shift(2))
    out["bear_fvg_lower"] = out["high"].where(out["high"] < out["low"].shift(2))
    out["bear_fvg_upper"] = out["low"].shift(2).where(out["high"] < out["low"].shift(2))
    _completed_daily_levels(out)
    _completed_session_levels(out)
    return out


LEVEL_SOURCES: tuple[tuple[str, str, int], ...] = (
    ("previous_day_high", "previous_day_low", 7),
    ("ny_or_high", "ny_or_low", 7),
    ("asia_high", "asia_low", 6),
    ("prior_high_48", "prior_low_48", 5),
    ("prior_high_12", "prior_low_12", 3),
)


def _session_allowed(row: pd.Series, source: str) -> bool:
    if source.startswith("ASIA"):
        return bool(row.get("london_killzone", 0.0) > 0 or row.get("new_york_killzone", 0.0) > 0)
    if source.startswith("NY_OR"):
        return bool(row.get("post_or_window", 0.0) > 0)
    if source.startswith("PREVIOUS_DAY"):
        return bool(row.get("london_killzone", 0.0) > 0 or row.get("new_york_killzone", 0.0) > 0)
    return bool(row.get("london_killzone", 0.0) > 0 or row.get("new_york_killzone", 0.0) > 0 or row.get("post_or_window", 0.0) > 0)


def _source_name(column: str, side: int) -> str:
    name = column.replace("_high", "").replace("_low", "").upper()
    return f"{name}_{'LOW' if side > 0 else 'HIGH'}"


def _external_sweep(row: pd.Series, side: int, atr: float, config: ScreenConfig) -> tuple[float, str, int, float] | None:
    choices: list[tuple[int, float, str, float, float]] = []
    buffer = config.sweep_buffer_atr * atr
    for high_column, low_column, quality in LEVEL_SOURCES:
        column = low_column if side > 0 else high_column
        value = row.get(column)
        if not _finite(value):
            continue
        level = float(value)
        source = _source_name(column, side)
        if not _session_allowed(row, source):
            continue
        if side > 0:
            swept = float(row["low"]) < level - buffer and float(row["close"]) > level
            depth = (level - float(row["low"])) / atr
        else:
            swept = float(row["high"]) > level + buffer and float(row["close"]) < level
            depth = (float(row["high"]) - level) / atr
        if swept:
            choices.append((quality, -abs(float(row["close"]) - level), source, depth, level))
    if not choices:
        return None
    quality, _, source, depth, level = max(choices)
    return float(level), source, int(quality), float(depth)


def _smt_divergence(row: pd.Series, side: int, atr: float) -> tuple[bool, float]:
    if side > 0:
        own_level = row.get("prior_low_12")
        other_level = row.get("other_prior_low_12")
        if not (_finite(own_level) and _finite(other_level) and _finite(row.get("other_low"))):
            return False, 0.0
        own_break = (float(own_level) - float(row["low"])) / atr
        other_atr = max(float(row.get("other_atr", 1.0)), 1e-12)
        other_break = (float(other_level) - float(row["other_low"])) / other_atr
    else:
        own_level = row.get("prior_high_12")
        other_level = row.get("other_prior_high_12")
        if not (_finite(own_level) and _finite(other_level) and _finite(row.get("other_high"))):
            return False, 0.0
        own_break = (float(row["high"]) - float(own_level)) / atr
        other_atr = max(float(row.get("other_atr", 1.0)), 1e-12)
        other_break = (float(row["other_high"]) - float(other_level)) / other_atr
    divergence = own_break - max(other_break, 0.0)
    return bool(own_break > 0.02 and other_break <= 0.0), float(divergence)


def _last_opposite_fvg(features: pd.DataFrame, start: int, end: int, side: int) -> tuple[float, float] | None:
    segment = features.iloc[max(2, start):end]
    if side > 0:
        usable = segment[segment["bear_fvg_lower"].notna() & segment["bear_fvg_upper"].notna()]
        columns = ("bear_fvg_lower", "bear_fvg_upper")
    else:
        usable = segment[segment["bull_fvg_lower"].notna() & segment["bull_fvg_upper"].notna()]
        columns = ("bull_fvg_lower", "bull_fvg_upper")
    if usable.empty:
        return None
    row = usable.iloc[-1]
    lower, upper = sorted((float(row[columns[0]]), float(row[columns[1]])))
    return (lower, upper) if upper > lower else None


def _same_direction_fvg(row: pd.Series, side: int) -> tuple[float, float] | None:
    if side > 0 and _finite(row.get("bull_fvg_lower")) and _finite(row.get("bull_fvg_upper")):
        values = (float(row["bull_fvg_lower"]), float(row["bull_fvg_upper"]))
    elif side < 0 and _finite(row.get("bear_fvg_lower")) and _finite(row.get("bear_fvg_upper")):
        values = (float(row["bear_fvg_lower"]), float(row["bear_fvg_upper"]))
    else:
        return None
    lower, upper = sorted(values)
    return (lower, upper) if upper > lower else None


def _order_block(features: pd.DataFrame, start: int, end: int, side: int) -> tuple[float, float] | None:
    segment = features.iloc[max(0, start):end]
    opposite = segment[segment["close"] < segment["open"]] if side > 0 else segment[segment["close"] > segment["open"]]
    if opposite.empty:
        return None
    row = opposite.iloc[-1]
    lower, upper = sorted((float(row["open"]), float(row["close"])))
    return (lower, upper) if upper > lower else None


def _choose_zone(features: pd.DataFrame, sweep_pos: int, confirm_pos: int, side: int, atr: float) -> tuple[float, float, str] | None:
    row = features.iloc[confirm_pos]
    same = _same_direction_fvg(row, side)
    opposite = _last_opposite_fvg(features, sweep_pos - 12, confirm_pos + 1, side)
    ob = _order_block(features, sweep_pos - 6, confirm_pos, side)

    inverted: tuple[float, float] | None = None
    if opposite is not None:
        if side > 0 and float(row["close"]) > opposite[1]:
            inverted = opposite
        if side < 0 and float(row["close"]) < opposite[0]:
            inverted = opposite
    if same is not None and inverted is not None:
        overlap = (max(same[0], inverted[0]), min(same[1], inverted[1]))
        if overlap[1] > overlap[0]:
            zone = overlap
            kind = "BPR"
        else:
            zone = inverted
            kind = "IFVG"
    elif inverted is not None:
        zone = inverted
        kind = "IFVG"
    elif same is not None and ob is not None:
        overlap = (max(same[0], ob[0]), min(same[1], ob[1]))
        if overlap[1] > overlap[0]:
            zone = overlap
            kind = "UNICORN"
        else:
            zone = same
            kind = "FVG"
    elif same is not None:
        zone = same
        kind = "FVG"
    elif ob is not None:
        zone = ob
        kind = "OB"
    else:
        return None

    lower, upper = zone
    width_atr = (upper - lower) / max(atr, 1e-12)
    if not 0.015 <= width_atr <= 0.85:
        return None
    if side > 0 and upper >= float(row["close"]):
        return None
    if side < 0 and lower <= float(row["close"]):
        return None
    return lower, upper, kind


def _target_levels(row: pd.Series, side: int, sweep_bar: pd.Series) -> list[tuple[float, int, str]]:
    result: list[tuple[float, int, str]] = []
    for high_column, low_column, quality in LEVEL_SOURCES:
        column = high_column if side > 0 else low_column
        value = row.get(column)
        if _finite(value):
            result.append((float(value), quality, column.upper()))
    result.append((float(sweep_bar["high"] if side > 0 else sweep_bar["low"]), 4, "SWEEP_BAR_OPPOSITE"))
    return result


def _select_target(levels: Iterable[tuple[float, int, str]], side: int, entry: float, stop: float, minimum_r: float) -> tuple[float, int, str] | None:
    risk = abs(entry - stop)
    valid: list[tuple[float, int, str, float]] = []
    for price, quality, name in levels:
        distance = side * (price - entry)
        if distance <= 0:
            continue
        reward_risk = distance / max(risk, 1e-12)
        if reward_risk >= minimum_r:
            valid.append((price, quality, name, reward_risk))
    if not valid:
        return None
    if side > 0:
        return min(valid, key=lambda item: (item[0], -item[1]))[:3]
    return max(valid, key=lambda item: (item[0], item[1]))[:3]


def _feature_row(
    row: pd.Series,
    sweep_row: pd.Series,
    confirm_row: pd.Series,
    side: int,
    family: str,
    source: str,
    source_quality: int,
    sweep_depth: float,
    smt: bool,
    smt_divergence: float,
    zone_kind: str,
    zone_lower: float,
    zone_upper: float,
    retest_extreme: float,
    sweep_pos: int,
    confirm_pos: int,
    entry_pos: int,
    entry: float,
    stop: float,
    target: float,
) -> dict[str, float]:
    atr = float(row["atr"])
    zone_width = (zone_upper - zone_lower) / atr
    stop_distance = abs(entry - stop)
    target_distance = abs(target - entry)
    ny_minutes = float(row.get("ny_minutes", 0.0))
    features = {
        "side": float(side),
        "symbol_btc": float(str(row.get("symbol")) == "BTCUSDT"),
        "family_smt": float(family == "SMT_CISD_BPR"),
        "family_session": float(family == "SESSION_OR_CISD_BPR"),
        "source_quality": float(source_quality),
        "source_previous_day": float(source.startswith("PREVIOUS_DAY")),
        "source_asia": float(source.startswith("ASIA")),
        "source_ny_or": float(source.startswith("NY_OR")),
        "source_4h": float(source.startswith("PRIOR_48")),
        "sweep_depth_atr": float(sweep_depth),
        "smt": float(smt),
        "smt_divergence_atr": float(smt_divergence),
        "sweep_reclaim_atr": side * (float(sweep_row["close"]) - float(sweep_row["low"] if side > 0 else sweep_row["high"])) / atr,
        "confirmation_body_atr": side * float(confirm_row.get("body_atr", 0.0)),
        "confirmation_range_atr": float(confirm_row.get("range_atr", 0.0)),
        "confirmation_efficiency": abs(float(confirm_row.get("body_atr", 0.0))) / max(float(confirm_row.get("range_atr", 0.0)), 1e-12),
        "confirmation_volume_z": float(confirm_row.get("volume_z", 0.0)) if _finite(confirm_row.get("volume_z")) else 0.0,
        "zone_bpr": float(zone_kind == "BPR"),
        "zone_ifvg": float(zone_kind == "IFVG"),
        "zone_unicorn": float(zone_kind == "UNICORN"),
        "zone_fvg": float(zone_kind == "FVG"),
        "zone_ob": float(zone_kind == "OB"),
        "zone_width_atr": float(zone_width),
        "retest_depth_atr": side * (entry - retest_extreme) / atr,
        "confirmation_wait_bars": float(confirm_pos - sweep_pos),
        "retest_wait_bars": float(entry_pos - confirm_pos),
        "stop_distance_atr": stop_distance / atr,
        "target_distance_atr": target_distance / atr,
        "raw_reward_risk": target_distance / max(stop_distance, 1e-12),
        "trend_alignment": side * (float(row.get("trend_alignment", 0.0)) if _finite(row.get("trend_alignment")) else 0.0),
        "ema_spread_atr": side * (float(row.get("ema_spread_atr", 0.0)) if _finite(row.get("ema_spread_atr")) else 0.0),
        "compression_ratio": float(row.get("compression_ratio", 1.0)) if _finite(row.get("compression_ratio")) else 1.0,
        "realized_vol_24": float(row.get("realized_vol_24", 0.0)) if _finite(row.get("realized_vol_24")) else 0.0,
        "entry_volume_z": float(row.get("volume_z", 0.0)) if _finite(row.get("volume_z")) else 0.0,
        "london_killzone": float(row.get("london_killzone", 0.0)),
        "new_york_killzone": float(row.get("new_york_killzone", 0.0)),
        "post_or_window": float(row.get("post_or_window", 0.0)),
        "ny_time_sin": math.sin(2 * math.pi * ny_minutes / 1440.0),
        "ny_time_cos": math.cos(2 * math.pi * ny_minutes / 1440.0),
        "other_return_divergence": side * (
            float(row.get("return_12", 0.0)) - float(row.get("other_return_12", 0.0))
        ),
    }
    return {key: float(value) for key, value in features.items() if np.isfinite(value)}


def generate_candidates(features_by_symbol: Mapping[str, pd.DataFrame], config: ScreenConfig) -> list[Candidate]:
    prepared: dict[str, pd.DataFrame] = {}
    for symbol, frame in features_by_symbol.items():
        other = next(name for name in SYMBOLS if name != symbol)
        other_frame = features_by_symbol[other]
        joined = frame.copy()
        joined["symbol"] = symbol
        joined["return_12"] = np.log(joined["close"] / joined["close"].shift(12))
        for column in ("high", "low", "atr", "prior_high_12", "prior_low_12", "close"):
            joined[f"other_{column}"] = other_frame[column].reindex(joined.index)
        joined["other_return_12"] = np.log(joined["other_close"] / joined["other_close"].shift(12))
        prepared[symbol] = joined

    candidates: list[Candidate] = []
    recent_keys: dict[tuple[str, int, str], int] = {}
    for symbol, features in sorted(prepared.items()):
        for sweep_pos in range(50, len(features) - config.confirmation_max_bars - config.retest_max_bars - 4):
            sweep_row = features.iloc[sweep_pos]
            if not _finite(sweep_row.get("atr")) or float(sweep_row["atr"]) <= 0:
                continue
            atr = float(sweep_row["atr"])
            for side in (1, -1):
                sweep = _external_sweep(sweep_row, side, atr, config)
                smt, smt_divergence = _smt_divergence(sweep_row, side, atr)
                if smt and not bool(sweep_row.get("london_killzone", 0.0) > 0 or sweep_row.get("new_york_killzone", 0.0) > 0 or sweep_row.get("post_or_window", 0.0) > 0):
                    smt = False
                if sweep is None and not smt:
                    continue
                if sweep is None:
                    level = float(sweep_row["prior_low_12"] if side > 0 else sweep_row["prior_high_12"])
                    source = "SMT_INTERNAL_LOW" if side > 0 else "SMT_INTERNAL_HIGH"
                    quality = 4
                    depth = smt_divergence
                else:
                    level, source, quality, depth = sweep
                family = "SMT_CISD_BPR" if smt else "SESSION_OR_CISD_BPR"
                key = (symbol, side, source)
                if sweep_pos - recent_keys.get(key, -10_000) < 6:
                    continue
                internal_break = sweep_row.get("prior_high_3" if side > 0 else "prior_low_3")
                if not _finite(internal_break):
                    continue

                confirm_pos: int | None = None
                zone: tuple[float, float, str] | None = None
                for position in range(sweep_pos + 1, min(len(features), sweep_pos + 1 + config.confirmation_max_bars)):
                    row = features.iloc[position]
                    if not _finite(row.get("atr")):
                        continue
                    body = side * float(row.get("body_atr", 0.0))
                    range_atr = float(row.get("range_atr", 0.0))
                    location = float(row.get("close_location", 0.5))
                    location_ok = location >= config.confirmation_close_location if side > 0 else location <= 1 - config.confirmation_close_location
                    structure_ok = float(row["close"]) > float(internal_break) if side > 0 else float(row["close"]) < float(internal_break)
                    if body < config.confirmation_body_atr or range_atr < config.confirmation_range_atr or not location_ok or not structure_ok:
                        continue
                    candidate_zone = _choose_zone(features, sweep_pos, position, side, float(row["atr"]))
                    if candidate_zone is None:
                        continue
                    confirm_pos = position
                    zone = candidate_zone
                    break
                if confirm_pos is None or zone is None:
                    continue

                zone_lower, zone_upper, zone_kind = zone
                retest_pos: int | None = None
                entry_pos: int | None = None
                retest_extreme: float | None = None
                for position in range(confirm_pos + 1, min(len(features), confirm_pos + 1 + config.retest_max_bars)):
                    row = features.iloc[position]
                    row_atr = float(row["atr"]) if _finite(row.get("atr")) else atr
                    tolerance = config.retest_tolerance_atr * row_atr
                    # Overall sweep invalidation before a trade exists.
                    if side > 0 and float(row["low"]) < float(sweep_row["low"]) - config.stop_buffer_atr * row_atr:
                        break
                    if side < 0 and float(row["high"]) > float(sweep_row["high"]) + config.stop_buffer_atr * row_atr:
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
                        retest_row = features.iloc[retest_pos]
                        body = side * float(row.get("body_atr", 0.0))
                        later = (
                            float(row["close"]) > float(retest_row["high"]) and body > 0
                            if side > 0
                            else float(row["close"]) < float(retest_row["low"]) and body > 0
                        )
                        if later:
                            entry_pos = position
                            break
                if entry_pos is None or retest_extreme is None:
                    continue

                row = features.iloc[entry_pos]
                entry = float(row["close"])
                row_atr = float(row["atr"])
                stop = (
                    min(float(retest_extreme), zone_lower) - config.stop_buffer_atr * row_atr
                    if side > 0
                    else max(float(retest_extreme), zone_upper) + config.stop_buffer_atr * row_atr
                )
                stop_atr = abs(entry - stop) / row_atr
                if not config.minimum_stop_atr <= stop_atr <= config.maximum_stop_atr:
                    continue
                target = _select_target(
                    _target_levels(row, side, sweep_row),
                    side,
                    entry,
                    stop,
                    config.minimum_target_r,
                )
                if target is None:
                    continue
                target_price, _, _ = target
                if side * (target_price - entry) <= 0:
                    continue
                tp1 = entry + side * config.tp1_r * abs(entry - stop)
                decision_time = pd.Timestamp(features.index[entry_pos])
                digest = sha256(
                    f"{symbol}|{decision_time.isoformat()}|{side}|{family}|{source}|{entry:.12g}|{stop:.12g}|{target_price:.12g}".encode()
                ).hexdigest()[:20]
                candidate = Candidate(
                    candidate_id=digest,
                    decision_time=decision_time,
                    symbol=symbol,
                    side=side,
                    family=family,
                    source=source,
                    source_quality=quality,
                    entry_reference=entry,
                    stop_reference=stop,
                    target_reference=float(target_price),
                    tp1_reference=float(tp1),
                    sweep_level=float(level),
                    sweep_extreme=float(sweep_row["low"] if side > 0 else sweep_row["high"]),
                    zone_lower=float(zone_lower),
                    zone_upper=float(zone_upper),
                    zone_kind=zone_kind,
                    features=_feature_row(
                        row,
                        sweep_row,
                        features.iloc[confirm_pos],
                        side,
                        family,
                        source,
                        quality,
                        depth,
                        smt,
                        smt_divergence,
                        zone_kind,
                        zone_lower,
                        zone_upper,
                        float(retest_extreme),
                        sweep_pos,
                        confirm_pos,
                        entry_pos,
                        entry,
                        stop,
                        float(target_price),
                    ),
                )
                candidates.append(candidate)
                recent_keys[key] = sweep_pos
    candidates.sort(key=lambda item: (item.decision_time, item.symbol, item.side, item.candidate_id))
    deduped: dict[tuple[pd.Timestamp, str, int], Candidate] = {}
    for candidate in candidates:
        key = (candidate.decision_time, candidate.symbol, candidate.side)
        existing = deduped.get(key)
        if existing is None or candidate.features.get("raw_reward_risk", 0.0) > existing.features.get("raw_reward_risk", 0.0):
            deduped[key] = candidate
    return sorted(deduped.values(), key=lambda item: (item.decision_time, item.symbol, item.side))


def _execution_arrays(frame: pd.DataFrame) -> dict[str, Any]:
    data = frame.copy()
    data["bar_start"] = pd.to_datetime(data["bar_start"], utc=True)
    data = data.sort_values("bar_start", kind="stable")
    return {
        "frame": data,
        "times": pd.DatetimeIndex(data["bar_start"]).as_unit("ns").asi8,
        "open": data["open"].to_numpy(float),
        "high": data["high"].to_numpy(float),
        "low": data["low"].to_numpy(float),
        "close": data["close"].to_numpy(float),
    }


def simulate_outcome(
    candidate: Candidate,
    execution: Mapping[str, Any],
    management: str,
    config: ScreenConfig,
    end_exclusive: pd.Timestamp,
) -> Outcome:
    activation = candidate.decision_time + pd.Timedelta(milliseconds=config.activation_latency_ms)
    position = int(np.searchsorted(execution["times"], activation.value, side="right"))
    if position >= len(execution["open"]):
        return Outcome(candidate.candidate_id, management, "NO_EXECUTION_BAR", None, None, None, None, None, None, None, None, None, ())
    times = pd.DatetimeIndex(pd.to_datetime(execution["frame"]["bar_start"], utc=True))
    if times[position] >= end_exclusive:
        return Outcome(candidate.candidate_id, management, "NO_EXECUTION_BAR", None, None, None, None, None, None, None, None, None, ())
    cost_fraction = (config.half_spread_bps + config.entry_slippage_bps) / 10_000.0
    entry = float(execution["open"][position]) * (1 + candidate.side * cost_fraction)
    stop = float(candidate.stop_reference)
    target = float(candidate.target_reference)
    if candidate.side * (entry - stop) <= 0 or candidate.side * (target - entry) <= 0:
        return Outcome(candidate.candidate_id, management, "INVALID_ENTRY_GEOMETRY", times[position], times[position], entry, stop, target, None, None, None, 0.0, ())
    risk_distance = abs(entry - stop)
    tp1 = entry + candidate.side * config.tp1_r * risk_distance
    if candidate.side * (target - tp1) <= 0:
        return Outcome(candidate.candidate_id, management, "TARGET_BELOW_TP1", times[position], times[position], entry, stop, target, None, None, None, 0.0, ())

    stop_fill = stop * (1 - config.stop_slippage_bps / 10_000.0 if candidate.side > 0 else 1 + config.stop_slippage_bps / 10_000.0)
    planned_loss = (
        risk_distance
        + entry * config.taker_fee_rate
        + stop_fill * config.taker_fee_rate
        + entry * config.conservative_funding_rate_8h
    )
    legs: list[Leg] = []
    remaining = 1.0
    tp1_done = False
    breakeven = entry
    status = "OPEN"
    exit_time: pd.Timestamp | None = None

    for index in range(position, len(execution["open"])):
        timestamp = times[index]
        if timestamp >= end_exclusive:
            break
        high = float(execution["high"][index])
        low = float(execution["low"][index])
        active_stop = breakeven if tp1_done and management == "SCALE_BE" else stop
        stop_hit = low <= active_stop if candidate.side > 0 else high >= active_stop
        target_hit = high >= target if candidate.side > 0 else low <= target
        tp1_hit = high >= tp1 if candidate.side > 0 else low <= tp1

        if stop_hit:
            if tp1_done and management == "SCALE_BE":
                price = breakeven * (1 - config.stop_slippage_bps / 10_000.0 if candidate.side > 0 else 1 + config.stop_slippage_bps / 10_000.0)
                status = "TP1_THEN_BREAKEVEN"
            else:
                price = stop_fill
                status = "STOP"
            legs.append(Leg(timestamp, remaining, price, config.taker_fee_rate, status))
            remaining = 0.0
            exit_time = timestamp
            break

        if management == "SCALE_BE" and not tp1_done and tp1_hit:
            fraction = min(config.partial_fraction, remaining)
            legs.append(Leg(timestamp, fraction, tp1, config.taker_fee_rate, "TP1"))
            remaining -= fraction
            tp1_done = True
            # Same-minute TP2 is not credited; the remaining target must survive to a later bar.
            continue

        if target_hit:
            legs.append(Leg(timestamp, remaining, target, config.taker_fee_rate, "TARGET"))
            remaining = 0.0
            exit_time = timestamp
            status = "TP1_THEN_TARGET" if tp1_done else "TARGET"
            break

    if exit_time is None:
        status = "OPEN"
        exit_time = end_exclusive
        final_index = int(np.searchsorted(execution["times"], (end_exclusive - pd.Timedelta(nanoseconds=1)).value, side="right")) - 1
        if final_index >= position:
            closeout = float(execution["close"][final_index]) * (
                1 - candidate.side * (config.half_spread_bps + config.stop_slippage_bps) / 10_000.0
            )
            legs.append(Leg(end_exclusive, remaining, closeout, config.taker_fee_rate, "MARK_TO_MARKET"))
            remaining = 0.0

    entry_fee = entry * config.taker_fee_rate
    gross = sum(leg.fraction * candidate.side * (leg.price - entry) for leg in legs)
    exit_fees = sum(leg.fraction * leg.price * leg.fee_rate for leg in legs)
    hold_hours = max(0.0, (pd.Timestamp(exit_time) - times[position]).total_seconds() / 3600.0)
    funding_events = int(hold_hours // 8.0)
    funding_cost = funding_events * entry * config.conservative_funding_rate_8h
    unit_pnl = gross - entry_fee - exit_fees - funding_cost
    net_r = unit_pnl / max(planned_loss, 1e-12)
    return Outcome(
        candidate.candidate_id,
        management,
        status,
        times[position],
        pd.Timestamp(exit_time),
        entry,
        stop,
        target,
        planned_loss,
        unit_pnl,
        net_r,
        hold_hours * 60.0,
        tuple(legs),
    )


def _candidate_matrix(candidates: Sequence[Candidate], feature_names: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame([{name: candidate.features.get(name, np.nan) for name in feature_names} for candidate in candidates])


class ActionModel:
    def __init__(self, config: ScreenConfig) -> None:
        self.config = config
        self.features: list[str] = []
        self.regressor = HistGradientBoostingRegressor(
            learning_rate=config.learning_rate,
            max_leaf_nodes=config.max_leaf_nodes,
            max_iter=config.max_iter,
            min_samples_leaf=config.min_samples_leaf,
            l2_regularization=config.l2_regularization,
            random_state=config.random_state,
            loss="absolute_error",
        )
        self.classifier = HistGradientBoostingClassifier(
            learning_rate=config.learning_rate,
            max_leaf_nodes=config.max_leaf_nodes,
            max_iter=config.max_iter,
            min_samples_leaf=config.min_samples_leaf,
            l2_regularization=config.l2_regularization,
            random_state=config.random_state,
        )
        self.calibrator = IsotonicRegression(out_of_bounds="clip")
        self.calibrated = False
        self.winner = 1.0
        self.loser = -1.0

    def fit(self, candidates: Sequence[Candidate], outcomes: Sequence[Outcome]) -> "ActionModel":
        rows = []
        for candidate, outcome in zip(candidates, outcomes, strict=True):
            if outcome.net_r is None or not np.isfinite(outcome.net_r) or outcome.status == "OPEN":
                continue
            row = dict(candidate.features)
            row["net_r"] = float(outcome.net_r)
            row["positive"] = int(outcome.net_r > 0)
            row["decision_time"] = candidate.decision_time
            rows.append(row)
        data = pd.DataFrame(rows).sort_values("decision_time", kind="stable").reset_index(drop=True)
        if len(data) < self.config.minimum_training_rows:
            raise ValueError("insufficient training rows")
        self.features = sorted(
            column for column in data.columns
            if column not in {"net_r", "positive", "decision_time"} and pd.api.types.is_numeric_dtype(data[column])
        )
        split = max(self.config.minimum_training_rows // 2, int(len(data) * 0.8))
        split = min(split, len(data) - 2)
        base = data.iloc[:split]
        calibration = data.iloc[split:]
        x_base = base[self.features].replace([np.inf, -np.inf], np.nan)
        self.regressor.fit(x_base, base["net_r"])
        self.classifier.fit(x_base, base["positive"])
        probabilities = self.classifier.predict_proba(calibration[self.features].replace([np.inf, -np.inf], np.nan))
        classes = list(self.classifier.classes_)
        if 1 in classes and calibration["positive"].nunique() > 1:
            raw = probabilities[:, classes.index(1)]
            self.calibrator.fit(raw, calibration["positive"].to_numpy())
            self.calibrated = True
        wins = base.loc[base["net_r"] > 0, "net_r"]
        losses = base.loc[base["net_r"] <= 0, "net_r"]
        self.winner = float(wins.median()) if not wins.empty else 1.0
        self.loser = float(losses.median()) if not losses.empty else -1.0
        return self

    def score(self, candidates: Sequence[Candidate]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x_values = _candidate_matrix(candidates, self.features).replace([np.inf, -np.inf], np.nan)
        predicted_r = self.regressor.predict(x_values)
        probabilities = self.classifier.predict_proba(x_values)
        classes = list(self.classifier.classes_)
        raw_p = probabilities[:, classes.index(1)] if 1 in classes else np.zeros(len(candidates))
        p = self.calibrator.predict(raw_p) if self.calibrated else raw_p
        expected_p = p * self.winner + (1 - p) * self.loser
        disagreement = np.abs(predicted_r - expected_p)
        uncertainty = np.sqrt(np.maximum(p * (1 - p), 0.0))
        lower = np.minimum(predicted_r, expected_p) - self.config.score_penalty * (disagreement + uncertainty)
        return lower.astype(float), predicted_r.astype(float), p.astype(float)


def walk_forward_scores(
    candidates: Sequence[Candidate],
    outcomes: Mapping[str, Outcome],
    evaluation_start: pd.Timestamp,
    evaluation_end: pd.Timestamp,
    config: ScreenConfig,
) -> dict[str, ModelScore]:
    ordered = sorted(candidates, key=lambda item: item.decision_time)
    update_starts = list(pd.date_range(evaluation_start.floor("D"), evaluation_end, freq=pd.Timedelta(days=config.update_cadence_days), tz="UTC"))
    update_index = 0
    active: ActionModel | None = None
    active_rows = 0
    active_at = evaluation_start
    pending: tuple[pd.Timestamp, ActionModel, int] | None = None
    scores: dict[str, ModelScore] = {}

    def train(update_start: pd.Timestamp) -> tuple[pd.Timestamp, ActionModel, int] | None:
        training_candidates: list[Candidate] = []
        training_outcomes: list[Outcome] = []
        for candidate in ordered:
            if candidate.decision_time >= update_start:
                break
            outcome = outcomes.get(candidate.candidate_id)
            if outcome is None or outcome.exit_time is None or outcome.exit_time > update_start or outcome.status == "OPEN":
                continue
            training_candidates.append(candidate)
            training_outcomes.append(outcome)
        if len(training_candidates) < config.minimum_training_rows:
            return None
        try:
            model = ActionModel(config).fit(training_candidates, training_outcomes)
        except (ValueError, IndexError):
            return None
        return update_start + pd.Timedelta(minutes=config.training_completion_lag_minutes), model, len(training_candidates)

    initial = train(evaluation_start - pd.Timedelta(minutes=config.training_completion_lag_minutes))
    if initial is not None:
        active_at, active, active_rows = initial
    evaluation_candidates = [candidate for candidate in ordered if evaluation_start <= candidate.decision_time < evaluation_end]
    for candidate in evaluation_candidates:
        while update_index < len(update_starts) and update_starts[update_index] <= candidate.decision_time:
            trained = train(update_starts[update_index])
            if trained is not None:
                pending = trained
            update_index += 1
        if pending is not None and pending[0] <= candidate.decision_time:
            active_at, active, active_rows = pending
            pending = None
        if active is None or candidate.decision_time < active_at:
            continue
        lower, expected, probability = active.score([candidate])
        scores[candidate.candidate_id] = ModelScore(
            candidate.candidate_id,
            candidate.decision_time,
            float(lower[0]),
            float(expected[0]),
            float(probability[0]),
            active_rows,
            active_at,
        )
    return scores


def _mark_price(execution: Mapping[str, Any], timestamp: pd.Timestamp) -> float:
    position = int(np.searchsorted(execution["times"], timestamp.value, side="right")) - 1
    position = min(max(position, 0), len(execution["close"]) - 1)
    return float(execution["close"][position])


def replay_account(
    candidates: Sequence[Candidate],
    outcomes: Mapping[str, Outcome],
    scores: Mapping[str, ModelScore],
    executions: Mapping[str, Mapping[str, Any]],
    start: pd.Timestamp,
    end: pd.Timestamp,
    threshold: float,
    risk_fraction: float,
    maximum_leverage: float,
    initial_nav: float = 10_000.0,
    config: ScreenConfig = ScreenConfig(),
) -> dict[str, Any]:
    grouped: dict[pd.Timestamp, list[Candidate]] = {}
    for candidate in candidates:
        if start <= candidate.decision_time < end and candidate.candidate_id in scores:
            grouped.setdefault(candidate.decision_time, []).append(candidate)
    cash = float(initial_nav)
    slot_release = start
    trades: list[TradeRecord] = []
    selected: list[tuple[Candidate, Outcome, float, float]] = []
    cash_events: list[tuple[pd.Timestamp, float]] = [(start, cash)]

    for decision_time in sorted(grouped):
        if decision_time < slot_release or cash <= 0:
            continue
        eligible = [candidate for candidate in grouped[decision_time] if scores[candidate.candidate_id].lower_score_r >= threshold]
        if not eligible:
            continue
        candidate = max(
            eligible,
            key=lambda item: (scores[item.candidate_id].lower_score_r, scores[item.candidate_id].expected_r, item.features.get("raw_reward_risk", 0.0)),
        )
        outcome = outcomes[candidate.candidate_id]
        if outcome.exit_time is None or pd.Timestamp(outcome.exit_time) > end:
            outcome = simulate_outcome(candidate, executions[candidate.symbol], outcome.management, config, end)
        if outcome.entry_time is None or outcome.entry_price is None or outcome.planned_unit_loss is None or outcome.unit_pnl is None:
            continue
        if outcome.entry_time >= end:
            continue
        effective_exit = min(pd.Timestamp(outcome.exit_time or end), end)
        risk_quantity = cash * risk_fraction / max(outcome.planned_unit_loss, 1e-12)
        stop_fraction = abs(outcome.entry_price - float(outcome.stop_price or candidate.stop_reference)) / outcome.entry_price
        maximum_safe_leverage = 1.0 / max(stop_fraction + 0.005 + 0.0025, 1e-12)
        leverage_quantity = cash * min(maximum_leverage, maximum_safe_leverage) / outcome.entry_price
        raw_quantity = min(risk_quantity, leverage_quantity)
        step, minimum = ((0.001, 0.001) if candidate.symbol == "BTCUSDT" else (0.01, 0.01))
        quantity = math.floor(raw_quantity / step) * step
        if quantity < minimum or quantity * outcome.entry_price < 5.0:
            continue
        entry_equity = cash
        pnl = quantity * outcome.unit_pnl
        cash += pnl
        cash_events.append((effective_exit, cash))
        trades.append(
            TradeRecord(
                candidate.candidate_id,
                candidate.symbol,
                candidate.side,
                candidate.family,
                candidate.source,
                pd.Timestamp(outcome.entry_time),
                effective_exit,
                quantity,
                outcome.entry_price,
                pnl,
                pnl / max(entry_equity, 1e-12),
                float(outcome.net_r or 0.0),
                outcome.status,
            )
        )
        selected.append((candidate, outcome, quantity, entry_equity))
        slot_release = effective_exit
        if effective_exit >= end and outcome.status == "OPEN":
            break

    daily_nav: list[tuple[pd.Timestamp, float]] = []
    peak = initial_nav
    maximum_drawdown = 0.0
    for day_end in pd.date_range(start.floor("D") + pd.Timedelta(days=1), end, freq="1D", tz="UTC"):
        nav = initial_nav
        prior = [value for timestamp, value in cash_events if timestamp <= day_end]
        if prior:
            nav = prior[-1]
        # cash already includes final marked outcome for an OPEN final trade. This screen
        # records that closeout only at evaluation end, so mark it before then.
        for candidate, outcome, quantity, entry_equity in selected:
            if outcome.entry_time is None or outcome.entry_price is None:
                continue
            if outcome.entry_time <= day_end < pd.Timestamp(outcome.exit_time or end):
                mark = _mark_price(executions[candidate.symbol], day_end)
                nav = (
                    entry_equity
                    - quantity * outcome.entry_price * config.taker_fee_rate
                    + candidate.side * quantity * (mark - outcome.entry_price)
                    - quantity * mark * config.taker_fee_rate
                )
                break
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, 1 - nav / max(peak, 1e-12))
        daily_nav.append((day_end, nav))

    end_nav = daily_nav[-1][1] if daily_nav else cash
    days = max(1, int((end - start) / pd.Timedelta(days=1)))
    geometric_daily_growth = math.exp(math.log(max(end_nav, 1e-12) / initial_nav) / days) - 1 if end_nav > 0 else -1.0
    pnls = np.asarray([trade.net_pnl for trade in trades], dtype=float)
    positive = pnls[pnls > 0]
    negative = pnls[pnls < 0]
    profit_factor = float(positive.sum() / abs(negative.sum())) if negative.size else (None if positive.size else 0.0)
    top_five_share = float(np.sort(positive)[-5:].sum() / positive.sum()) if positive.size and positive.sum() > 0 else 0.0
    winner_removed_nav = initial_nav + float(pnls.sum() - (positive.max() if positive.size else 0.0))
    return {
        "start_nav": initial_nav,
        "end_nav": float(end_nav),
        "account_multiple": float(end_nav / initial_nav),
        "total_return": float(end_nav / initial_nav - 1),
        "calendar_days": days,
        "geometric_daily_growth": float(geometric_daily_growth),
        "maximum_drawdown": float(maximum_drawdown),
        "completed_trades": len(trades),
        "win_rate": float((pnls > 0).mean()) if len(pnls) else 0.0,
        "profit_factor": profit_factor,
        "median_trade_return": float(np.median([trade.account_return for trade in trades])) if trades else 0.0,
        "top_five_positive_pnl_share": top_five_share,
        "winner_removal_return": float(winner_removed_nav / initial_nav - 1),
        "liquidated_or_invalid": bool(end_nav <= 0),
        "trades": [_jsonable(asdict(trade)) for trade in trades],
        "daily_nav": [{"day_end": timestamp.isoformat(), "nav": float(nav)} for timestamp, nav in daily_nav],
    }


def _compact_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metrics.items() if key not in {"trades", "daily_nav"}}


def _raw_economics(candidates: Sequence[Candidate], outcomes: Mapping[str, Outcome], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    rows = [outcomes[candidate.candidate_id] for candidate in candidates if start <= candidate.decision_time < end and candidate.candidate_id in outcomes]
    values = np.asarray([row.net_r for row in rows if row.net_r is not None and np.isfinite(row.net_r) and row.status != "OPEN"], dtype=float)
    return {
        "candidates": len(rows),
        "resolved": int(len(values)),
        "mean_net_r": float(values.mean()) if len(values) else None,
        "median_net_r": float(np.median(values)) if len(values) else None,
        "positive_fraction": float((values > 0).mean()) if len(values) else None,
        "sum_net_r": float(values.sum()) if len(values) else None,
        "p10": float(np.quantile(values, 0.10)) if len(values) else None,
        "p90": float(np.quantile(values, 0.90)) if len(values) else None,
    }


def _half_year_metrics(
    candidates: Sequence[Candidate],
    outcomes: Mapping[str, Outcome],
    scores: Mapping[str, ModelScore],
    executions: Mapping[str, Mapping[str, Any]],
    start: pd.Timestamp,
    end: pd.Timestamp,
    threshold: float,
    risk: float,
    leverage: float,
    config: ScreenConfig,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    cursor = start
    while cursor < end:
        half_end = min(end, pd.Timestamp(year=cursor.year, month=(7 if cursor.month <= 6 else 1), day=1, tz="UTC") if cursor.month <= 6 else pd.Timestamp(year=cursor.year + 1, month=1, day=1, tz="UTC"))
        label = f"{cursor.year}H{1 if cursor.month <= 6 else 2}"
        result[label] = _compact_metrics(replay_account(candidates, outcomes, scores, executions, cursor, half_end, threshold, risk, leverage, config=config))
        cursor = half_end
    return result


def run_screen(args: argparse.Namespace) -> int:
    if load_public_archive is None:
        raise SystemExit("system.public_archive is required for a screen run")
    config = ScreenConfig()
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    data_start = utc_timestamp(args.data_start)
    selection_start = utc_timestamp(args.selection_start)
    evaluation_start = utc_timestamp(args.evaluation_start)
    evaluation_end = utc_timestamp(args.evaluation_end_exclusive)
    if not data_start < selection_start < evaluation_start < evaluation_end:
        raise SystemExit("require data_start < selection_start < evaluation_start < evaluation_end")

    started = monotonic()
    execution_frames: dict[str, pd.DataFrame] = {}
    archive_records: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        result = load_public_archive(args.cache_root, symbol, 1, data_start, evaluation_end)
        execution_frames[symbol] = result.frame
        archive_records.extend(_jsonable(asdict(record)) for record in result.records)
    timings["archive_seconds"] = round(monotonic() - started, 3)

    started = monotonic()
    features = {symbol: build_features(frame, config) for symbol, frame in execution_frames.items()}
    candidates = generate_candidates(features, config)
    timings["feature_candidate_seconds"] = round(monotonic() - started, 3)
    executions = {symbol: _execution_arrays(frame) for symbol, frame in execution_frames.items()}

    candidate_rows = []
    for candidate in candidates:
        row = {key: _jsonable(value) for key, value in asdict(candidate).items() if key != "features"}
        row.update({f"feature__{key}": value for key, value in candidate.features.items()})
        candidate_rows.append(row)
    pd.DataFrame(candidate_rows).to_parquet(output / "CANDIDATES.parquet", index=False)

    managements = ("FULL", "SCALE_BE")
    all_outcomes: dict[str, dict[str, Outcome]] = {}
    started = monotonic()
    for management in managements:
        all_outcomes[management] = {
            candidate.candidate_id: simulate_outcome(candidate, executions[candidate.symbol], management, config, evaluation_end)
            for candidate in candidates
        }
    timings["label_seconds"] = round(monotonic() - started, 3)

    outcome_rows = []
    for management, outcomes in all_outcomes.items():
        for outcome in outcomes.values():
            row = _jsonable(asdict(outcome))
            row["legs"] = json.dumps(row["legs"], ensure_ascii=False, sort_keys=True)
            outcome_rows.append(row)
    pd.DataFrame(outcome_rows).to_parquet(output / "OUTCOMES.parquet", index=False)

    thresholds = (0.0, 0.10, 0.25, 0.50)
    pre2024_results: list[dict[str, Any]] = []
    score_ledgers: dict[str, dict[str, ModelScore]] = {}
    started = monotonic()
    for management in managements:
        scores = walk_forward_scores(candidates, all_outcomes[management], selection_start, evaluation_start, config)
        score_ledgers[management] = scores
        for threshold in thresholds:
            account = replay_account(
                candidates,
                all_outcomes[management],
                scores,
                executions,
                selection_start,
                evaluation_start,
                threshold,
                0.01,
                5.0,
                config=config,
            )
            pre2024_results.append({"management": management, "threshold_r": threshold, "risk_fraction": 0.01, "maximum_leverage": 5.0, "metrics": account})
    timings["walk_forward_selection_seconds"] = round(monotonic() - started, 3)

    viable = [row for row in pre2024_results if row["metrics"]["completed_trades"] > 0 and not row["metrics"]["liquidated_or_invalid"]]
    selected = max(
        viable,
        key=lambda row: (
            row["metrics"]["geometric_daily_growth"],
            row["metrics"]["account_multiple"],
            -row["metrics"]["maximum_drawdown"],
            row["metrics"]["completed_trades"],
        ),
        default=None,
    )
    basic_positive = bool(selected and selected["metrics"]["geometric_daily_growth"] > 0)

    risk_search: list[dict[str, Any]] = []
    risk_selected = selected
    if basic_positive and selected is not None:
        management = selected["management"]
        threshold = float(selected["threshold_r"])
        for risk_fraction in (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.20):
            for leverage in (2.0, 5.0, 10.0, 20.0, 50.0, 100.0):
                metrics = replay_account(
                    candidates,
                    all_outcomes[management],
                    score_ledgers[management],
                    executions,
                    selection_start,
                    evaluation_start,
                    threshold,
                    risk_fraction,
                    leverage,
                    config=config,
                )
                row = {"management": management, "threshold_r": threshold, "risk_fraction": risk_fraction, "maximum_leverage": leverage, "metrics": metrics}
                risk_search.append(row)
        eligible = [row for row in risk_search if not row["metrics"]["liquidated_or_invalid"] and row["metrics"]["end_nav"] > 0]
        risk_selected = max(
            eligible,
            key=lambda row: (
                row["metrics"]["geometric_daily_growth"],
                row["metrics"]["account_multiple"],
                -row["metrics"]["maximum_drawdown"],
            ),
            default=selected,
        )

    provisional_2024h1 = None
    if basic_positive and risk_selected is not None:
        management = risk_selected["management"]
        scores_2024 = walk_forward_scores(candidates, all_outcomes[management], evaluation_start, evaluation_end, config)
        provisional_2024h1 = replay_account(
            candidates,
            all_outcomes[management],
            scores_2024,
            executions,
            evaluation_start,
            evaluation_end,
            float(risk_selected["threshold_r"]),
            float(risk_selected["risk_fraction"]),
            float(risk_selected["maximum_leverage"]),
            config=config,
        )

    score_rows = []
    for management, scores in score_ledgers.items():
        for score in scores.values():
            score_rows.append({"management": management, **_jsonable(asdict(score))})
    pd.DataFrame(score_rows).to_parquet(output / "MODEL_SCORES.parquet", index=False)

    counts_by_family = Counter(candidate.family for candidate in candidates)
    counts_by_source = Counter(candidate.source for candidate in candidates)
    counts_by_symbol = Counter(candidate.symbol for candidate in candidates)
    raw = {
        management: {
            "2021": _raw_economics(candidates, all_outcomes[management], data_start, selection_start),
            "pre2024_selection": _raw_economics(candidates, all_outcomes[management], selection_start, evaluation_start),
            "2022H1": _raw_economics(candidates, all_outcomes[management], pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2022-07-01", tz="UTC")),
            "2022H2": _raw_economics(candidates, all_outcomes[management], pd.Timestamp("2022-07-01", tz="UTC"), pd.Timestamp("2023-01-01", tz="UTC")),
            "2023H1": _raw_economics(candidates, all_outcomes[management], pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2023-07-01", tz="UTC")),
            "2023H2": _raw_economics(candidates, all_outcomes[management], pd.Timestamp("2023-07-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")),
        }
        for management in managements
    }
    selected_halves = None
    if risk_selected is not None:
        management = risk_selected["management"]
        selected_halves = _half_year_metrics(
            candidates,
            all_outcomes[management],
            score_ledgers[management],
            executions,
            selection_start,
            evaluation_start,
            float(risk_selected["threshold_r"]),
            float(risk_selected["risk_fraction"]),
            float(risk_selected["maximum_leverage"]),
            config,
        )

    summary = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "system_id": "YT-TRINITY-SMT-OR-BPR-CISD-ML-V1",
        "stage": "PRE2024_CAUSAL_COARSE_1M_NOT_RANKABLE",
        "official_open_authority": False,
        "ranking_authority": False,
        "corpus_binding": json.loads(args.corpus_pointer.read_text(encoding="utf-8")) if args.corpus_pointer else None,
        "data_start": data_start.isoformat(),
        "selection_start": selection_start.isoformat(),
        "evaluation_start": evaluation_start.isoformat(),
        "evaluation_end_exclusive": evaluation_end.isoformat(),
        "symbols": list(SYMBOLS),
        "config": asdict(config),
        "candidate_count": len(candidates),
        "candidate_counts_by_symbol": dict(sorted(counts_by_symbol.items())),
        "candidate_counts_by_family": dict(sorted(counts_by_family.items())),
        "candidate_counts_by_source": dict(sorted(counts_by_source.items())),
        "raw_label_economics": raw,
        "pre2024_basic_grid": [
            {**{key: value for key, value in row.items() if key != "metrics"}, "metrics": _compact_metrics(row["metrics"])}
            for row in pre2024_results
        ],
        "selected_basic_configuration": selected,
        "positive_basic_alpha": basic_positive,
        "risk_search": [
            {**{key: value for key, value in row.items() if key != "metrics"}, "metrics": _compact_metrics(row["metrics"])}
            for row in risk_search
        ],
        "selected_configuration": risk_selected,
        "selected_half_year_metrics": selected_halves,
        "provisional_2024h1": provisional_2024h1,
        "decision": (
            "POSITIVE_COARSE_ALPHA_ADVANCE_EVENT_TAPE_AND_FUNDING"
            if basic_positive
            else "ECONOMIC_FAIL_CLOSE_SMT_OR_BPR_ROUTE_AND_SWITCH_PAYOFF"
        ),
        "limitations": [
            "one-minute OHLC replay with stop-first same-bar ambiguity",
            "configured spread and slippage rather than historical bid/ask",
            "conservative fixed funding debit rather than timestamped actual funding",
            "no queue or partial-fill model because this variant enters market after retest rejection",
            "provisional 2024H1, when present, is not an official or rankable result",
        ],
        "archive_records": archive_records,
        "timings": timings,
    }
    summary_path = output / "RUN_SUMMARY.json"
    summary_path.write_text(json.dumps(_jsonable(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = sorted(path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text("".join(f"{_sha256(path)}  {path.name}\n" for path in files), encoding="utf-8")
    print(json.dumps(_jsonable(summary), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def self_test() -> None:
    config = ScreenConfig()
    # Outcome test: stop and target on the same minute must resolve to the stop.
    starts = pd.date_range("2023-01-01T00:01:00Z", periods=4, freq="1min")
    frame = pd.DataFrame(
        {
            "bar_start": starts,
            "open": [100.0, 100.0, 100.0, 100.0],
            "high": [100.0, 103.0, 103.0, 103.0],
            "low": [100.0, 97.0, 99.0, 99.0],
            "close": [100.0, 100.0, 102.0, 102.0],
        }
    )
    execution = _execution_arrays(frame)
    candidate = Candidate(
        "test",
        pd.Timestamp("2023-01-01T00:00:00Z"),
        "BTCUSDT",
        1,
        "SMT_CISD_BPR",
        "ASIA_LOW",
        6,
        100.0,
        98.0,
        104.0,
        102.0,
        99.0,
        98.5,
        99.0,
        100.0,
        "BPR",
        {"raw_reward_risk": 1.0},
    )
    outcome = simulate_outcome(candidate, execution, "FULL", ScreenConfig(activation_latency_ms=0, entry_slippage_bps=0.0, half_spread_bps=0.0, stop_slippage_bps=0.0, taker_fee_rate=0.0, conservative_funding_rate_8h=0.0), pd.Timestamp("2023-01-02T00:00:00Z"))
    assert outcome.status == "STOP" and outcome.net_r is not None and outcome.net_r < 0

    # Scaling test: TP1 must not also credit TP2 on the same bar.
    scale = simulate_outcome(candidate, execution, "SCALE_BE", ScreenConfig(activation_latency_ms=0, entry_slippage_bps=0.0, half_spread_bps=0.0, stop_slippage_bps=0.0, taker_fee_rate=0.0, conservative_funding_rate_8h=0.0), pd.Timestamp("2023-01-02T00:00:00Z"))
    assert scale.status in {"TP1_THEN_BREAKEVEN", "TP1_THEN_TARGET", "STOP"}

    # Resampling must expose a five-minute bar only at its end.
    minute_starts = pd.date_range("2023-01-01T00:00:00Z", periods=10, freq="1min")
    minute = pd.DataFrame(
        {
            "bar_start": minute_starts,
            "open": np.arange(10, dtype=float) + 100,
            "high": np.arange(10, dtype=float) + 101,
            "low": np.arange(10, dtype=float) + 99,
            "close": np.arange(10, dtype=float) + 100.5,
            "volume": 1.0,
        }
    )
    five = _resample_decision(minute, 5)
    assert five.index[0] == pd.Timestamp("2023-01-01T00:05:00Z")
    assert five.iloc[0]["high"] == 105.0
    print("self-test: PASS")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--corpus-pointer", type=Path)
    parser.add_argument("--data-start", default="2021-01-01T00:00:00Z")
    parser.add_argument("--selection-start", default="2022-01-01T00:00:00Z")
    parser.add_argument("--evaluation-start", default="2024-01-01T00:00:00Z")
    parser.add_argument("--evaluation-end-exclusive", default="2024-07-01T00:00:00Z")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.cache_root is None or args.output is None:
        parser.error("--cache-root and --output are required")
    return run_screen(args)


if __name__ == "__main__":
    raise SystemExit(main())
