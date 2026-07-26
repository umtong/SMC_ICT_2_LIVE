from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .core import EventCandidate, EventFamily, FeatureConfig, build_causal_features


@dataclass(frozen=True)
class CorpusAlphaConfig:
    """Few frozen structural thresholds distilled from the full transcript corpus.

    These values define a causal setup. They are not return, risk, leverage, or trade
    frequency ceilings and can be compared causally using only pre-2024 data.
    """

    confirmation_body_atr: float = 0.45
    confirmation_close_location: float = 0.65
    rejection_body_atr: float = 0.08
    sweep_buffer_atr: float = 0.03
    stop_buffer_atr: float = 0.04
    retest_tolerance_atr: float = 0.10
    continuation_trend_floor: float = 0.0
    target_cluster_tolerance_atr: float = 0.12


@dataclass
class _SetupState:
    family: EventFamily
    side: int
    created_pos: int
    created_at: pd.Timestamp
    structural_level: float
    origin_extreme: float
    internal_break: float
    swept_level_count: int
    sweep_depth_atr: float
    phase: str = "AWAIT_CONFIRM"
    confirmation_pos: int | None = None
    zone_lower: float | None = None
    zone_upper: float | None = None
    stop: float | None = None
    confirmation_body_atr: float = 0.0
    confirmation_volume_z: float = 0.0
    path_high: float = -np.inf
    path_low: float = np.inf


def _finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _numeric_row(row: pd.Series) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in row.items():
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value):
            result[str(key)] = float(value)
    return result


def _completed_period_columns(
    out: pd.DataFrame,
    time_basis: pd.DatetimeIndex,
    period: str,
    prefix: str,
) -> None:
    """Map only the open of the current period and OHLC of the completed prior period."""

    key = time_basis.floor(period)
    table = pd.DataFrame(
        {
            "period": key,
            "open": out["open"].to_numpy(),
            "high": out["high"].to_numpy(),
            "low": out["low"].to_numpy(),
            "close": out["close"].to_numpy(),
        },
        index=out.index,
    )
    aggregate = table.groupby("period", sort=True).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    previous = aggregate.shift(1)
    key_series = pd.Series(key, index=out.index)
    for name in ("open", "high", "low", "close"):
        out[f"previous_{prefix}_{name}"] = key_series.map(previous[name])
    out[f"current_{prefix}_open"] = key_series.map(aggregate["open"])


def build_corpus_features(
    frame: pd.DataFrame,
    feature_config: FeatureConfig = FeatureConfig(),
) -> pd.DataFrame:
    """Add reference-time, compression, and last-opposite-candle features causally."""

    out = build_causal_features(frame, feature_config).copy()
    raw_time = frame["bar_start"] if "bar_start" in frame.columns else frame.index
    time_basis = pd.DatetimeIndex(pd.to_datetime(raw_time, utc=True))

    _completed_period_columns(out, time_basis, "1h", "1h")
    _completed_period_columns(out, time_basis, "4h", "4h")

    out["internal_high_3"] = out["high"].shift(1).rolling(3, min_periods=2).max()
    out["internal_low_3"] = out["low"].shift(1).rolling(3, min_periods=2).min()

    bullish = out["close"] > out["open"]
    bearish = out["close"] < out["open"]
    body_low = out[["open", "close"]].min(axis=1)
    body_high = out[["open", "close"]].max(axis=1)
    for label, mask in (("bullish", bullish), ("bearish", bearish)):
        out[f"last_{label}_open"] = out["open"].where(mask).shift(1).ffill()
        out[f"last_{label}_high"] = out["high"].where(mask).shift(1).ffill()
        out[f"last_{label}_low"] = out["low"].where(mask).shift(1).ffill()
        out[f"last_{label}_body_low"] = body_low.where(mask).shift(1).ffill()
        out[f"last_{label}_body_high"] = body_high.where(mask).shift(1).ffill()

    bandwidth_median = out["bollinger_bandwidth"].rolling(96, min_periods=24).median()
    out["compression_ratio_96"] = out["bollinger_bandwidth"] / bandwidth_median.replace(0, np.nan)
    range_median = out["range_atr"].rolling(20, min_periods=10).median()
    out["range_expansion_ratio_20"] = out["range_atr"] / range_median.replace(0, np.nan)

    trend_components = pd.concat(
        [
            np.sign(out["ema_spread_atr"]),
            np.sign(out["ema_fast_slope_atr"]),
            np.sign(out["ema_slow_slope_atr"]),
            np.sign((out["close"] - out["current_4h_open"]) / out["atr"]),
            np.sign((out["close"] - out["current_1h_open"]) / out["atr"]),
        ],
        axis=1,
    )
    out["trend_alignment_score"] = trend_components.sum(axis=1, min_count=1)

    for prefix in ("previous_1h", "previous_4h"):
        for name in ("high", "low", "open"):
            out[f"distance_{prefix}_{name}_atr"] = (out["close"] - out[f"{prefix}_{name}"]) / out["atr"]
    out["distance_current_1h_open_atr"] = (out["close"] - out["current_1h_open"]) / out["atr"]
    out["distance_current_4h_open_atr"] = (out["close"] - out["current_4h_open"]) / out["atr"]
    return out


