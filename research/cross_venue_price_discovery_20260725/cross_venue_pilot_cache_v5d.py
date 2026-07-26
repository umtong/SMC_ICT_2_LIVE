from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import pandas as pd

import cross_venue_execution_v5 as base
import cross_venue_pilot as v1
import cross_venue_signals_v5d as signals

_PATCHED = False
_ORIGINAL_SIMULATE_FIXED_DAY = base.simulate_fixed_day_v5
_CACHE: dict[tuple, tuple[str, list[base.FixedTradeV5]]] = {}


def clear() -> None:
    _CACHE.clear()


def _frame_key(frames: dict[tuple[str, str], pd.DataFrame]) -> tuple:
    return tuple(sorted((day, symbol, id(frame)) for (day, symbol), frame in frames.items()))


def _event_boundary(event: v1.Event | None) -> tuple | None:
    if event is None:
        return None
    return (
        event.day,
        event.symbol,
        event.family,
        int(event.decision_ms),
        int(event.side),
        float(event.score),
        float(event.initial_basis_residual),
    )


def semantic_execution_key(
    frames: dict[tuple[str, str], pd.DataFrame],
    events: list[v1.Event],
    config: v1.Config,
) -> tuple:
    """Identify configurations that have exactly the same gross execution path.

    ``signal_signature`` already contains every configuration field used by the
    V5D signal builder. Gross fixed-notional execution then depends only on the
    immutable frames, event sequence, latency, hold and stop. Some dimensions
    in the original 768-row Cartesian grid are intentionally irrelevant for a
    given family; preserving their config IDs does not require replaying the
    same entries and exits repeatedly.
    """

    return (
        _frame_key(frames),
        signals.signal_signature(config),
        int(config.latency_ms),
        int(config.hold_ms),
        float(config.stop_spreads),
        len(events),
        _event_boundary(events[0] if events else None),
        _event_boundary(events[-1] if events else None),
    )


def simulate_fixed_day_cached(
    frames: dict[tuple[str, str], pd.DataFrame],
    events: Iterable[v1.Event],
    config: v1.Config,
) -> list[base.FixedTradeV5]:
    event_list = events if isinstance(events, list) else list(events)
    key = semantic_execution_key(frames, event_list, config)
    cached = _CACHE.get(key)
    if cached is None:
        trades = _ORIGINAL_SIMULATE_FIXED_DAY(frames, event_list, config)
        _CACHE[key] = (config.config_id, trades)
        return trades

    source_config_id, trades = cached
    if source_config_id == config.config_id:
        return trades
    return [replace(trade, config_id=config.config_id) for trade in trades]


def patch() -> None:
    global _PATCHED
    if _PATCHED:
        return
    base.simulate_fixed_day_v5 = simulate_fixed_day_cached
    _PATCHED = True
