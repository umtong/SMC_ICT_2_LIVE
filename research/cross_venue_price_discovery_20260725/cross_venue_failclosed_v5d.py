from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

import cross_venue_basis_v5d as basis_v5d
import cross_venue_execution_v5 as base
import cross_venue_execution_v5d as v5d
import cross_venue_pilot as v1

_PATCHED = False
_ORIGINAL_ENTRY_CANDIDATES = None
MAX_DELAY_US = v1.MAX_QUOTE_AGE_MS * 1_000
_STATE_COLUMNS = ("bn_mid", "bb_mid", "bn_spread", "bb_spread")
_INVALID_POSITIONS_CACHE_KEY = "_v5d_invalid_state_positions"


def _finite_state(row: pd.Series) -> bool:
    values = [row.get(name) for name in _STATE_COLUMNS]
    return all(value is not None and math.isfinite(float(value)) and float(value) > 0 for value in values)


def _invalid_state_positions(frame: pd.DataFrame) -> np.ndarray:
    """Index unavailable completed states once for an immutable aligned frame.

    V5D previously scanned the complete position interval one row at a time for
    every accepted trade. A pilot frame has roughly 864,000 completed 100-ms
    buckets, so the repeated scan dominated the otherwise vectorized replay.
    The aligned frame is immutable after construction. Searching the sorted
    invalid-position index returns the same first unavailable bucket without
    changing any signal, fill, latency, stop, exit, cost, slot or account path.
    """

    cached = frame.attrs.get(_INVALID_POSITIONS_CACHE_KEY)
    if cached is not None:
        return cached
    values = frame.loc[:, _STATE_COLUMNS].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    valid = np.isfinite(values).all(axis=1) & (values > 0).all(axis=1)
    positions = np.flatnonzero(~valid).astype(np.int64, copy=False)
    positions.setflags(write=False)
    frame.attrs[_INVALID_POSITIONS_CACHE_KEY] = positions
    return positions


def clear_frame_cache(frame: pd.DataFrame) -> None:
    frame.attrs.pop(_INVALID_POSITIONS_CACHE_KEY, None)


def _entry_candidates_failclosed(
    frames: dict[tuple[str, str], pd.DataFrame],
    events: Iterable[v1.Event],
    config: v1.Config,
) -> list[base.EntryCandidateV5]:
    if _ORIGINAL_ENTRY_CANDIDATES is None:
        raise RuntimeError("V5D fail-closed entry contract is not patched")
    candidates = _ORIGINAL_ENTRY_CANDIDATES(frames, events, config)
    accepted: list[base.EntryCandidateV5] = []
    for candidate in candidates:
        target_us = (candidate.event.decision_ms + config.latency_ms) * 1_000
        delay = candidate.entry_us - target_us
        frame = frames[candidate.key]
        if 0 <= delay <= MAX_DELAY_US and _finite_state(frame.iloc[candidate.entry_position]):
            accepted.append(candidate)
    return accepted


def _first_invalid_position(frame: pd.DataFrame, start: int, stop: int) -> int | None:
    if start < 0:
        start = 0
    stop = min(int(stop), len(frame) - 1)
    if start > stop:
        return None
    positions = _invalid_state_positions(frame)
    offset = int(np.searchsorted(positions, start, side="left"))
    if offset < len(positions) and int(positions[offset]) <= stop:
        return int(positions[offset])
    return None


def _position_at_boundary(frame: pd.DataFrame, boundary_us: int) -> int:
    index = frame.index.to_numpy(np.int64)
    boundary_ms = boundary_us // 1_000
    position = int(np.searchsorted(index, boundary_ms, side="right") - 1)
    return min(max(position, 0), len(index) - 1)


def _punitive_resolution(
    frame: pd.DataFrame,
    candidate: base.EntryCandidateV5,
    position: int,
    boundary_us: int,
    quantity: float,
    entry_price: float,
    fee_bps: float,
    nav: float,
    account_peak: float,
) -> base.ExitResolutionV5:
    side = candidate.event.side
    if side > 0:
        exit_price = np.finfo(float).tiny
    else:
        exit_price = entry_price + (2.0 * max(nav, 1.0)) / max(quantity, np.finfo(float).tiny)
    entry_fee = quantity * entry_price * fee_bps / 10_000.0
    exit_fee = quantity * exit_price * fee_bps / 10_000.0
    exit_nav = nav + side * quantity * (exit_price - entry_price) - entry_fee - exit_fee
    intratrade = base._drawdown(exit_nav, nav)
    path = base._drawdown(exit_nav, account_peak)
    exit_us = min(boundary_us, (int(frame.index[-1]) + v1.BUCKET_MS) * 1_000)
    return base.ExitResolutionV5(
        exit_position=position,
        exit_us=exit_us,
        exit_price=exit_price,
        exit_reason="source_gap_punitive_exit",
        exit_liquidity_overrun=True,
        trigger_boundary_us=boundary_us,
        maximum_intratrade_drawdown=intratrade,
        maximum_path_drawdown=path,
    )


def _resolve_exit_failclosed(
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
    if v5d._V5C_RESOLVE_EXIT is None:
        raise RuntimeError("V5D base resolver is not patched")
    try:
        result = v5d._V5C_RESOLVE_EXIT(
            frame,
            candidate,
            config,
            quantity,
            entry_price,
            stop_mid,
            fee_bps,
            nav,
            account_peak,
        )
    except ValueError:
        invalid = _first_invalid_position(frame, candidate.entry_position, len(frame) - 1)
        if invalid is None:
            raise
        boundary = (int(frame.index[invalid]) + v1.BUCKET_MS) * 1_000
        return _punitive_resolution(
            frame, candidate, invalid, boundary, quantity, entry_price, fee_bps, nav, account_peak
        )

    invalid = _first_invalid_position(frame, candidate.entry_position, result.exit_position)
    if invalid is not None:
        boundary = (int(frame.index[invalid]) + v1.BUCKET_MS) * 1_000
        return _punitive_resolution(
            frame, candidate, invalid, boundary, quantity, entry_price, fee_bps, nav, account_peak
        )
    exit_target_us = result.trigger_boundary_us + config.latency_ms * 1_000
    if result.exit_us - exit_target_us > MAX_DELAY_US:
        boundary = exit_target_us + MAX_DELAY_US
        position = _position_at_boundary(frame, boundary)
        return _punitive_resolution(
            frame,
            candidate,
            position,
            boundary,
            quantity,
            entry_price,
            fee_bps,
            nav,
            account_peak,
        )
    return result


def patch() -> None:
    global _PATCHED, _ORIGINAL_ENTRY_CANDIDATES
    basis_v5d.patch()
    v5d.patch_v5()
    if _PATCHED:
        return
    _ORIGINAL_ENTRY_CANDIDATES = base._entry_candidates
    base._entry_candidates = _entry_candidates_failclosed
    base._resolve_exit = _resolve_exit_failclosed
    _PATCHED = True