def _liquidity_values(row: pd.Series, high: bool) -> list[float]:
    suffix = "high" if high else "low"
    names = (
        f"last_swing_{suffix}",
        f"previous_day_{suffix}",
        f"previous_week_{suffix}",
        f"previous_1h_{suffix}",
        f"previous_4h_{suffix}",
    )
    return sorted({float(row.get(name)) for name in names if _finite(row.get(name))})


def _nearest_untouched_target(
    row: pd.Series,
    side: int,
    entry: float,
    path_high: float,
    path_low: float,
    atr: float,
    cluster_tolerance_atr: float,
) -> tuple[float | None, int]:
    if side > 0:
        floor = max(entry, path_high)
        candidates = [value for value in _liquidity_values(row, True) if value > floor]
        if not candidates:
            return None, 0
        target = min(candidates)
    else:
        ceiling = min(entry, path_low)
        candidates = [value for value in _liquidity_values(row, False) if value < ceiling]
        if not candidates:
            return None, 0
        target = max(candidates)
    tolerance = max(cluster_tolerance_atr * atr, 1e-12)
    confluence = sum(abs(value - target) <= tolerance for value in candidates)
    return target, confluence


def _zone_from_confirmation(row: pd.Series, side: int) -> tuple[float, float] | None:
    if side > 0 and _finite(row.get("bull_fvg_lower")) and _finite(row.get("bull_fvg_upper")):
        lower = float(row["bull_fvg_lower"])
        upper = float(row["bull_fvg_upper"])
    elif side < 0 and _finite(row.get("bear_fvg_lower")) and _finite(row.get("bear_fvg_upper")):
        lower = float(row["bear_fvg_lower"])
        upper = float(row["bear_fvg_upper"])
    elif side > 0:
        lower = float(row.get("last_bearish_body_low")) if _finite(row.get("last_bearish_body_low")) else np.nan
        upper = float(row.get("last_bearish_body_high")) if _finite(row.get("last_bearish_body_high")) else np.nan
    else:
        lower = float(row.get("last_bullish_body_low")) if _finite(row.get("last_bullish_body_low")) else np.nan
        upper = float(row.get("last_bullish_body_high")) if _finite(row.get("last_bullish_body_high")) else np.nan
    if not (_finite(lower) and _finite(upper)):
        return None
    lower, upper = sorted((float(lower), float(upper)))
    if upper <= lower:
        return None
    return lower, upper


def _confirmation(row: pd.Series, state: _SetupState, config: CorpusAlphaConfig) -> bool:
    body_atr = float(row.get("body_atr", 0.0)) if _finite(row.get("body_atr")) else 0.0
    close_location = float(row.get("close_location", 0.5)) if _finite(row.get("close_location")) else 0.5
    close = float(row["close"])
    if state.side > 0:
        return (
            close > state.internal_break
            and body_atr >= config.confirmation_body_atr
            and close_location >= config.confirmation_close_location
        )
    return (
        close < state.internal_break
        and body_atr <= -config.confirmation_body_atr
        and close_location <= 1.0 - config.confirmation_close_location
    )


