from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import floor
from typing import Mapping

import numpy as np
import pandas as pd


class EventFamily(str, Enum):
    LIQUIDITY_SWEEP_REVERSAL = "LIQUIDITY_SWEEP_REVERSAL"
    DISPLACEMENT_BREAK_RETEST_CONTINUATION = "DISPLACEMENT_BREAK_RETEST_CONTINUATION"


@dataclass(frozen=True)
class FeatureConfig:
    atr_window: int = 14
    rsi_window: int = 14
    fast_ema: int = 20
    slow_ema: int = 50
    long_ema: int = 200
    volume_window: int = 50
    pivot_left: int = 3
    pivot_right: int = 3
    equal_tolerance_atr: float = 0.12
    displacement_body_atr: float = 0.80
    sweep_buffer_atr: float = 0.03
    retest_tolerance_atr: float = 0.15


@dataclass(frozen=True)
class RiskConfig:
    risk_fraction: float
    maximum_leverage: float
    quantity_step: float
    minimum_quantity: float = 0.0
    maintenance_margin_fraction: float = 0.005
    liquidation_buffer_fraction: float = 0.0025


@dataclass(frozen=True)
class EventCandidate:
    timestamp: pd.Timestamp
    symbol: str
    family: EventFamily
    side: int
    decision_price: float
    entry_reference: float
    stop_reference: float
    target_reference: float
    structural_level: float
    feature_row: Mapping[str, float]

    @property
    def stop_distance(self) -> float:
        return abs(self.entry_reference - self.stop_reference)

    @property
    def target_distance(self) -> float:
        return abs(self.target_reference - self.entry_reference)


REQUIRED_OHLCV = ("open", "high", "low", "close", "volume")


