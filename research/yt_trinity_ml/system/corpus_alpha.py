from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .core import EventCandidate, EventFamily, FeatureConfig, build_causal_features


@dataclass(frozen=True)
class CorpusAlphaConfig:
    """Frozen structural rules for one unified SMC/ICT delivery narrative.

    Reversal and continuation remain diagnostic delivery modes, not separately
    selected strategies.  Every candidate must connect a knowable liquidity pool,
    a draw on opposing liquidity, displacement/structure, a causal PD array, a
    mitigation, and structural invalidation.
    """

    displacement_body_atr: float = 0.55
    displacement_range_atr: float = 0.90
    displacement_close_location: float = 0.70
    minimum_displacement_efficiency: float = 0.50
    sweep_buffer_atr: float = 0.03
    stop_buffer_atr: float = 0.04
    retest_tolerance_atr: float = 0.08
    entry_close_location: float = 0.58
    target_cluster_tolerance_atr: float = 0.12
    liquidity_dedup_tolerance_atr: float = 0.06
    strong_counter_bias_floor: float = -3.0


@dataclass(frozen=True)
class _LiquidityPool:
    price: float
    quality: int
    kind: str
    confluence: int = 1


@dataclass
class _NarrativeState:
    family: EventFamily
    side: int
    created_pos: int
    created_at: pd.Timestamp
    structural_level: float
    origin_extreme: float
    internal_break: float
    draw_target: float
    draw_target_quality: int
    swept_level_count: int
    sweep_depth_atr: float
    liquidity_quality: int
    ob_search_start: int | None = None
    raid_reclaimed_same_bar: bool = False
    phase: str = "AWAIT_DISPLACEMENT"
    confirmation_pos: int | None = None
    zone_lower: float | None = None
    zone_upper: float | None = None
    zone_kind: int = 0
    stop: float | None = None
    impulse_low: float | None = None
    impulse_high: float | None = None
    confirmation_body_atr: float = 0.0
    confirmation_volume_z: float = 0.0
    displacement_efficiency: float = 0.0
    fvg_width_atr: float = 0.0
    ob_width_atr: float = 0.0
    first_retest_pos: int | None = None
    mitigation_count: int = 0
    retest_trigger: float | None = None
    retest_extreme: float | None = None
    entry_confirmation_kind: int = 0
    path_high: float = -np.inf
    path_low: float = np.inf


def _finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _bump(diagnostics: Counter[str] | None, key: str, amount: int = 1) -> None:
    if diagnostics is not None:
        diagnostics[key] += amount


def _numeric_row(row: pd.Series) -> dict[str, float]:
    """Return only causal, scale-free context for the pooled cross-symbol ML model.

    Absolute OHLC, raw volume and price-level columns let a pooled tree identify the
    instrument and calendar regime instead of learning SMC setup quality. Structural
    distances are added separately in ATR/R units below.
    """

    raw_exact = {
        "open", "high", "low", "close", "volume", "turnover", "trade_count",
        "buy_volume", "sell_volume", "open_interest", "mark_price", "index_price",
    }
    raw_suffixes = (
        "_price", "_level", "_lower", "_upper", "_equilibrium",
        "_high", "_low", "_open", "_close", "_volume", "_turnover",
        "_trade_count", "_open_interest",
    )
    result: dict[str, float] = {}
    for key, value in row.items():
        name = str(key)
        if not isinstance(value, (int, float, np.integer, np.floating)) or not np.isfinite(value):
            continue
        if name in raw_exact or "timestamp" in name or name.endswith(("_ns", "_ms")):
            continue
        if name.endswith(raw_suffixes):
            continue
        result[name] = float(value)
    return result


def _confirmed_pivot(series: pd.Series, left: int, right: int, high: bool) -> pd.Series:
    width = left + right + 1
    rolling = series.rolling(width, min_periods=width)
    extreme = rolling.max() if high else rolling.min()
    candidate = series.shift(right)
    return candidate.where(candidate.eq(extreme))


def _completed_period_columns(
    out: pd.DataFrame,
    time_basis: pd.DatetimeIndex,
    period: str,
    prefix: str,
) -> None:
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


def _session_columns(
    out: pd.DataFrame,
    time_basis: pd.DatetimeIndex,
    start_hour: int,
    end_hour: int,
    prefix: str,
) -> None:
    """Expose a same-day session range only after that session has completed."""

    day = time_basis.floor("D")
    hour = time_basis.hour
    in_session = (hour >= start_hour) & (hour < end_hour)
    table = pd.DataFrame(
        {
            "day": day[in_session],
            "high": out.loc[in_session, "high"].to_numpy(),
            "low": out.loc[in_session, "low"].to_numpy(),
        }
    )
    if table.empty:
        out[f"current_{prefix}_high"] = np.nan
        out[f"current_{prefix}_low"] = np.nan
        return
    aggregate = table.groupby("day", sort=True).agg(high=("high", "max"), low=("low", "min"))
    day_series = pd.Series(day, index=out.index)
    available = hour >= end_hour
    out[f"current_{prefix}_high"] = day_series.map(aggregate["high"]).where(available)
    out[f"current_{prefix}_low"] = day_series.map(aggregate["low"]).where(available)


