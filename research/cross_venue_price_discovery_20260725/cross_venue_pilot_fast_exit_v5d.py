from __future__ import annotations

import math
from dataclasses import asdict
from typing import Iterable

import numpy as np
import pandas as pd

import cross_venue_execution_v5 as base
import cross_venue_execution_v5c as v5c
import cross_venue_pilot as v1
import cross_venue_pilot_cache_v5d as pilot_cache

_PATCHED = False
_ORIGINAL_CORE_RESOLVER = None


def _arrays(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    cached = frame.attrs.get("_v5d_fast_exit_arrays")
    if cached is not None:
        return cached
    base._prepare_basis(frame)
    index = frame.index.to_numpy(np.int64)
    bucket_end_us = (index + v1.BUCKET_MS) * 1_000
    basis = pd.to_numeric(frame["_v5_basis"], errors="coerce").to_numpy(float)
    median = pd.to_numeric(frame["_v5_basis_median"], errors="coerce").to_numpy(float)
    cached = {
        "bucket_end_us": bucket_end_us,
        "low_bid": pd.to_numeric(frame["bn_low_bid"], errors="coerce").to_numpy(float),
        "high_ask": pd.to_numeric(frame["bn_high_ask"], errors="coerce").to_numpy(float),
        "basis_residual": basis - median,
    }
    for value in cached.values():
        value.setflags(write=False)
    frame.attrs["_v5d_fast_exit_arrays"] = cached
    return cached


def _first_true(mask: np.ndarray) -> int | None:
    positions = np.flatnonzero(mask)
    return int(positions[0]) if len(positions) else None


def resolve_exit_without_unused_drawdown(
    frame: pd.DataFrame,
    candidate: base.EntryCandidateV5,
    config: v1.Config,
    quantity: float,
    entry_price: float,
    stop_mid: float,
    fee_bps: float,
    nav: float,
    account_peak: float,
) -> base.ExitResolutionV5:
    """Match the frozen V5 core exit while omitting unused pilot drawdown marks.

    V5C still applies adverse protective-stop pricing and V5D fail-closed logic
    still applies source-gap and delayed-exit penalties around this core resolver.
    Only the fixed-notional pilot calls this implementation. Account-level
    development continues to use the original resolver with complete drawdowns.
    """

    values = _arrays(frame)
    event = candidate.event
    entry_position = candidate.entry_position
    entry_us = candidate.entry_us
    horizon_us = entry_us + config.hold_ms * 1_000
    horizon_boundary_us = (
        (horizon_us + base.BUCKET_US - 1) // base.BUCKET_US
    ) * base.BUCKET_US
    bucket_end_us = values["bucket_end_us"]
    horizon_position = int(
        np.searchsorted(bucket_end_us, horizon_boundary_us, side="left")
    )
    if horizon_position >= len(frame):
        raise ValueError(
            "V5 position reached the fixed source boundary without a causal exit trigger"
        )

    stop_slice = slice(entry_position, horizon_position + 1)
    if event.side > 0:
        adverse = values["low_bid"][stop_slice]
        stop_mask = np.isfinite(adverse) & (adverse <= stop_mid)
    else:
        adverse = values["high_ask"][stop_slice]
        stop_mask = np.isfinite(adverse) & (adverse >= stop_mid)
    stop_offset = _first_true(stop_mask)
    stop_position = (
        entry_position + stop_offset if stop_offset is not None else None
    )

    convergence_position: int | None = None
    initial_gap = abs(event.initial_basis_residual)
    if initial_gap > 0 and horizon_position > entry_position + 1:
        start = entry_position + 1
        stop = horizon_position
        residual = values["basis_residual"][start:stop]
        convergence_mask = np.isfinite(residual) & (
            np.abs(residual) <= 0.25 * initial_gap
        )
        convergence_offset = _first_true(convergence_mask)
        if convergence_offset is not None:
            convergence_position = start + convergence_offset

    positions = [horizon_position]
    if stop_position is not None:
        positions.append(stop_position)
    if convergence_position is not None:
        positions.append(convergence_position)
    trigger_position = min(positions)
    if stop_position is not None and stop_position == trigger_position:
        reason = "protective_stop"
        trigger_boundary_us = int(bucket_end_us[trigger_position])
    elif trigger_position == horizon_position:
        reason = "horizon"
        trigger_boundary_us = int(horizon_boundary_us)
    else:
        reason = "cross_venue_convergence"
        trigger_boundary_us = int(bucket_end_us[trigger_position])

    exit_target_us = trigger_boundary_us + config.latency_ms * 1_000
    found = base._first_quote_after(frame, exit_target_us)
    if found is None:
        raise ValueError("V5 accepted entry has no actual Binance quote after exit latency")
    exit_position, exit_us = found
    exit_quote = base._quote_from_first(
        frame.iloc[exit_position], event.side, entering=False
    )
    if exit_quote is None:
        raise ValueError("V5 exit first-quote group is unusable")
    exit_price, overrun = base._mandatory_exit(exit_quote, event.side, quantity)
    return base.ExitResolutionV5(
        exit_position=exit_position,
        exit_us=exit_us,
        exit_price=exit_price,
        exit_reason=reason,
        exit_liquidity_overrun=overrun,
        trigger_boundary_us=trigger_boundary_us,
        maximum_intratrade_drawdown=0.0,
        maximum_path_drawdown=0.0,
    )


def simulate_fixed_day_fast(
    frames: dict[tuple[str, str], pd.DataFrame],
    events: Iterable[v1.Event],
    config: v1.Config,
) -> list[base.FixedTradeV5]:
    trades: list[base.FixedTradeV5] = []
    free_time_us = -1
    for candidate in base._entry_candidates(frames, events, config):
        if candidate.entry_us < free_time_us:
            continue
        frame = frames[candidate.key]
        event = candidate.event
        entry_quote = base._quote_from_first(
            frame.iloc[candidate.entry_position], event.side, entering=True
        )
        if entry_quote is None:
            continue
        reference = entry_quote["ask"] if event.side > 0 else entry_quote["bid"]
        quantity = v1.FIXED_NOTIONAL / reference
        entry_fill = base._entry_fill(entry_quote, event.side, quantity)
        if entry_fill is None:
            continue
        entry_price, entry_spread = entry_fill
        entry_mid = (entry_quote["bid"] + entry_quote["ask"]) / 2.0
        stop_mid = entry_mid - event.side * config.stop_spreads * entry_spread
        resolved = base._resolve_exit(
            frame,
            candidate,
            config,
            quantity,
            entry_price,
            stop_mid,
            0.0,
            v1.FIXED_NOTIONAL,
            v1.FIXED_NOTIONAL,
        )
        gross_bps = event.side * math.log(
            resolved.exit_price / entry_price
        ) * 10_000.0
        spread_bps = entry_spread / entry_mid * 10_000.0
        trades.append(
            base.FixedTradeV5(
                config.config_id,
                event.day,
                event.symbol,
                event.family,
                event.decision_ms,
                candidate.entry_us // 1_000,
                resolved.exit_us // 1_000,
                candidate.entry_us,
                resolved.exit_us,
                event.side,
                entry_price,
                resolved.exit_price,
                gross_bps,
                spread_bps,
                0.0,
                gross_bps,
                resolved.exit_reason,
                event.score,
                resolved.exit_liquidity_overrun,
                resolved.trigger_boundary_us,
            )
        )
        free_time_us = resolved.exit_us + base.BUCKET_US
    return trades


def patch() -> None:
    global _PATCHED, _ORIGINAL_CORE_RESOLVER
    if _PATCHED:
        return
    if v5c._V5B_RESOLVE_EXIT is None:
        raise RuntimeError("V5C must be patched before the fast pilot resolver")
    _ORIGINAL_CORE_RESOLVER = v5c._V5B_RESOLVE_EXIT
    v5c._V5B_RESOLVE_EXIT = resolve_exit_without_unused_drawdown
    pilot_cache._ORIGINAL_SIMULATE_FIXED_DAY = simulate_fixed_day_fast
    _PATCHED = True


def _synthetic_frame() -> pd.DataFrame:
    start_ms = 1_672_531_200_000
    index = np.arange(start_ms, start_ms + 20_000, v1.BUCKET_MS, dtype=np.int64)
    n = len(index)
    mid = np.full(n, 100.0)
    bid = mid - 0.05
    ask = mid + 0.05
    event_us = index * 1_000 + 10_000
    frame = pd.DataFrame(
        {
            "bn_mid": mid,
            "bb_mid": mid + 0.20,
            "bn_spread": ask - bid,
            "bb_spread": np.full(n, 0.10),
            "bn_first_event_us": event_us,
            "bn_first_bid": bid,
            "bn_first_bid_amount": np.full(n, 1000.0),
            "bn_first_bid_ask": ask,
            "bn_first_bid_ask_amount": np.full(n, 1000.0),
            "bn_first_ask_bid": bid,
            "bn_first_ask_bid_amount": np.full(n, 1000.0),
            "bn_first_ask": ask,
            "bn_first_ask_amount": np.full(n, 1000.0),
            "bn_low_bid": bid,
            "bn_low_bid_amount": np.full(n, 1000.0),
            "bn_low_bid_ask": ask,
            "bn_low_bid_ask_amount": np.full(n, 1000.0),
            "bn_high_ask_bid": bid,
            "bn_high_ask_bid_amount": np.full(n, 1000.0),
            "bn_high_ask": ask,
            "bn_high_ask_amount": np.full(n, 1000.0),
            "bn_trade_notional": np.zeros(n),
            "bb_trade_notional": np.zeros(n),
            "bn_signed_notional": np.zeros(n),
            "bb_signed_notional": np.zeros(n),
        },
        index=index,
    )
    frame["_v5_basis"] = np.log(frame.bb_mid) - np.log(frame.bn_mid)
    frame["_v5_basis_median"] = frame["_v5_basis"] + 1.0
    frame.attrs["_v5d_basis_prepared"] = True
    return frame


def self_test() -> None:
    if _ORIGINAL_CORE_RESOLVER is None:
        raise RuntimeError("call patch() before self_test()")
    frame = _synthetic_frame()
    config = v1.Config(
        "bybit_to_binance_propagation",
        1000,
        2.0,
        0.4,
        0.5,
        100,
        3000,
        2.0,
        2.0,
    )
    day = "2023-01-01"
    decision_ms = int(frame.index[10])
    event = v1.Event(
        day,
        "BTCUSDT",
        config.family,
        decision_ms,
        1,
        3.0,
        1.0,
    )
    frames = {(day, "BTCUSDT"): frame}
    candidates = base._entry_candidates(frames, [event], config)
    assert len(candidates) == 1
    candidate = candidates[0]
    quote = base._quote_from_first(
        frame.iloc[candidate.entry_position], 1, entering=True
    )
    assert quote is not None
    quantity = v1.FIXED_NOTIONAL / quote["ask"]
    entry_price, spread = base._entry_fill(quote, 1, quantity)
    stop_mid = (quote["bid"] + quote["ask"]) / 2.0 - 2.0 * spread

    original = _ORIGINAL_CORE_RESOLVER(
        frame,
        candidate,
        config,
        quantity,
        entry_price,
        stop_mid,
        0.0,
        v1.FIXED_NOTIONAL,
        v1.FIXED_NOTIONAL,
    )
    fast = resolve_exit_without_unused_drawdown(
        frame,
        candidate,
        config,
        quantity,
        entry_price,
        stop_mid,
        0.0,
        v1.FIXED_NOTIONAL,
        v1.FIXED_NOTIONAL,
    )
    left = asdict(original)
    right = asdict(fast)
    left["maximum_intratrade_drawdown"] = 0.0
    left["maximum_path_drawdown"] = 0.0
    assert left == right, {"original": left, "fast": right}

    stop_frame = _synthetic_frame()
    stop_frame.loc[stop_frame.index[15], "bn_low_bid"] = 99.0
    stop_frame.attrs["_v5d_basis_prepared"] = True
    stop_frames = {(day, "BTCUSDT"): stop_frame}
    stop_candidate = base._entry_candidates(stop_frames, [event], config)[0]
    stop_quote = base._quote_from_first(
        stop_frame.iloc[stop_candidate.entry_position], 1, entering=True
    )
    assert stop_quote is not None
    stop_quantity = v1.FIXED_NOTIONAL / stop_quote["ask"]
    stop_entry, stop_spread = base._entry_fill(stop_quote, 1, stop_quantity)
    stop_level = (
        (stop_quote["bid"] + stop_quote["ask"]) / 2.0 - 2.0 * stop_spread
    )
    original_stop = _ORIGINAL_CORE_RESOLVER(
        stop_frame,
        stop_candidate,
        config,
        stop_quantity,
        stop_entry,
        stop_level,
        0.0,
        v1.FIXED_NOTIONAL,
        v1.FIXED_NOTIONAL,
    )
    fast_stop = resolve_exit_without_unused_drawdown(
        stop_frame,
        stop_candidate,
        config,
        stop_quantity,
        stop_entry,
        stop_level,
        0.0,
        v1.FIXED_NOTIONAL,
        v1.FIXED_NOTIONAL,
    )
    left_stop = asdict(original_stop)
    right_stop = asdict(fast_stop)
    left_stop["maximum_intratrade_drawdown"] = 0.0
    left_stop["maximum_path_drawdown"] = 0.0
    assert left_stop == right_stop, {
        "original": left_stop,
        "fast": right_stop,
    }
    print("V5D_FAST_FIXED_PILOT_EXIT_EQUIVALENCE_PASS")