def _rejection(row: pd.Series, side: int, midpoint: float, config: CorpusAlphaConfig) -> bool:
    body_atr = float(row.get("body_atr", 0.0)) if _finite(row.get("body_atr")) else 0.0
    if side > 0:
        return float(row["close"]) >= midpoint and body_atr >= config.rejection_body_atr
    return float(row["close"]) <= midpoint and body_atr <= -config.rejection_body_atr


def _setup_features(
    row: pd.Series,
    state: _SetupState,
    pos: int,
    entry: float,
    stop: float,
    target: float,
    target_confluence: int,
    atr: float,
) -> dict[str, float]:
    values = _numeric_row(row)
    midpoint = (float(state.zone_lower) + float(state.zone_upper)) / 2
    values.update(
        {
            "setup_is_reversal": float(state.family == EventFamily.LIQUIDITY_SWEEP_REVERSAL),
            "setup_age_bars": float(pos - state.created_pos),
            "confirmation_age_bars": float(pos - int(state.confirmation_pos or state.created_pos)),
            "sweep_depth_atr": float(state.sweep_depth_atr),
            "swept_level_count": float(state.swept_level_count),
            "confirmation_body_atr": float(state.confirmation_body_atr),
            "confirmation_volume_z": float(state.confirmation_volume_z),
            "zone_width_atr": (float(state.zone_upper) - float(state.zone_lower)) / atr,
            "retest_midpoint_distance_atr": (entry - midpoint) / atr,
            "stop_distance_atr": abs(entry - stop) / atr,
            "target_distance_atr": abs(target - entry) / atr,
            "raw_structural_reward_risk": abs(target - entry) / max(abs(entry - stop), 1e-12),
            "target_liquidity_confluence": float(target_confluence),
            "path_excursion_atr": (state.path_high - state.path_low) / atr,
        }
    )
    return values


def _event_from_retest(
    row: pd.Series,
    timestamp: pd.Timestamp,
    symbol: str,
    state: _SetupState,
    pos: int,
    config: CorpusAlphaConfig,
) -> EventCandidate | None:
    atr = float(row["atr"])
    if not _finite(atr) or atr <= 0 or state.zone_lower is None or state.zone_upper is None or state.stop is None:
        return None
    tolerance = config.retest_tolerance_atr * atr
    touched = float(row["low"]) <= state.zone_upper + tolerance and float(row["high"]) >= state.zone_lower - tolerance
    if not touched:
        return None
    midpoint = (state.zone_lower + state.zone_upper) / 2
    if not _rejection(row, state.side, midpoint, config):
        return None
    entry = float(row["close"])
    stop = float(state.stop)
    if (state.side > 0 and stop >= entry) or (state.side < 0 and stop <= entry):
        return None
    target, confluence = _nearest_untouched_target(
        row,
        state.side,
        entry,
        state.path_high,
        state.path_low,
        atr,
        config.target_cluster_tolerance_atr,
    )
    if target is None:
        return None
    if (state.side > 0 and target <= entry) or (state.side < 0 and target >= entry):
        return None
    return EventCandidate(
        timestamp=timestamp,
        symbol=symbol,
        family=state.family,
        side=state.side,
        decision_price=entry,
        entry_reference=entry,
        stop_reference=stop,
        target_reference=float(target),
        structural_level=float(state.structural_level),
        feature_row=_setup_features(row, state, pos, entry, stop, float(target), confluence, atr),
    )