def _completed_timeframe_context(
    out: pd.DataFrame,
    time_basis: pd.DatetimeIndex,
    rule: str,
    prefix: str,
) -> None:
    """As-of join only fully completed HTF bars and their confirmed structure."""

    source = pd.DataFrame(
        {
            "open": out["open"].to_numpy(),
            "high": out["high"].to_numpy(),
            "low": out["low"].to_numpy(),
            "close": out["close"].to_numpy(),
            "volume": out["volume"].to_numpy(),
        },
        index=time_basis,
    )
    bars = source.resample(rule, label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open", "high", "low", "close"])
    if bars.empty:
        for name in ("bias", "last_swing_high", "last_swing_low", "equilibrium", "range_position"):
            out[f"{prefix}_{name}"] = np.nan
        return

    pivot_high = _confirmed_pivot(bars["high"], 2, 2, True)
    pivot_low = _confirmed_pivot(bars["low"], 2, 2, False)
    bars["last_swing_high"] = pivot_high.ffill()
    bars["last_swing_low"] = pivot_low.ffill()
    prior_high = bars["last_swing_high"].shift(1)
    prior_low = bars["last_swing_low"].shift(1)
    bull_break = bars["close"].gt(prior_high) & bars["close"].shift(1).le(prior_high)
    bear_break = bars["close"].lt(prior_low) & bars["close"].shift(1).ge(prior_low)
    event = pd.Series(np.nan, index=bars.index, dtype=float)
    event.loc[bull_break] = 1.0
    event.loc[bear_break] = -1.0
    bars["bias"] = event.ffill().fillna(0.0)
    bars["equilibrium"] = (bars["last_swing_high"] + bars["last_swing_low"]) / 2.0
    width = (bars["last_swing_high"] - bars["last_swing_low"]).replace(0, np.nan)
    bars["range_position"] = (bars["close"] - bars["last_swing_low"]) / width

    offset = pd.tseries.frequencies.to_offset(rule)
    context = bars[["bias", "last_swing_high", "last_swing_low", "equilibrium", "range_position"]].copy()
    context.index = context.index + offset
    context.index.name = "available_at"
    left = pd.DataFrame({"available_at": pd.DatetimeIndex(out.index)})
    right = context.reset_index()
    merged = pd.merge_asof(
        left.sort_values("available_at"),
        right.sort_values("available_at"),
        on="available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    merged.index = out.index
    for name in ("bias", "last_swing_high", "last_swing_low", "equilibrium", "range_position"):
        out[f"{prefix}_{name}"] = merged[name].to_numpy()


def build_corpus_features(
    frame: pd.DataFrame,
    feature_config: FeatureConfig = FeatureConfig(),
) -> pd.DataFrame:
    """Build causal structure, session, HTF and PD-array context."""

    out = build_causal_features(frame, feature_config).copy()
    raw_time = frame["bar_start"] if "bar_start" in frame.columns else frame.index
    time_basis = pd.DatetimeIndex(pd.to_datetime(raw_time, utc=True))

    _completed_period_columns(out, time_basis, "1h", "1h")
    _completed_period_columns(out, time_basis, "4h", "4h")
    _session_columns(out, time_basis, 0, 6, "asia")
    _session_columns(out, time_basis, 7, 10, "london_open")
    _completed_timeframe_context(out, time_basis, "15min", "htf_15m")
    _completed_timeframe_context(out, time_basis, "1h", "htf_1h")
    _completed_timeframe_context(out, time_basis, "4h", "htf_4h")

    micro_high = _confirmed_pivot(out["high"], 2, 2, True)
    micro_low = _confirmed_pivot(out["low"], 2, 2, False)
    out["micro_pivot_high"] = micro_high
    out["micro_pivot_low"] = micro_low
    out["micro_last_swing_high"] = micro_high.ffill()
    out["micro_last_swing_low"] = micro_low.ffill()
    previous_micro_high = micro_high.ffill().shift(1)
    previous_micro_low = micro_low.ffill().shift(1)
    equality_tolerance = feature_config.equal_tolerance_atr * out["atr"]
    out["equal_high_liquidity"] = ((micro_high + previous_micro_high) / 2.0).where(
        micro_high.notna() & previous_micro_high.notna() & (micro_high - previous_micro_high).abs().le(equality_tolerance)
    ).ffill()
    out["equal_low_liquidity"] = ((micro_low + previous_micro_low) / 2.0).where(
        micro_low.notna() & previous_micro_low.notna() & (micro_low - previous_micro_low).abs().le(equality_tolerance)
    ).ffill()
    out["internal_high_5"] = out["high"].shift(1).rolling(5, min_periods=3).max()
    out["internal_low_5"] = out["low"].shift(1).rolling(5, min_periods=3).min()

    bandwidth_median = out["bollinger_bandwidth"].rolling(96, min_periods=24).median()
    out["compression_ratio_96"] = out["bollinger_bandwidth"] / bandwidth_median.replace(0, np.nan)
    range_median = out["range_atr"].rolling(20, min_periods=10).median()
    out["range_expansion_ratio_20"] = out["range_atr"] / range_median.replace(0, np.nan)
    out["displacement_efficiency"] = out["body_atr"].abs() / out["range_atr"].replace(0, np.nan)

    trend_components = pd.concat(
        [
            np.sign(out["ema_spread_atr"]),
            np.sign(out["ema_fast_slope_atr"]),
            np.sign(out["ema_slow_slope_atr"]),
            out["htf_15m_bias"].fillna(0.0),
            2.0 * out["htf_1h_bias"].fillna(0.0),
            3.0 * out["htf_4h_bias"].fillna(0.0),
        ],
        axis=1,
    )
    out["trend_alignment_score"] = trend_components.sum(axis=1, min_count=1)
    out["htf_bias_score"] = (
        out["htf_15m_bias"].fillna(0.0)
        + 2.0 * out["htf_1h_bias"].fillna(0.0)
        + 3.0 * out["htf_4h_bias"].fillna(0.0)
    )

    out["dealing_range_high"] = out[["last_swing_high", "htf_1h_last_swing_high"]].max(axis=1)
    out["dealing_range_low"] = out[["last_swing_low", "htf_1h_last_swing_low"]].min(axis=1)
    out["dealing_range_equilibrium"] = (out["dealing_range_high"] + out["dealing_range_low"]) / 2.0
    dealing_width = (out["dealing_range_high"] - out["dealing_range_low"]).replace(0, np.nan)
    out["dealing_range_position"] = (out["close"] - out["dealing_range_low"]) / dealing_width

    hour = time_basis.hour + time_basis.minute / 60.0
    out["session_code"] = np.select(
        [hour < 6.0, (hour >= 7.0) & (hour < 10.0), (hour >= 13.0) & (hour < 16.5)],
        [1.0, 2.0, 3.0],
        default=0.0,
    )
    out["killzone"] = out["session_code"].isin([2.0, 3.0]).astype(float)

    for prefix in ("previous_1h", "previous_4h"):
        for name in ("high", "low", "open"):
            out[f"distance_{prefix}_{name}_atr"] = (out["close"] - out[f"{prefix}_{name}"]) / out["atr"]
    out["distance_current_1h_open_atr"] = (out["close"] - out["current_1h_open"]) / out["atr"]
    out["distance_current_4h_open_atr"] = (out["close"] - out["current_4h_open"]) / out["atr"]
    return out


_HIGH_POOL_SOURCES: tuple[tuple[str, int, str], ...] = (
    ("previous_week_high", 7, "PWH"),
    ("htf_4h_last_swing_high", 7, "4H_BSL"),
    ("previous_day_high", 6, "PDH"),
    ("htf_1h_last_swing_high", 6, "1H_BSL"),
    ("current_asia_high", 5, "ASIA_H"),
    ("current_london_open_high", 5, "LONDON_H"),
    ("equal_high_liquidity", 6, "EQH"),
    ("previous_4h_high", 4, "P4H"),
    ("last_swing_high", 4, "BSL"),
    ("previous_1h_high", 3, "P1H"),
    ("micro_last_swing_high", 2, "INTERNAL_BSL"),
)
_LOW_POOL_SOURCES: tuple[tuple[str, int, str], ...] = (
    ("previous_week_low", 7, "PWL"),
    ("htf_4h_last_swing_low", 7, "4H_SSL"),
    ("previous_day_low", 6, "PDL"),
    ("htf_1h_last_swing_low", 6, "1H_SSL"),
    ("current_asia_low", 5, "ASIA_L"),
    ("current_london_open_low", 5, "LONDON_L"),
    ("equal_low_liquidity", 6, "EQL"),
    ("previous_4h_low", 4, "P4L"),
    ("last_swing_low", 4, "SSL"),
    ("previous_1h_low", 3, "P1L"),
    ("micro_last_swing_low", 2, "INTERNAL_SSL"),
)


def _liquidity_pools(row: pd.Series, high: bool, atr: float, tolerance_atr: float) -> list[_LiquidityPool]:
    sources = _HIGH_POOL_SOURCES if high else _LOW_POOL_SOURCES
    raw = [
        _LiquidityPool(float(row[name]), quality, kind)
        for name, quality, kind in sources
        if name in row.index and _finite(row.get(name))
    ]
    raw.sort(key=lambda item: item.price)
    tolerance = max(float(atr) * tolerance_atr, 1e-12)
    groups: list[list[_LiquidityPool]] = []
    for pool in raw:
        if groups and abs(pool.price - np.mean([item.price for item in groups[-1]])) <= tolerance:
            groups[-1].append(pool)
        else:
            groups.append([pool])
    result: list[_LiquidityPool] = []
    for group in groups:
        weights = np.asarray([max(item.quality, 1) for item in group], dtype=float)
        prices = np.asarray([item.price for item in group], dtype=float)
        result.append(
            _LiquidityPool(
                price=float(np.average(prices, weights=weights)),
                quality=max(item.quality for item in group),
                kind="+".join(sorted({item.kind for item in group})),
                confluence=len(group),
            )
        )
    return result


def _pool_key(pool: _LiquidityPool) -> tuple[str, float]:
    # A touch of an internal swing must not permanently consume a later PDH/PWH or
    # session pool merely because it formed at approximately the same price. Keep
    # source provenance and use fine scale-free log-price quantization.
    provenance = "+".join(sorted(part for part in pool.kind.split("+") if part)) or "LEVEL"
    return provenance, round(float(np.log(pool.price)), 6)


def _select_draw_target(
    pools: Iterable[_LiquidityPool],
    side: int,
    path_high: float,
    path_low: float,
    consumed: set[tuple[str, float]],
    minimum_quality: int = 4,
) -> _LiquidityPool | None:
    if side > 0:
        valid = [
            pool for pool in pools
            if pool.quality >= minimum_quality and pool.price > path_high and _pool_key(pool) not in consumed
        ]
        return min(valid, key=lambda pool: (pool.price, -pool.quality, -pool.confluence)) if valid else None
    valid = [
        pool for pool in pools
        if pool.quality >= minimum_quality and pool.price < path_low and _pool_key(pool) not in consumed
    ]
    return max(valid, key=lambda pool: (pool.price, pool.quality, pool.confluence)) if valid else None


def _displacement(row: pd.Series, side: int, config: CorpusAlphaConfig) -> bool:
    body = float(row.get("body_atr", 0.0)) if _finite(row.get("body_atr")) else 0.0
    range_atr = float(row.get("range_atr", 0.0)) if _finite(row.get("range_atr")) else 0.0
    close_location = float(row.get("close_location", 0.5)) if _finite(row.get("close_location")) else 0.5
    efficiency = abs(body) / max(range_atr, 1e-12)
    if side > 0:
        return (
            body >= config.displacement_body_atr
            and range_atr >= config.displacement_range_atr
            and close_location >= config.displacement_close_location
            and efficiency >= config.minimum_displacement_efficiency
        )
    return (
        body <= -config.displacement_body_atr
        and range_atr >= config.displacement_range_atr
        and close_location <= 1.0 - config.displacement_close_location
        and efficiency >= config.minimum_displacement_efficiency
    )


def _order_block_zone(features: pd.DataFrame, start_pos: int, end_pos: int, side: int) -> tuple[float, float] | None:
    if end_pos <= start_pos:
        return None
    segment = features.iloc[start_pos:end_pos]
    if side > 0:
        opposite = segment[segment["close"] < segment["open"]]
    else:
        opposite = segment[segment["close"] > segment["open"]]
    if opposite.empty:
        return None
    candle = opposite.iloc[-1]
    lower = float(min(candle["open"], candle["close"]))
    upper = float(max(candle["open"], candle["close"]))
    return (lower, upper) if upper > lower else None


def _fvg_zone(row: pd.Series, side: int) -> tuple[float, float] | None:
    if side > 0 and _finite(row.get("bull_fvg_lower")) and _finite(row.get("bull_fvg_upper")):
        lower, upper = float(row["bull_fvg_lower"]), float(row["bull_fvg_upper"])
    elif side < 0 and _finite(row.get("bear_fvg_lower")) and _finite(row.get("bear_fvg_upper")):
        lower, upper = float(row["bear_fvg_lower"]), float(row["bear_fvg_upper"])
    else:
        return None
    lower, upper = sorted((lower, upper))
    return (lower, upper) if upper > lower else None


def _choose_pd_array(
    features: pd.DataFrame,
    state: _NarrativeState,
    pos: int,
    atr: float,
) -> tuple[float, float, int, float, float] | None:
    row = features.iloc[pos]
    fvg = _fvg_zone(row, state.side)
    if state.ob_search_start is not None:
        ob_start = int(state.ob_search_start)
    else:
        ob_start = state.created_pos if state.created_pos < pos else max(0, pos - 12)
    ob_start = max(0, min(ob_start, max(0, pos - 1)))
    ob = _order_block_zone(features, ob_start, pos, state.side)
    fvg_width = ((fvg[1] - fvg[0]) / atr) if fvg else 0.0
    ob_width = ((ob[1] - ob[0]) / atr) if ob else 0.0
    if fvg and ob:
        overlap_lower = max(fvg[0], ob[0])
        overlap_upper = min(fvg[1], ob[1])
        if overlap_upper > overlap_lower:
            zone = (overlap_lower, overlap_upper)
            kind = 3
        else:
            zone = fvg
            kind = 2
    elif fvg:
        zone = fvg
        kind = 2
    elif ob:
        zone = ob
        kind = 1
    else:
        return None

    lower, upper = zone
    close = float(row["close"])
    if state.side > 0 and upper >= close:
        return None
    if state.side < 0 and lower <= close:
        return None
    return lower, upper, kind, fvg_width, ob_width


def _target_reached(row: pd.Series, state: _NarrativeState) -> bool:
    return float(row["high"]) >= state.draw_target if state.side > 0 else float(row["low"]) <= state.draw_target


def _stop_reached(row: pd.Series, state: _NarrativeState, stop: float) -> bool:
    return float(row["low"]) <= stop if state.side > 0 else float(row["high"]) >= stop


def _setup_features(
    row: pd.Series,
    state: _NarrativeState,
    pos: int,
    entry: float,
    stop: float,
) -> dict[str, float]:
    values = _numeric_row(row)
    atr = float(row["atr"])
    zone_mid = (float(state.zone_lower) + float(state.zone_upper)) / 2.0
    impulse_low = float(state.impulse_low if state.impulse_low is not None else state.path_low)
    impulse_high = float(state.impulse_high if state.impulse_high is not None else state.path_high)
    impulse_width = max(impulse_high - impulse_low, 1e-12)
    target_distance = abs(state.draw_target - entry)
    stop_distance = abs(entry - stop)
    range_position = (entry - impulse_low) / impulse_width
    retest_depth = (
        (float(state.zone_upper) - float(state.retest_extreme)) / max(float(state.zone_upper) - float(state.zone_lower), 1e-12)
        if state.side > 0 and state.retest_extreme is not None
        else (float(state.retest_extreme) - float(state.zone_lower)) / max(float(state.zone_upper) - float(state.zone_lower), 1e-12)
        if state.retest_extreme is not None
        else 0.0
    )
    values.update(
        {
            "setup_is_reversal": float(state.family == EventFamily.LIQUIDITY_SWEEP_REVERSAL),
            "narrative_age_bars": float(pos - state.created_pos),
            "confirmation_age_bars": float(pos - int(state.confirmation_pos or state.created_pos)),
            "sweep_depth_atr": float(state.sweep_depth_atr),
            "swept_level_count": float(state.swept_level_count),
            "liquidity_quality": float(state.liquidity_quality),
            "raid_reclaimed_same_bar": float(state.raid_reclaimed_same_bar),
            "draw_target_quality": float(state.draw_target_quality),
            "ob_search_age_bars": float(
                max(
                    0,
                    int(state.confirmation_pos or pos)
                    - int(state.ob_search_start if state.ob_search_start is not None else state.created_pos),
                )
            ),
            "confirmation_body_atr": float(state.confirmation_body_atr),
            "confirmation_volume_z": float(state.confirmation_volume_z),
            "displacement_efficiency_at_confirmation": float(state.displacement_efficiency),
            "fvg_width_atr": float(state.fvg_width_atr),
            "ob_width_atr": float(state.ob_width_atr),
            "pd_array_kind": float(state.zone_kind),
            "zone_width_atr": (float(state.zone_upper) - float(state.zone_lower)) / atr,
            "zone_midpoint_distance_atr": (entry - zone_mid) / atr,
            "impulse_range_position": float(range_position),
            "retest_depth_fraction": float(retest_depth),
            "retest_wait_bars": float(pos - int(state.first_retest_pos or pos)),
            "mitigation_count": float(state.mitigation_count),
            "entry_confirmation_kind": float(state.entry_confirmation_kind),
            "stop_distance_atr": stop_distance / atr,
            "target_distance_atr": target_distance / atr,
            "raw_structural_reward_risk": target_distance / max(stop_distance, 1e-12),
            "path_excursion_atr": (state.path_high - state.path_low) / atr,
            "htf_bias_alignment": float(state.side) * (
                float(row.get("htf_bias_score")) if _finite(row.get("htf_bias_score")) else 0.0
            ),
            "dealing_range_side_alignment": (
                1.0
                if (state.side > 0 and (float(row.get("dealing_range_position")) if _finite(row.get("dealing_range_position")) else 0.5) <= 0.5)
                or (state.side < 0 and (float(row.get("dealing_range_position")) if _finite(row.get("dealing_range_position")) else 0.5) >= 0.5)
                else 0.0
            ),
        }
    )
    return values


def _event_from_state(
    state: _NarrativeState,
    row: pd.Series,
    timestamp: pd.Timestamp,
    symbol: str,
    pos: int,
) -> EventCandidate | None:
    if state.stop is None or state.zone_lower is None or state.zone_upper is None:
        return None
    entry = float(row["close"])
    stop = float(state.stop)
    target = float(state.draw_target)
    if (state.side > 0 and not stop < entry < target) or (state.side < 0 and not target < entry < stop):
        return None
    return EventCandidate(
        timestamp=timestamp,
        symbol=symbol,
        family=state.family,
        side=state.side,
        decision_price=entry,
        entry_reference=entry,
        stop_reference=stop,
        target_reference=target,
        structural_level=float(state.structural_level),
        feature_row=_setup_features(row, state, pos, entry, stop),
    )


def _entry_confirmation(
    state: _NarrativeState,
    row: pd.Series,
    previous: pd.Series,
    config: CorpusAlphaConfig,
) -> int:
    """Return 0=no entry, 1=zone rejection, 2=later CISD confirmation."""

    midpoint = (float(state.zone_lower) + float(state.zone_upper)) / 2.0
    close = float(row["close"])
    body = float(row.get("body_atr", 0.0)) if _finite(row.get("body_atr")) else 0.0
    location = float(row.get("close_location", 0.5)) if _finite(row.get("close_location")) else 0.5
    if state.side > 0:
        same_bar_rejection = close > float(state.zone_upper) and body > 0 and location >= config.entry_close_location
        later_cisd = (
            state.first_retest_pos is not None
            and close > max(float(state.retest_trigger or midpoint), float(previous["high"]))
            and body > 0
        )
    else:
        same_bar_rejection = close < float(state.zone_lower) and body < 0 and location <= 1.0 - config.entry_close_location
        later_cisd = (
            state.first_retest_pos is not None
            and close < min(float(state.retest_trigger or midpoint), float(previous["low"]))
            and body < 0
        )
    if same_bar_rejection:
        return 1
    if later_cisd:
        return 2
    return 0


def _arm_displacement(
    state: _NarrativeState,
    features: pd.DataFrame,
    pos: int,
    config: CorpusAlphaConfig,
    diagnostics: Counter[str] | None = None,
) -> _NarrativeState | None:
    row = features.iloc[pos]
    if not _displacement(row, state.side, config):
        return state
    close = float(row["close"])
    if state.side > 0 and close <= state.internal_break:
        return state
    if state.side < 0 and close >= state.internal_break:
        return state
    _bump(diagnostics, "displacement_structure_confirmations")
    atr = float(row["atr"])
    zone = _choose_pd_array(features, state, pos, atr)
    if zone is None:
        _bump(diagnostics, "displacement_without_valid_pd_array")
        return state
    lower, upper, kind, fvg_width, ob_width = zone
    stop_buffer = config.stop_buffer_atr * atr
    stop = (
        float(state.stop)
        if state.stop is not None
        else state.origin_extreme - stop_buffer
        if state.side > 0
        else state.origin_extreme + stop_buffer
    )
    impulse_slice = features.iloc[state.created_pos : pos + 1]
    state.phase = "AWAIT_RETEST"
    state.confirmation_pos = pos
    state.zone_lower = lower
    state.zone_upper = upper
    state.zone_kind = kind
    state.stop = stop
    state.impulse_low = float(impulse_slice["low"].min())
    state.impulse_high = float(impulse_slice["high"].max())
    state.confirmation_body_atr = float(row.get("body_atr", 0.0))
    state.confirmation_volume_z = float(row.get("volume_z", 0.0)) if _finite(row.get("volume_z")) else 0.0
    state.displacement_efficiency = abs(float(row.get("body_atr", 0.0))) / max(float(row.get("range_atr", 0.0)), 1e-12)
    state.fvg_width_atr = fvg_width
    state.ob_width_atr = ob_width
    _bump(diagnostics, "pd_array_states_armed")
    return state


def _process_state(
    state: _NarrativeState,
    features: pd.DataFrame,
    pos: int,
    timestamp: pd.Timestamp,
    symbol: str,
    config: CorpusAlphaConfig,
    diagnostics: Counter[str] | None = None,
) -> tuple[_NarrativeState | None, EventCandidate | None]:
    row = features.iloc[pos]
    previous = features.iloc[pos - 1]
    state.path_high = max(state.path_high, float(row["high"]))
    state.path_low = min(state.path_low, float(row["low"]))
    atr = float(row["atr"])
    structural_stop = (
        float(state.stop)
        if state.stop is not None
        else state.origin_extreme - config.stop_buffer_atr * atr
        if state.side > 0
        else state.origin_extreme + config.stop_buffer_atr * atr
    )
    if _target_reached(row, state):
        _bump(diagnostics, "target_taken_before_entry")
        return None, None
    if _stop_reached(row, state, structural_stop):
        _bump(diagnostics, "structural_invalidation_before_entry")
        return None, None

    if state.phase == "AWAIT_DISPLACEMENT":
        if pos <= state.created_pos:
            return state, None
        return _arm_displacement(state, features, pos, config, diagnostics), None

    if state.confirmation_pos is None or pos <= state.confirmation_pos:
        return state, None
    tolerance = config.retest_tolerance_atr * atr
    touched = float(row["low"]) <= float(state.zone_upper) + tolerance and float(row["high"]) >= float(state.zone_lower) - tolerance
    if touched:
        state.mitigation_count += 1
        if state.first_retest_pos is None:
            state.first_retest_pos = pos
            _bump(diagnostics, "pd_array_first_mitigations")
        if state.side > 0:
            state.retest_extreme = min(float(state.retest_extreme or np.inf), float(row["low"]))
            if float(row["close"]) < float(row["open"]):
                state.retest_trigger = float(row["open"])
            elif state.retest_trigger is None:
                state.retest_trigger = float(state.zone_upper)
        else:
            state.retest_extreme = max(float(state.retest_extreme or -np.inf), float(row["high"]))
            if float(row["close"]) > float(row["open"]):
                state.retest_trigger = float(row["open"])
            elif state.retest_trigger is None:
                state.retest_trigger = float(state.zone_lower)

    if state.first_retest_pos is None:
        return state, None
    confirmation_kind = _entry_confirmation(state, row, previous, config)
    if confirmation_kind:
        state.entry_confirmation_kind = confirmation_kind
        event = _event_from_state(state, row, timestamp, symbol, pos)
        if event is not None:
            _bump(diagnostics, "entry_confirmations")
            _bump(
                diagnostics,
                "zone_rejection_entries" if confirmation_kind == 1 else "later_cisd_entries",
            )
        return None, event
    return state, None


def _new_reversal_states(
    features: pd.DataFrame,
    pos: int,
    consumed_high: set[tuple[str, float]],
    consumed_low: set[tuple[str, float]],
    config: CorpusAlphaConfig,
    diagnostics: Counter[str] | None = None,
) -> list[_NarrativeState]:
    row = features.iloc[pos]
    atr = float(row["atr"])
    buffer = config.sweep_buffer_atr * atr
    high_pools = _liquidity_pools(row, True, atr, config.liquidity_dedup_tolerance_atr)
    low_pools = _liquidity_pools(row, False, atr, config.liquidity_dedup_tolerance_atr)
    swept_highs = [
        pool
        for pool in high_pools
        if _pool_key(pool) not in consumed_high
        and float(row["high"]) > pool.price + buffer
    ]
    swept_lows = [
        pool
        for pool in low_pools
        if _pool_key(pool) not in consumed_low
        and float(row["low"]) < pool.price - buffer
    ]
    if swept_highs and swept_lows:
        _bump(diagnostics, "ambiguous_two_sided_raid_bars")
        return []

    timestamp = features.index[pos]
    states: list[_NarrativeState] = []
    swept_highs = [pool for pool in swept_highs if pool.quality >= 4]
    swept_lows = [pool for pool in swept_lows if pool.quality >= 4]
    if swept_highs or swept_lows:
        _bump(diagnostics, "external_liquidity_raids")
    if swept_highs:
        selected = max(swept_highs, key=lambda pool: (pool.quality, pool.price, pool.confluence))
        internal_break = row.get("micro_last_swing_low")
        if not _finite(internal_break):
            internal_break = row.get("internal_low_5")
        target = _select_draw_target(low_pools, -1, float(row["high"]), float(row["low"]), consumed_low)
        if not _finite(internal_break):
            _bump(diagnostics, "raid_missing_internal_structure")
        elif target is None:
            _bump(diagnostics, "raid_missing_opposing_draw")
        else:
            states.append(
                _NarrativeState(
                    family=EventFamily.LIQUIDITY_SWEEP_REVERSAL,
                    side=-1,
                    created_pos=pos,
                    created_at=timestamp,
                    structural_level=selected.price,
                    origin_extreme=float(row["high"]),
                    internal_break=float(internal_break),
                    draw_target=target.price,
                    draw_target_quality=target.quality,
                    swept_level_count=sum(pool.confluence for pool in swept_highs),
                    sweep_depth_atr=(float(row["high"]) - selected.price) / atr,
                    liquidity_quality=selected.quality,
                    raid_reclaimed_same_bar=bool(float(row["close"]) < selected.price),
                    stop=float(row["high"] + config.stop_buffer_atr * atr),
                    path_high=float(row["high"]),
                    path_low=float(row["low"]),
                )
            )
            _bump(diagnostics, "reversal_narratives_armed")
    if swept_lows:
        selected = max(swept_lows, key=lambda pool: (pool.quality, -pool.price, pool.confluence))
        internal_break = row.get("micro_last_swing_high")
        if not _finite(internal_break):
            internal_break = row.get("internal_high_5")
        target = _select_draw_target(high_pools, 1, float(row["high"]), float(row["low"]), consumed_high)
        if not _finite(internal_break):
            _bump(diagnostics, "raid_missing_internal_structure")
        elif target is None:
            _bump(diagnostics, "raid_missing_opposing_draw")
        else:
            states.append(
                _NarrativeState(
                    family=EventFamily.LIQUIDITY_SWEEP_REVERSAL,
                    side=1,
                    created_pos=pos,
                    created_at=timestamp,
                    structural_level=selected.price,
                    origin_extreme=float(row["low"]),
                    internal_break=float(internal_break),
                    draw_target=target.price,
                    draw_target_quality=target.quality,
                    swept_level_count=sum(pool.confluence for pool in swept_lows),
                    sweep_depth_atr=(selected.price - float(row["low"])) / atr,
                    liquidity_quality=selected.quality,
                    raid_reclaimed_same_bar=bool(float(row["close"]) > selected.price),
                    stop=float(row["low"] - config.stop_buffer_atr * atr),
                    path_high=float(row["high"]),
                    path_low=float(row["low"]),
                )
            )
            _bump(diagnostics, "reversal_narratives_armed")
    return states


def _last_level_origin_pos(
    features: pd.DataFrame,
    pos: int,
    value: float,
    side: int,
) -> int:
    """Locate the protected swing that owns a continuation OB search window."""

    segment = features.iloc[: pos + 1]
    series = segment["low"] if side > 0 else segment["high"]
    atr = float(features.iloc[pos]["atr"])
    tolerance = max(0.15 * atr, abs(float(value)) * 1e-8, 1e-12)
    matches = np.flatnonzero((series - float(value)).abs().le(tolerance).to_numpy())
    if len(matches):
        return int(matches[-1])
    return max(0, pos - 12)


def _new_continuation_state(
    features: pd.DataFrame,
    pos: int,
    side: int,
    consumed_high: set[tuple[str, float]],
    consumed_low: set[tuple[str, float]],
    config: CorpusAlphaConfig,
    diagnostics: Counter[str] | None = None,
) -> _NarrativeState | None:
    row = features.iloc[pos]
    previous = features.iloc[pos - 1]
    if not _displacement(row, side, config):
        return None
    bias = float(row.get("htf_bias_score", 0.0)) if _finite(row.get("htf_bias_score")) else 0.0
    if side * bias < config.strong_counter_bias_floor:
        _bump(diagnostics, "continuation_strong_counter_bias_rejections")
        return None
    if side > 0:
        break_level = previous.get("last_swing_high")
        if not _finite(break_level) or not (float(row["close"]) > float(break_level) and float(previous["close"]) <= float(break_level)):
            return None
        stop_anchor = row.get("micro_last_swing_low")
        high_pools = _liquidity_pools(row, True, float(row["atr"]), config.liquidity_dedup_tolerance_atr)
        target = _select_draw_target(high_pools, 1, float(row["high"]), float(row["low"]), consumed_high)
    else:
        break_level = previous.get("last_swing_low")
        if not _finite(break_level) or not (float(row["close"]) < float(break_level) and float(previous["close"]) >= float(break_level)):
            return None
        stop_anchor = row.get("micro_last_swing_high")
        low_pools = _liquidity_pools(row, False, float(row["atr"]), config.liquidity_dedup_tolerance_atr)
        target = _select_draw_target(low_pools, -1, float(row["high"]), float(row["low"]), consumed_low)
    _bump(diagnostics, "continuation_first_break_displacements")
    if target is None:
        _bump(diagnostics, "continuation_missing_external_draw")
        return None
    if not _finite(stop_anchor):
        stop_anchor = float(row["low"] if side > 0 else row["high"])
    ob_search_start = _last_level_origin_pos(features, pos, float(stop_anchor), side)
    state = _NarrativeState(
        family=EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION,
        side=side,
        created_pos=pos,
        created_at=features.index[pos],
        structural_level=float(break_level),
        origin_extreme=float(stop_anchor),
        internal_break=float(break_level),
        draw_target=target.price,
        draw_target_quality=target.quality,
        swept_level_count=0,
        sweep_depth_atr=0.0,
        liquidity_quality=0,
        ob_search_start=ob_search_start,
        path_high=float(row["high"]),
        path_low=float(row["low"]),
    )
    armed = _arm_displacement(state, features, pos, config, diagnostics)
    if armed is not None and armed.phase == "AWAIT_RETEST":
        _bump(diagnostics, "continuation_narratives_armed")
        return armed
    return None


def _mark_consumed(
    row: pd.Series,
    high_pools: Iterable[_LiquidityPool],
    low_pools: Iterable[_LiquidityPool],
    consumed_high: set[tuple[str, float]],
    consumed_low: set[tuple[str, float]],
) -> None:
    for pool in high_pools:
        if float(row["high"]) >= pool.price:
            consumed_high.add(_pool_key(pool))
    for pool in low_pools:
        if float(row["low"]) <= pool.price:
            consumed_low.add(_pool_key(pool))


def _generate_corpus_candidates(
    features: pd.DataFrame,
    symbol: str,
    config: CorpusAlphaConfig,
    diagnostics: Counter[str] | None,
) -> list[EventCandidate]:
    """Generate one coherent SMC/ICT narrative, not independently selected families."""

    required = {
        "open",
        "high",
        "low",
        "close",
        "atr",
        "body_atr",
        "range_atr",
        "close_location",
        "last_swing_high",
        "last_swing_low",
        "internal_high_5",
        "internal_low_5",
    }
    missing = required - set(features.columns)
    if missing:
        raise ValueError(f"corpus features missing required columns: {sorted(missing)}")

    states: list[_NarrativeState] = []
    events: list[EventCandidate] = []
    consumed_high: set[tuple[str, float]] = set()
    consumed_low: set[tuple[str, float]] = set()
    if len(features) > 0 and _finite(features.iloc[0].get("atr")) and float(features.iloc[0]["atr"]) > 0:
        first = features.iloc[0]
        first_atr = float(first["atr"])
        _mark_consumed(
            first,
            _liquidity_pools(first, True, first_atr, config.liquidity_dedup_tolerance_atr),
            _liquidity_pools(first, False, first_atr, config.liquidity_dedup_tolerance_atr),
            consumed_high,
            consumed_low,
        )

    for pos in range(1, len(features)):
        row = features.iloc[pos]
        if not _finite(row.get("atr")) or float(row["atr"]) <= 0:
            continue
        timestamp = features.index[pos]

        surviving: list[_NarrativeState] = []
        for state in states:
            updated, event = _process_state(state, features, pos, timestamp, symbol, config, diagnostics)
            if event is not None:
                events.append(event)
            if updated is not None:
                surviving.append(updated)
        states = surviving

        new_reversals = _new_reversal_states(features, pos, consumed_high, consumed_low, config, diagnostics)
        continuation_long = _new_continuation_state(features, pos, 1, consumed_high, consumed_low, config, diagnostics)
        continuation_short = _new_continuation_state(features, pos, -1, consumed_high, consumed_low, config, diagnostics)
        states.extend(new_reversals)
        if continuation_long is not None:
            states.append(continuation_long)
        if continuation_short is not None:
            states.append(continuation_short)

        atr = float(row["atr"])
        high_pools = _liquidity_pools(row, True, atr, config.liquidity_dedup_tolerance_atr)
        low_pools = _liquidity_pools(row, False, atr, config.liquidity_dedup_tolerance_atr)
        _mark_consumed(row, high_pools, low_pools, consumed_high, consumed_low)

        # Structural dominance only: a deeper, newer raid with the same draw supersedes
        # an older narrative.  No state is discarded merely because elapsed time passed.
        deduped: dict[tuple[EventFamily, int, float], _NarrativeState] = {}
        for state in states:
            key = (state.family, state.side, round(state.draw_target, 8))
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = state
            elif state.family == EventFamily.LIQUIDITY_SWEEP_REVERSAL:
                deeper = state.origin_extreme < existing.origin_extreme if state.side > 0 else state.origin_extreme > existing.origin_extreme
                if deeper:
                    deduped[key] = state
            elif state.created_pos > existing.created_pos:
                deduped[key] = state
        states = list(deduped.values())

    events.sort(key=lambda item: (item.timestamp, item.symbol, item.family.value, item.side))
    return events

def generate_corpus_candidates(
    features: pd.DataFrame,
    symbol: str,
    config: CorpusAlphaConfig = CorpusAlphaConfig(),
) -> list[EventCandidate]:
    return _generate_corpus_candidates(features, symbol, config, None)


def generate_corpus_candidates_with_diagnostics(
    features: pd.DataFrame,
    symbol: str,
    config: CorpusAlphaConfig = CorpusAlphaConfig(),
) -> tuple[list[EventCandidate], dict[str, int]]:
    diagnostics: Counter[str] = Counter()
    diagnostics["rows"] = int(len(features))
    events = _generate_corpus_candidates(features, symbol, config, diagnostics)
    diagnostics["final_candidates"] = int(len(events))
    diagnostics["reversal_candidates"] = sum(
        event.family == EventFamily.LIQUIDITY_SWEEP_REVERSAL for event in events
    )
    diagnostics["continuation_candidates"] = sum(
        event.family == EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION for event in events
    )
    return events, dict(sorted(diagnostics.items()))

