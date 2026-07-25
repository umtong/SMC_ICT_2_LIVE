from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

import cross_venue_pilot as v1
import cross_venue_pilot_v2 as v2

_ORIGINAL_SIGNAL_EVENTS_V2 = v2.signal_events_v2
_PATCHED = False


def _rolling_sum(values: pd.Series, bins: int) -> pd.Series:
    return values.rolling(bins, min_periods=bins).sum()


def _common(frame: pd.DataFrame) -> dict[str, pd.Series]:
    cached = frame.attrs.get("_v5b_signal_common")
    if cached is not None:
        return cached
    bn_log = np.log(frame.bn_mid)
    bb_log = np.log(frame.bb_mid)
    basis = bb_log - bn_log
    basis_history = basis.shift(1)
    basis_mean = basis_history.rolling(600, min_periods=300).mean()
    basis_std = basis_history.rolling(600, min_periods=300).std(ddof=0).replace(0, np.nan)
    basis_residual = basis - basis_mean
    cached = {
        "bn_log": bn_log,
        "bb_log": bb_log,
        "basis_residual": basis_residual,
        "basis_z": basis_residual / basis_std,
        "basis_residual_diff": basis_residual.diff(),
        "bybit_spread_log": frame.bb_spread / frame.bb_mid,
        "binance_spread_log": frame.bn_spread / frame.bn_mid,
    }
    frame.attrs["_v5b_signal_common"] = cached
    return cached


def _observation(frame: pd.DataFrame, observation_ms: int) -> dict[str, pd.Series]:
    cache = frame.attrs.setdefault("_v5b_signal_observation", {})
    cached = cache.get(observation_ms)
    if cached is not None:
        return cached
    common = _common(frame)
    bins = max(1, observation_ms // v1.BUCKET_MS)
    short_bins = max(1, min(5, bins // 2))
    bn_flow_den = _rolling_sum(frame.bn_trade_notional, bins).replace(0, np.nan)
    bb_flow_den = _rolling_sum(frame.bb_trade_notional, bins).replace(0, np.nan)
    cached = {
        **common,
        "bn_ret": common["bn_log"] - common["bn_log"].shift(bins),
        "bb_ret": common["bb_log"] - common["bb_log"].shift(bins),
        "bn_flow": _rolling_sum(frame.bn_signed_notional, bins) / bn_flow_den,
        "bb_flow": _rolling_sum(frame.bb_signed_notional, bins) / bb_flow_den,
        "bn_flow_short": (
            _rolling_sum(frame.bn_signed_notional, short_bins)
            / _rolling_sum(frame.bn_trade_notional, short_bins).replace(0, np.nan)
        ),
    }
    cache[observation_ms] = cached
    return cached


def signal_signature(config: v1.Config) -> tuple[Any, ...]:
    if config.family in {"bybit_to_binance_propagation", "binance_overshoot_fade"}:
        return (
            config.family,
            config.observation_ms,
            config.displacement_spreads,
            config.flow_imbalance,
            config.follower_fraction,
            config.hold_ms,
        )
    return (
        config.family,
        config.observation_ms,
        config.hold_ms,
        config.basis_z,
    )


def signal_events_v5b(
    frame: pd.DataFrame,
    config: v1.Config,
    day: str,
    symbol: str,
) -> list[v1.Event]:
    signature = signal_signature(config)
    event_cache = frame.attrs.setdefault("_v5b_signal_events", {})
    key = (day, symbol, signature)
    cached = event_cache.get(key)
    if cached is not None:
        return cached

    values = _observation(frame, config.observation_ms)
    bn_ret = values["bn_ret"]
    bb_ret = values["bb_ret"]
    bn_flow = values["bn_flow"]
    bb_flow = values["bb_flow"]
    bn_flow_short = values["bn_flow_short"]
    basis_residual = values["basis_residual"]
    basis_z = values["basis_z"]
    bybit_spread_log = values["bybit_spread_log"]
    binance_spread_log = values["binance_spread_log"]

    if config.family == "bybit_to_binance_propagation":
        direction = np.sign(bb_ret)
        displacement = bb_ret.abs() / bybit_spread_log.replace(0, np.nan)
        response = direction * bn_ret / bb_ret.abs().replace(0, np.nan)
        cross_gap = direction * basis_residual
        mask = (
            (displacement >= config.displacement_spreads)
            & (direction * bb_flow >= config.flow_imbalance)
            & (response >= -0.25)
            & (response <= config.follower_fraction)
            & (direction * bn_flow >= -0.20)
            & (cross_gap > 0)
        )
        score = displacement + direction * bb_flow + cross_gap / bybit_spread_log.replace(0, np.nan)
        sides = direction
    elif config.family == "binance_overshoot_fade":
        direction = np.sign(bn_ret)
        displacement = bn_ret.abs() / binance_spread_log.replace(0, np.nan)
        bybit_response = direction * bb_ret / bn_ret.abs().replace(0, np.nan)
        overshoot = -direction * basis_residual
        mask = (
            (displacement >= config.displacement_spreads)
            & (direction * bn_flow >= config.flow_imbalance)
            & (bybit_response >= -0.25)
            & (bybit_response <= config.follower_fraction)
            & (direction * bn_flow_short <= 0.20)
            & (overshoot > 0)
        )
        score = displacement + direction * bn_flow + overshoot / binance_spread_log.replace(0, np.nan)
        sides = -direction
    else:
        direction = np.sign(bn_ret + bb_ret)
        both = (direction * bn_ret > 0) & (direction * bb_ret > 0)
        contracting = basis_residual * values["basis_residual_diff"] < 0
        mask = (
            both
            & (basis_z.abs() >= config.basis_z)
            & contracting
            & (direction * bn_flow >= -0.20)
            & (direction * bb_flow >= -0.20)
        )
        score = (
            basis_z.abs()
            + bn_ret.abs() / binance_spread_log.replace(0, np.nan)
            + bb_ret.abs() / bybit_spread_log.replace(0, np.nan)
        )
        sides = np.sign(basis_residual)

    mask = mask.fillna(False) & mask.shift(1, fill_value=False).eq(False) & sides.ne(0)
    raw = np.flatnonzero(mask.to_numpy())
    cooldown_bins = max(10, config.hold_ms // v1.BUCKET_MS)
    next_free = -1
    events: list[v1.Event] = []
    for position in raw:
        if position < next_free:
            continue
        decision_ms = int(frame.index[position]) + v1.BUCKET_MS
        events.append(
            v1.Event(
                day,
                symbol,
                config.family,
                decision_ms,
                int(sides.iloc[position]),
                float(score.iloc[position]),
                float(basis_residual.iloc[position]),
            )
        )
        next_free = position + cooldown_bins
    event_cache[key] = events
    return events


def patch() -> None:
    global _PATCHED
    if _PATCHED:
        return
    v2.signal_events_v2 = signal_events_v5b
    v1.signal_events = signal_events_v5b
    _PATCHED = True
