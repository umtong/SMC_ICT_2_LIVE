from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

import cross_venue_development_v2 as d2
import cross_venue_execution_v5 as base
import cross_venue_pilot as v1

CAUSAL_VERSION = base.CAUSAL_VERSION
BUCKET_US = base.BUCKET_US
EntryCandidateV5 = base.EntryCandidateV5
ExitResolutionV5 = base.ExitResolutionV5
FixedTradeV5 = base.FixedTradeV5
AccountTradeV5 = base.AccountTradeV5

_ORIGINAL_ENTRY_CANDIDATES = base._entry_candidates
_ORIGINAL_FIRST_QUOTE_INDEX = base._first_quote_index
_GUARD_PATCHED = False


def _first_quote_index_cached(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    cached = frame.attrs.get("_v5b_first_quote_index")
    if cached is not None:
        return cached
    raw = pd.to_numeric(frame["bn_first_event_us"], errors="coerce").to_numpy(float)
    positions = np.flatnonzero(np.isfinite(raw))
    times = raw[positions].astype(np.int64)
    if len(times) and np.any(np.diff(times) < 0):
        raise ValueError("Binance first local-arrival quote times are not monotonic")
    cached = (positions, times)
    frame.attrs["_v5b_first_quote_index"] = cached
    return cached


def _entry_candidates_with_funding_guard(
    frames: dict[tuple[str, str], object],
    events: Iterable[v1.Event],
    config: v1.Config,
) -> list[EntryCandidateV5]:
    candidates = _ORIGINAL_ENTRY_CANDIDATES(frames, events, config)
    guarded: list[EntryCandidateV5] = []
    for candidate in candidates:
        entry_ms = candidate.entry_us // 1_000
        # The latest causal exit includes the maximum hold, exit latency and the
        # bounded completed-bucket rounding allowance frozen by V5.
        latest_exit_us = (
            candidate.entry_us
            + config.hold_ms * 1_000
            + config.latency_ms * 1_000
            + 2 * BUCKET_US
        )
        latest_exit_ms = (latest_exit_us + 999) // 1_000
        if not d2.funding_collision(entry_ms, latest_exit_ms):
            guarded.append(candidate)
    return guarded


def patch_v5() -> None:
    global _GUARD_PATCHED
    base.patch_v5()
    if not _GUARD_PATCHED:
        base._first_quote_index = _first_quote_index_cached
        base._entry_candidates = _entry_candidates_with_funding_guard
        _GUARD_PATCHED = True


def timestamp_us(raw: str) -> int:
    return base.timestamp_us(raw)


def read_quotes_v5(path):
    return base.read_quotes_v5(path)


def align_v5(*args, **kwargs):
    return base.align_v5(*args, **kwargs)


def simulate_fixed_day_v5(*args, **kwargs):
    patch_v5()
    return base.simulate_fixed_day_v5(*args, **kwargs)


def apply_fixed_fee(*args, **kwargs):
    return base.apply_fixed_fee(*args, **kwargs)


def initial_account_state():
    return base.initial_account_state()


def simulate_account_day_v5(*args, **kwargs):
    patch_v5()
    return base.simulate_account_day_v5(*args, **kwargs)


def account_metrics_v5(*args, **kwargs):
    return base.account_metrics_v5(*args, **kwargs)
