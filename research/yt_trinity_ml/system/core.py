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
    confirmation_window_bars: int = 8
    continuation_retest_window_bars: int = 12
    internal_structure_lookback: int = 4
    require_confirmation_fvg: bool = True
    retest_close_location_min: float = 0.55


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
        if source in {"mark_close", "index_close"}:
            out[destination] = (values - out["close"]) / out["atr"]
        elif source == "open_interest":
            out[destination] = np.log(values.replace(0, np.nan)).diff()
        elif source == "long_short_ratio":
            mean = values.rolling(100, min_periods=30).mean()
            std_value = values.rolling(100, min_periods=30).std(ddof=0)
            out[destination] = (values - mean) / std_value.replace(0, np.nan)
        else:
            out[destination] = values

    # Bybit premium-index klines contain a premium rate, not a tradable price.
    # Treating that rate as a price and subtracting the contract close creates a
    # scale-dependent value hundreds or thousands of ATRs from zero.
    if "premium_close" in raw.columns:
        premium_rate = pd.to_numeric(raw["premium_close"], errors="coerce")
        premium_mean = premium_rate.rolling(100, min_periods=30).mean()
        premium_std = premium_rate.rolling(100, min_periods=30).std(ddof=0)
        out["premium_rate"] = premium_rate
        out["premium_bps"] = premium_rate * 10_000.0
        out["premium_rate_z"] = (premium_rate - premium_mean) / premium_std.replace(0, np.nan)
    else:
        out["premium_rate"] = np.nan
        out["premium_bps"] = np.nan
        out["premium_rate_z"] = np.nan
    # Keep the legacy column non-informative so old manifests fail safely instead
    # of silently learning the invalid price-minus-rate calculation.
    out["premium_atr"] = np.nan

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
    """Generate only completed, causally confirmed structural setups.

    A liquidity raid is not an entry by itself. It first arms a reversal setup and
    becomes tradable only after a later displacement/MSS confirmation. Likewise, a
    displacement break arms a continuation setup and becomes tradable only after a
    later accepted retest. This avoids labelling the setup bar with information that
    did not yet exist and removes the economically weak "sweep equals entry" and
    "break bar equals retest" shortcuts.
    """
    required = {
        "atr",
        "last_swing_high",
        "last_swing_low",
        "bull_bos",
        "bear_bos",
        "bull_displacement",
        "bear_displacement",
    }
    if not required.issubset(features.columns):
        raise ValueError(f"features missing required columns: {sorted(required - set(features.columns))}")
    if config.confirmation_window_bars <= 0 or config.continuation_retest_window_bars <= 0:
        raise ValueError("setup windows must be positive")
    if config.internal_structure_lookback <= 0:
        raise ValueError("internal_structure_lookback must be positive")

    @dataclass(frozen=True)
    class SweepSetup:
        armed_position: int
        side: int
        swept_level: float
        extreme: float
        confirmation_level: float
        sweep_depth_atr: float

    @dataclass(frozen=True)
    class ContinuationSetup:
        armed_position: int
        side: int
        broken_level: float
        zone_lower: float
        zone_upper: float
        stop_reference: float

    events: list[EventCandidate] = []
    previous_close = features["close"].shift(1)
    sweep_setups: dict[int, SweepSetup] = {}
    continuation_setups: dict[int, ContinuationSetup] = {}

    def feature_snapshot(row: pd.Series, **extra: float) -> dict[str, float]:
        snapshot = _numeric_feature_row(row)
        snapshot.update({key: float(value) for key, value in extra.items() if np.isfinite(value)})
        return snapshot

    for position in range(2, len(features)):
        row = features.iloc[position]
        timestamp = features.index[position]
        atr_value = row.get("atr")
        if pd.isna(atr_value) or float(atr_value) <= 0:
            continue
        atr = float(atr_value)
        buffer = config.sweep_buffer_atr * atr
        tolerance = config.retest_tolerance_atr * atr

        # 1) Confirm previously armed liquidity raids with a later MSS/displacement.
        for side, setup in list(sweep_setups.items()):
            age = position - setup.armed_position
            invalidated = (
                float(row["low"]) < setup.extreme - buffer
                if side > 0
                else float(row["high"]) > setup.extreme + buffer
            )
            if age > config.confirmation_window_bars or invalidated:
                del sweep_setups[side]
                continue
            if age < 1:
                continue
            displaced = row.get("bull_displacement", 0) > 0 if side > 0 else row.get("bear_displacement", 0) > 0
            structure_shift = float(row["close"]) > setup.confirmation_level if side > 0 else float(row["close"]) < setup.confirmation_level
            if side > 0:
                fvg_lower, fvg_upper = row.get("bull_fvg_lower"), row.get("bull_fvg_upper")
            else:
                fvg_lower, fvg_upper = row.get("bear_fvg_lower"), row.get("bear_fvg_upper")
            has_fvg = pd.notna(fvg_lower) and pd.notna(fvg_upper) and float(fvg_lower) < float(fvg_upper)
            if not displaced or not structure_shift or (config.require_confirmation_fvg and not has_fvg):
                continue
            entry = (float(fvg_lower) + float(fvg_upper)) / 2 if has_fvg else float(row["close"])
            stop = setup.extreme - buffer if side > 0 else setup.extreme + buffer
            target = _nearest_above(row, max(entry, float(row["close"]))) if side > 0 else _nearest_below(row, min(entry, float(row["close"])))
            valid_geometry = target is not None and (stop < entry < target if side > 0 else target < entry < stop)
            if valid_geometry:
                events.append(
                    EventCandidate(
                        timestamp=timestamp,
                        symbol=symbol,
                        family=EventFamily.LIQUIDITY_SWEEP_REVERSAL,
                        side=side,
                        decision_price=float(row["close"]),
                        entry_reference=entry,
                        stop_reference=stop,
                        target_reference=float(target),
                        structural_level=setup.swept_level,
                        feature_row=feature_snapshot(
                            row,
                            setup_age_bars=age,
                            sweep_depth_atr=setup.sweep_depth_atr,
                            confirmation_distance_atr=abs(float(row["close"]) - setup.confirmation_level) / atr,
                            passive_retrace_distance_atr=abs(float(row["close"]) - entry) / atr,
                        ),
                    )
                )
            del sweep_setups[side]

        # 2) Confirm a prior displacement break only after a later accepted retest.
        for side, setup in list(continuation_setups.items()):
            age = position - setup.armed_position
            hard_invalidated = float(row["low"]) <= setup.stop_reference if side > 0 else float(row["high"]) >= setup.stop_reference
            if age > config.continuation_retest_window_bars or hard_invalidated:
                del continuation_setups[side]
                continue
            if age < 1:
                continue
            touched = float(row["low"]) <= setup.zone_upper + tolerance and float(row["high"]) >= setup.zone_lower - tolerance
            accepted = (
                float(row["close"]) > setup.broken_level
                and float(row.get("close_location", 0.0)) >= config.retest_close_location_min
                and float(row.get("body", 0.0)) > 0
                if side > 0
                else float(row["close"]) < setup.broken_level
                and float(row.get("close_location", 1.0)) <= 1 - config.retest_close_location_min
                and float(row.get("body", 0.0)) < 0
            )
            if not touched or not accepted:
                continue
            entry = (setup.zone_lower + setup.zone_upper) / 2
            target = _nearest_above(row, max(entry, float(row["close"]))) if side > 0 else _nearest_below(row, min(entry, float(row["close"])))
            valid_geometry = target is not None and (setup.stop_reference < entry < target if side > 0 else target < entry < setup.stop_reference)
            if valid_geometry:
                events.append(
                    EventCandidate(
                        timestamp=timestamp,
                        symbol=symbol,
                        family=EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION,
                        side=side,
                        decision_price=float(row["close"]),
                        entry_reference=entry,
                        stop_reference=setup.stop_reference,
                        target_reference=float(target),
                        structural_level=setup.broken_level,
                        feature_row=feature_snapshot(
                            row,
                            setup_age_bars=age,
                            retest_zone_width_atr=(setup.zone_upper - setup.zone_lower) / atr,
                            retest_distance_atr=abs(float(row["close"]) - entry) / atr,
                            accepted_break_distance_atr=abs(float(row["close"]) - setup.broken_level) / atr,
                        ),
                    )
                )
            del continuation_setups[side]

        high_levels = [row.get("last_swing_high"), row.get("previous_day_high"), row.get("previous_week_high")]
        low_levels = [row.get("last_swing_low"), row.get("previous_day_low"), row.get("previous_week_low")]
        valid_highs = [float(level) for level in high_levels if pd.notna(level)]
        valid_lows = [float(level) for level in low_levels if pd.notna(level)]
        lookback_start = max(0, position - config.internal_structure_lookback)
        prior_slice = features.iloc[lookback_start:position]

        # 3) Arm, but do not trade, a newly observed liquidity raid.
        swept_highs = [level for level in valid_highs if float(row["high"]) > level + buffer and float(row["close"]) < level]
        if swept_highs and previous_close.iloc[position] <= max(swept_highs) + atr and not prior_slice.empty:
            structural = max(swept_highs)
            sweep_setups[-1] = SweepSetup(
                armed_position=position,
                side=-1,
                swept_level=structural,
                extreme=float(row["high"]),
                confirmation_level=float(prior_slice["low"].min()),
                sweep_depth_atr=(float(row["high"]) - structural) / atr,
            )

        swept_lows = [level for level in valid_lows if float(row["low"]) < level - buffer and float(row["close"]) > level]
        if swept_lows and previous_close.iloc[position] >= min(swept_lows) - atr and not prior_slice.empty:
            structural = min(swept_lows)
            sweep_setups[1] = SweepSetup(
                armed_position=position,
                side=1,
                swept_level=structural,
                extreme=float(row["low"]),
                confirmation_level=float(prior_slice["high"].max()),
                sweep_depth_atr=(structural - float(row["low"])) / atr,
            )

        # 4) Arm a displacement continuation; the break bar itself is never an entry.
        if row.get("bull_bos", 0) > 0 and pd.notna(row.get("bull_fvg_lower")) and pd.notna(row.get("bull_fvg_upper")):
            lower, upper = float(row["bull_fvg_lower"]), float(row["bull_fvg_upper"])
            prior = features.iloc[position - 1]
            broken = prior.get("last_swing_high")
            prior_low = prior.get("last_swing_low")
            if lower < upper and pd.notna(broken):
                stop = min(float(prior_low), lower - buffer) if pd.notna(prior_low) else lower - buffer
                continuation_setups[1] = ContinuationSetup(position, 1, float(broken), lower, upper, stop)

        if row.get("bear_bos", 0) > 0 and pd.notna(row.get("bear_fvg_lower")) and pd.notna(row.get("bear_fvg_upper")):
            lower, upper = float(row["bear_fvg_lower"]), float(row["bear_fvg_upper"])
            prior = features.iloc[position - 1]
            broken = prior.get("last_swing_low")
            prior_high = prior.get("last_swing_high")
            if lower < upper and pd.notna(broken):
                stop = max(float(prior_high), upper + buffer) if pd.notna(prior_high) else upper + buffer
                continuation_setups[-1] = ContinuationSetup(position, -1, float(broken), lower, upper, stop)

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
    expected_entry_price: float | None = None,
    expected_stop_fill_price: float | None = None,
) -> float:
    if nav <= 0:
        raise ValueError("nav must be positive")
    if not 0 < risk.risk_fraction < 1:
        raise ValueError("risk_fraction must be in (0, 1)")
    if risk.quantity_step <= 0:
        raise ValueError("quantity_step must be positive")
    entry = float(expected_entry_price) if expected_entry_price is not None else candidate.entry_reference
    stop_fill = float(expected_stop_fill_price) if expected_stop_fill_price is not None else candidate.stop_reference
    if entry <= 0 or stop_fill <= 0:
        raise ValueError("expected entry and stop fill prices must be positive")
    stop_distance = abs(entry - stop_fill)
    per_unit_loss = (
        stop_distance
        + entry * (entry_fee_rate + entry_slippage_fraction + expected_funding_fraction)
        + stop_fill * (stop_fee_rate + stop_slippage_fraction)
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