def _require_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [name for name in REQUIRED_OHLCV if name not in frame.columns]
    if missing:
        raise ValueError(f"missing OHLCV columns: {missing}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("frame index must be a DatetimeIndex")
    if frame.index.tz is None:
        raise ValueError("frame index must be timezone aware")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("frame index must be unique and increasing")
    result = frame.copy()
    for name in REQUIRED_OHLCV:
        result[name] = pd.to_numeric(result[name], errors="coerce")
    if (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("prices must be positive")
    if (result["volume"] < 0).any():
        raise ValueError("volume must be nonnegative")
    return result


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _rsi(close: pd.Series, window: int) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(frame: pd.DataFrame, window: int) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def _confirmed_pivot(series: pd.Series, left: int, right: int, high: bool) -> pd.Series:
    """Return a pivot only when its right-side confirmation is available.

    At row t the value refers to the pivot located at t-right. No future row is
    visible to the decision at t.
    """
    width = left + right + 1
    rolling = series.rolling(width, min_periods=width)
    extreme = rolling.max() if high else rolling.min()
    candidate = series.shift(right)
    confirmed = candidate.where(candidate.eq(extreme))
    return confirmed


def _last_confirmed(series: pd.Series) -> pd.Series:
    return series.ffill()


def build_causal_features(frame: pd.DataFrame, config: FeatureConfig = FeatureConfig()) -> pd.DataFrame:
    raw = _require_frame(frame)
    out = raw.copy()
    time_basis = pd.DatetimeIndex(pd.to_datetime(raw["bar_start"], utc=True)) if "bar_start" in raw.columns else out.index
    out["atr"] = _atr(raw, config.atr_window)
    out["atr_fraction"] = out["atr"] / out["close"]
    out["body"] = out["close"] - out["open"]
    out["body_atr"] = out["body"] / out["atr"]
    out["range_atr"] = (out["high"] - out["low"]) / out["atr"]
    out["close_location"] = (out["close"] - out["low"]) / (out["high"] - out["low"]).replace(0, np.nan)

    out["ema_fast"] = _ema(out["close"], config.fast_ema)
    out["ema_slow"] = _ema(out["close"], config.slow_ema)
    out["ema_long"] = _ema(out["close"], config.long_ema)
    out["ema_fast_slope_atr"] = out["ema_fast"].diff(3) / out["atr"]
    out["ema_slow_slope_atr"] = out["ema_slow"].diff(5) / out["atr"]
    out["ema_spread_atr"] = (out["ema_fast"] - out["ema_slow"]) / out["atr"]
    out["rsi"] = _rsi(out["close"], config.rsi_window)

    fast_macd = _ema(out["close"], 12) - _ema(out["close"], 26)
    out["macd_atr"] = fast_macd / out["atr"]
    out["macd_signal_atr"] = _ema(fast_macd, 9) / out["atr"]
    out["macd_hist_atr"] = out["macd_atr"] - out["macd_signal_atr"]

    volume_mean = out["volume"].rolling(config.volume_window, min_periods=config.volume_window).mean()
    volume_std = out["volume"].rolling(config.volume_window, min_periods=config.volume_window).std(ddof=0)
    out["volume_z"] = (out["volume"] - volume_mean) / volume_std.replace(0, np.nan)
    typical = (out["high"] + out["low"] + out["close"]) / 3
    utc_day = time_basis.floor("D")
    cumulative_pv = (typical * out["volume"]).groupby(utc_day).cumsum()
    cumulative_volume = out["volume"].groupby(utc_day).cumsum()
    out["vwap"] = cumulative_pv / cumulative_volume.replace(0, np.nan)
    out["distance_vwap_atr"] = (out["close"] - out["vwap"]) / out["atr"]

    mid = out["close"].rolling(20, min_periods=20).mean()
    std = out["close"].rolling(20, min_periods=20).std(ddof=0)
    out["bollinger_bandwidth"] = (4 * std) / mid
    out["bollinger_z"] = (out["close"] - mid) / std.replace(0, np.nan)
    out["realized_vol_20"] = np.sqrt((np.log(out["close"]).diff() ** 2).rolling(20, min_periods=20).sum())

    pivot_high = _confirmed_pivot(out["high"], config.pivot_left, config.pivot_right, True)
    pivot_low = _confirmed_pivot(out["low"], config.pivot_left, config.pivot_right, False)
    out["confirmed_pivot_high"] = pivot_high
    out["confirmed_pivot_low"] = pivot_low
    out["last_swing_high"] = _last_confirmed(pivot_high)
    out["last_swing_low"] = _last_confirmed(pivot_low)
    out["distance_swing_high_atr"] = (out["last_swing_high"] - out["close"]) / out["atr"]
    out["distance_swing_low_atr"] = (out["close"] - out["last_swing_low"]) / out["atr"]

    daily_high = out["high"].groupby(utc_day).transform("max")
    daily_low = out["low"].groupby(utc_day).transform("min")
    day_table = pd.DataFrame({"day": utc_day, "high": daily_high, "low": daily_low}, index=out.index)
    unique_days = day_table.groupby("day", sort=True)[["high", "low"]].first()
    previous_day = unique_days.shift(1)
    out["previous_day_high"] = pd.Series(utc_day, index=out.index).map(previous_day["high"])
    out["previous_day_low"] = pd.Series(utc_day, index=out.index).map(previous_day["low"])

    week_key = time_basis.normalize() - pd.to_timedelta(time_basis.dayofweek, unit="D")
    weekly = pd.DataFrame({"week": week_key, "high": out["high"], "low": out["low"]}, index=out.index).groupby("week").agg({"high": "max", "low": "min"})
    previous_week = weekly.shift(1)
    out["previous_week_high"] = pd.Series(week_key, index=out.index).map(previous_week["high"])
    out["previous_week_low"] = pd.Series(week_key, index=out.index).map(previous_week["low"])

    out["bull_fvg_lower"] = out["high"].shift(2).where(out["low"] > out["high"].shift(2))
    out["bull_fvg_upper"] = out["low"].where(out["low"] > out["high"].shift(2))
    out["bear_fvg_lower"] = out["high"].where(out["high"] < out["low"].shift(2))
    out["bear_fvg_upper"] = out["low"].shift(2).where(out["high"] < out["low"].shift(2))
    out["last_bull_fvg_lower"] = out["bull_fvg_lower"].ffill()
    out["last_bull_fvg_upper"] = out["bull_fvg_upper"].ffill()
    out["last_bear_fvg_lower"] = out["bear_fvg_lower"].ffill()
    out["last_bear_fvg_upper"] = out["bear_fvg_upper"].ffill()

    tolerance = config.equal_tolerance_atr * out["atr"]
    out["near_equal_high"] = ((out["last_swing_high"] - out["high"].rolling(20, min_periods=5).max()).abs() <= tolerance).astype(float)
    out["near_equal_low"] = ((out["last_swing_low"] - out["low"].rolling(20, min_periods=5).min()).abs() <= tolerance).astype(float)

    out["bull_displacement"] = ((out["body_atr"] >= config.displacement_body_atr) & (out["close_location"] >= 0.75)).astype(float)
    out["bear_displacement"] = ((out["body_atr"] <= -config.displacement_body_atr) & (out["close_location"] <= 0.25)).astype(float)
    out["bull_bos"] = ((out["close"] > out["last_swing_high"].shift(1)) & (out["bull_displacement"] > 0)).astype(float)
    out["bear_bos"] = ((out["close"] < out["last_swing_low"].shift(1)) & (out["bear_displacement"] > 0)).astype(float)

    optional = {
        "mark_close": "basis_mark_atr",
        "index_close": "basis_index_atr",
        "premium_close": "premium_atr",
        "open_interest": "open_interest_change",
        "long_short_ratio": "long_short_ratio_z",
        "funding_rate": "funding_rate",
        "spread_bps": "spread_bps",
    }
    for source, destination in optional.items():
        if source not in raw.columns:
            out[destination] = np.nan
            continue
        values = pd.to_numeric(raw[source], errors="coerce")
        if source in {"mark_close", "index_close", "premium_close"}:
            out[destination] = (values - out["close"]) / out["atr"]
        elif source == "open_interest":
            out[destination] = np.log(values.replace(0, np.nan)).diff()
        elif source == "long_short_ratio":
            mean = values.rolling(100, min_periods=30).mean()
            std_value = values.rolling(100, min_periods=30).std(ddof=0)
            out[destination] = (values - mean) / std_value.replace(0, np.nan)
        else:
            out[destination] = values

    out["utc_hour_sin"] = np.sin(2 * np.pi * time_basis.hour / 24)
    out["utc_hour_cos"] = np.cos(2 * np.pi * time_basis.hour / 24)
    out["utc_weekday_sin"] = np.sin(2 * np.pi * time_basis.dayofweek / 7)
    out["utc_weekday_cos"] = np.cos(2 * np.pi * time_basis.dayofweek / 7)
    return out


def _nearest_above(row: pd.Series, price: float) -> float | None:
    values = [row.get("last_swing_high"), row.get("previous_day_high"), row.get("previous_week_high")]
    valid = sorted(float(value) for value in values if pd.notna(value) and float(value) > price)
    return valid[0] if valid else None


def _nearest_below(row: pd.Series, price: float) -> float | None:
    values = [row.get("last_swing_low"), row.get("previous_day_low"), row.get("previous_week_low")]
    valid = sorted((float(value) for value in values if pd.notna(value) and float(value) < price), reverse=True)
    return valid[0] if valid else None


def _numeric_feature_row(row: pd.Series) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in row.items():
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value):
            result[str(key)] = float(value)
    return result


def generate_event_candidates(
    features: pd.DataFrame,
    symbol: str,
    config: FeatureConfig = FeatureConfig(),
) -> list[EventCandidate]:
    required = {"atr", "last_swing_high", "last_swing_low", "bull_bos", "bear_bos"}
    if not required.issubset(features.columns):
        raise ValueError(f"features missing required columns: {sorted(required - set(features.columns))}")
    events: list[EventCandidate] = []
    previous_close = features["close"].shift(1)
    for position in range(2, len(features)):
        row = features.iloc[position]
        timestamp = features.index[position]
        atr = row.get("atr")
        if pd.isna(atr) or atr <= 0:
            continue
        buffer = config.sweep_buffer_atr * float(atr)
        feature_row = _numeric_feature_row(row)

        high_levels = [row.get("last_swing_high"), row.get("previous_day_high"), row.get("previous_week_high")]
        low_levels = [row.get("last_swing_low"), row.get("previous_day_low"), row.get("previous_week_low")]
        valid_highs = [float(level) for level in high_levels if pd.notna(level)]
        valid_lows = [float(level) for level in low_levels if pd.notna(level)]

        swept_highs = [level for level in valid_highs if row["high"] > level + buffer and row["close"] < level]
        if swept_highs and previous_close.iloc[position] <= max(swept_highs) + float(atr):
            structural = max(swept_highs)
            entry = float(row["close"])
            stop = float(row["high"] + buffer)
            target = _nearest_below(row, entry)
            if target is not None and target < entry and stop > entry:
                events.append(
                    EventCandidate(timestamp, symbol, EventFamily.LIQUIDITY_SWEEP_REVERSAL, -1, entry, entry, stop, target, structural, feature_row)
                )

        swept_lows = [level for level in valid_lows if row["low"] < level - buffer and row["close"] > level]
        if swept_lows and previous_close.iloc[position] >= min(swept_lows) - float(atr):
            structural = min(swept_lows)
            entry = float(row["close"])
            stop = float(row["low"] - buffer)
            target = _nearest_above(row, entry)
            if target is not None and target > entry and stop < entry:
                events.append(
                    EventCandidate(timestamp, symbol, EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, entry, entry, stop, target, structural, feature_row)
                )

        if row.get("bull_bos", 0) > 0:
            entry = float(row.get("bull_fvg_upper")) if pd.notna(row.get("bull_fvg_upper")) else float(row["close"])
            stop_level = row.get("last_swing_high")
            prior_low = features.iloc[position - 1].get("last_swing_low")
            stop = float(prior_low) if pd.notna(prior_low) else float(row["low"] - buffer)
            target = _nearest_above(row, float(row["close"]))
            if target is not None and stop < entry < target:
                events.append(
                    EventCandidate(timestamp, symbol, EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION, 1, float(row["close"]), entry, stop, target, float(stop_level), feature_row)
                )

        if row.get("bear_bos", 0) > 0:
            entry = float(row.get("bear_fvg_lower")) if pd.notna(row.get("bear_fvg_lower")) else float(row["close"])
            stop_level = row.get("last_swing_low")
            prior_high = features.iloc[position - 1].get("last_swing_high")
            stop = float(prior_high) if pd.notna(prior_high) else float(row["high"] + buffer)
            target = _nearest_below(row, float(row["close"]))
            if target is not None and target < entry < stop:
                events.append(
                    EventCandidate(timestamp, symbol, EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION, -1, float(row["close"]), entry, stop, target, float(stop_level), feature_row)
                )
    return events


def size_position_from_nav(
    nav: float,
    candidate: EventCandidate,
    risk: RiskConfig,
    entry_fee_rate: float,
    stop_fee_rate: float,
    entry_slippage_fraction: float,
    stop_slippage_fraction: float,
    expected_funding_fraction: float = 0.0,
) -> float:
    if nav <= 0:
        raise ValueError("nav must be positive")
    if not 0 < risk.risk_fraction < 1:
        raise ValueError("risk_fraction must be in (0, 1)")
    if risk.quantity_step <= 0:
        raise ValueError("quantity_step must be positive")
    entry = candidate.entry_reference
    stop_distance = candidate.stop_distance
    per_unit_loss = (
        stop_distance
        + entry * (entry_fee_rate + entry_slippage_fraction + expected_funding_fraction)
        + candidate.stop_reference * (stop_fee_rate + stop_slippage_fraction)
    )
    if per_unit_loss <= 0:
        raise ValueError("expected per-unit loss must be positive")
    risk_quantity = nav * risk.risk_fraction / per_unit_loss
    leverage_quantity = nav * risk.maximum_leverage / entry
    stop_fraction = stop_distance / entry
    maximum_safe_leverage = 1.0 / max(stop_fraction + risk.maintenance_margin_fraction + risk.liquidation_buffer_fraction, 1e-12)
    liquidation_quantity = nav * min(risk.maximum_leverage, maximum_safe_leverage) / entry
    raw_quantity = min(risk_quantity, leverage_quantity, liquidation_quantity)
    stepped = floor(raw_quantity / risk.quantity_step) * risk.quantity_step
    return stepped if stepped >= risk.minimum_quantity else 0.0