def _process_state(
    state: _SetupState,
    row: pd.Series,
    timestamp: pd.Timestamp,
    pos: int,
    symbol: str,
    config: CorpusAlphaConfig,
) -> tuple[_SetupState | None, EventCandidate | None]:
    atr = float(row["atr"])
    state.path_high = max(state.path_high, float(row["high"]))
    state.path_low = min(state.path_low, float(row["low"]))
    stop_buffer = config.stop_buffer_atr * atr

    if state.family == EventFamily.LIQUIDITY_SWEEP_REVERSAL:
        structural_stop = state.origin_extreme - stop_buffer if state.side > 0 else state.origin_extreme + stop_buffer
    else:
        structural_stop = state.stop if state.stop is not None else state.origin_extreme
    if state.side > 0 and float(row["low"]) <= structural_stop:
        return None, None
    if state.side < 0 and float(row["high"]) >= structural_stop:
        return None, None

    if state.phase == "AWAIT_CONFIRM":
        if pos <= state.created_pos or not _confirmation(row, state, config):
            return state, None
        zone = _zone_from_confirmation(row, state.side)
        if zone is None:
            return None, None
        lower, upper = zone
        close = float(row["close"])
        if (state.side > 0 and upper >= close) or (state.side < 0 and lower <= close):
            return None, None
        state.phase = "AWAIT_RETEST"
        state.confirmation_pos = pos
        state.zone_lower = lower
        state.zone_upper = upper
        state.stop = structural_stop
        state.confirmation_body_atr = float(row.get("body_atr", 0.0))
        state.confirmation_volume_z = float(row.get("volume_z", 0.0)) if _finite(row.get("volume_z")) else 0.0
        return state, None

    if state.confirmation_pos is None or pos <= state.confirmation_pos:
        return state, None
    tolerance = config.retest_tolerance_atr * atr
    touched = float(row["low"]) <= float(state.zone_upper) + tolerance and float(row["high"]) >= float(state.zone_lower) - tolerance
    if not touched:
        return state, None
    event = _event_from_retest(row, timestamp, symbol, state, pos, config)
    # The first mitigation consumes the setup whether it rejects or fails.
    return None, event


def _new_reversal_states(
    features: pd.DataFrame,
    pos: int,
    config: CorpusAlphaConfig,
) -> list[_SetupState]:
    row = features.iloc[pos]
    previous = features.iloc[pos - 1]
    atr = float(row["atr"])
    buffer = config.sweep_buffer_atr * atr
    high_levels = _liquidity_values(row, True)
    low_levels = _liquidity_values(row, False)
    swept_highs = [
        level
        for level in high_levels
        if float(row["high"]) > level + buffer
        and float(row["close"]) < level
        and (
            float(previous["high"]) <= level + buffer
            or float(row["high"]) > float(previous["high"]) + buffer
        )
    ]
    swept_lows = [
        level
        for level in low_levels
        if float(row["low"]) < level - buffer
        and float(row["close"]) > level
        and (
            float(previous["low"]) >= level - buffer
            or float(row["low"]) < float(previous["low"]) - buffer
        )
    ]
    # An outside bar that raids both sides has unknown intrabar ordering at this resolution.
    if swept_highs and swept_lows:
        return []
    timestamp = features.index[pos]
    states: list[_SetupState] = []
    if swept_highs and _finite(row.get("internal_low_3")):
        level = max(swept_highs)
        states.append(
            _SetupState(
                family=EventFamily.LIQUIDITY_SWEEP_REVERSAL,
                side=-1,
                created_pos=pos,
                created_at=timestamp,
                structural_level=level,
                origin_extreme=float(row["high"]),
                internal_break=float(row["internal_low_3"]),
                swept_level_count=len(swept_highs),
                sweep_depth_atr=(float(row["high"]) - level) / atr,
                path_high=float(row["high"]),
                path_low=float(row["low"]),
            )
        )
    if swept_lows and _finite(row.get("internal_high_3")):
        level = min(swept_lows)
        states.append(
            _SetupState(
                family=EventFamily.LIQUIDITY_SWEEP_REVERSAL,
                side=1,
                created_pos=pos,
                created_at=timestamp,
                structural_level=level,
                origin_extreme=float(row["low"]),
                internal_break=float(row["internal_high_3"]),
                swept_level_count=len(swept_lows),
                sweep_depth_atr=(level - float(row["low"])) / atr,
                path_high=float(row["high"]),
                path_low=float(row["low"]),
            )
        )
    return states


def _new_continuation_state(
    row: pd.Series,
    timestamp: pd.Timestamp,
    pos: int,
    side: int,
    config: CorpusAlphaConfig,
) -> _SetupState | None:
    atr = float(row["atr"])
    trend = float(row.get("trend_alignment_score", 0.0)) if _finite(row.get("trend_alignment_score")) else 0.0
    if side * trend <= config.continuation_trend_floor:
        return None
    zone = _zone_from_confirmation(row, side)
    if zone is None:
        return None
    lower, upper = zone
    close = float(row["close"])
    if (side > 0 and upper >= close) or (side < 0 and lower <= close):
        return None
    if side > 0:
        stop = float(row.get("last_swing_low")) if _finite(row.get("last_swing_low")) else float(row["low"] - config.stop_buffer_atr * atr)
        structural = float(row.get("last_swing_high")) if _finite(row.get("last_swing_high")) else close
        if stop >= lower:
            stop = min(float(row["low"] - config.stop_buffer_atr * atr), lower - config.stop_buffer_atr * atr)
    else:
        stop = float(row.get("last_swing_high")) if _finite(row.get("last_swing_high")) else float(row["high"] + config.stop_buffer_atr * atr)
        structural = float(row.get("last_swing_low")) if _finite(row.get("last_swing_low")) else close
        if stop <= upper:
            stop = max(float(row["high"] + config.stop_buffer_atr * atr), upper + config.stop_buffer_atr * atr)
    return _SetupState(
        family=EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION,
        side=side,
        created_pos=pos,
        created_at=timestamp,
        structural_level=structural,
        origin_extreme=stop,
        internal_break=close,
        swept_level_count=0,
        sweep_depth_atr=0.0,
        phase="AWAIT_RETEST",
        confirmation_pos=pos,
        zone_lower=lower,
        zone_upper=upper,
        stop=stop,
        confirmation_body_atr=float(row.get("body_atr", 0.0)),
        confirmation_volume_z=float(row.get("volume_z", 0.0)) if _finite(row.get("volume_z")) else 0.0,
        path_high=float(row["high"]),
        path_low=float(row["low"]),
    )


def generate_corpus_candidates(
    features: pd.DataFrame,
    symbol: str,
    config: CorpusAlphaConfig = CorpusAlphaConfig(),
) -> list[EventCandidate]:
    """Generate only after raid/BOS, later confirmation, and the first causal retest."""

    required = {
        "open",
        "high",
        "low",
        "close",
        "atr",
        "body_atr",
        "close_location",
        "bull_bos",
        "bear_bos",
        "internal_high_3",
        "internal_low_3",
    }
    missing = required - set(features.columns)
    if missing:
        raise ValueError(f"corpus features missing required columns: {sorted(missing)}")
    states: dict[tuple[EventFamily, int], _SetupState] = {}
    events: list[EventCandidate] = []
    for pos in range(1, len(features)):
        row = features.iloc[pos]
        if not _finite(row.get("atr")) or float(row["atr"]) <= 0:
            continue
        timestamp = features.index[pos]

        for key, state in list(states.items()):
            updated, event = _process_state(state, row, timestamp, pos, symbol, config)
            if event is not None:
                events.append(event)
            if updated is None:
                states.pop(key, None)
            else:
                states[key] = updated

        for state in _new_reversal_states(features, pos, config):
            states[(state.family, state.side)] = state

        if float(row.get("bull_bos", 0.0)) > 0:
            state = _new_continuation_state(row, timestamp, pos, 1, config)
            if state is not None:
                states[(state.family, 1)] = state
        if float(row.get("bear_bos", 0.0)) > 0:
            state = _new_continuation_state(row, timestamp, pos, -1, config)
            if state is not None:
                states[(state.family, -1)] = state

    events.sort(key=lambda item: (item.timestamp, item.symbol, item.family.value, item.side))
    return events
