from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import numpy as np
import pandas as pd

import cross_venue_execution_v5 as base
import cross_venue_execution_v5b as v5b
import cross_venue_pilot as v1

CAUSAL_VERSION = base.CAUSAL_VERSION
ENGINE_VERSION = "5C"
BUCKET_US = base.BUCKET_US
EntryCandidateV5 = base.EntryCandidateV5
ExitResolutionV5 = base.ExitResolutionV5
FixedTradeV5 = base.FixedTradeV5
AccountTradeV5 = base.AccountTradeV5

_V5B_ENTRY_CANDIDATES = None
_V5B_RESOLVE_EXIT = None
_PATCHED = False


def _require_aligned_boundaries(config: v1.Config, events: Iterable[v1.Event]) -> list[v1.Event]:
    event_list = list(events)
    if (config.latency_ms * 1_000) % BUCKET_US != 0:
        raise ValueError("V5C latency must align to the completed 100-ms grid")
    if (config.hold_ms * 1_000) % BUCKET_US != 0:
        raise ValueError("V5C maximum hold must align to the completed 100-ms grid")
    for event in event_list:
        if (event.decision_ms * 1_000) % BUCKET_US != 0:
            raise ValueError("V5C decision must align to the completed 100-ms grid")
    return event_list


def _entry_candidates_v5c(
    frames: dict[tuple[str, str], pd.DataFrame],
    events: Iterable[v1.Event],
    config: v1.Config,
) -> list[EntryCandidateV5]:
    if _V5B_ENTRY_CANDIDATES is None:
        raise RuntimeError("V5C entry contract was not patched")
    return _V5B_ENTRY_CANDIDATES(frames, _require_aligned_boundaries(config, events), config)


def _trigger_bucket_position(frame: pd.DataFrame, trigger_boundary_us: int) -> int:
    bucket_start_ms = trigger_boundary_us // 1_000 - v1.BUCKET_MS
    index = frame.index.to_numpy(np.int64)
    position = int(np.searchsorted(index, bucket_start_ms, side="left"))
    if position >= len(index) or int(index[position]) != bucket_start_ms:
        raise ValueError("V5C stop trigger boundary is absent from the aligned frame")
    return position


def _resolve_exit_v5c(
    frame: pd.DataFrame,
    candidate: EntryCandidateV5,
    config: v1.Config,
    quantity: float,
    entry_price: float,
    stop_mid: float,
    fee_bps: float,
    nav: float,
    account_peak: float,
) -> ExitResolutionV5:
    if _V5B_RESOLVE_EXIT is None:
        raise RuntimeError("V5C exit contract was not patched")
    result = _V5B_RESOLVE_EXIT(
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
    if result.exit_reason != "protective_stop":
        return result

    trigger_position = _trigger_bucket_position(frame, result.trigger_boundary_us)
    trigger_quote = base._quote_from_bucket_extreme(frame.iloc[trigger_position], candidate.event.side)
    if trigger_quote is None:
        raise ValueError("V5C protective-stop bucket has no usable executable extremum")
    trigger_price, trigger_overrun = base._mandatory_exit(trigger_quote, candidate.event.side, quantity)
    if candidate.event.side > 0:
        adverse_exit_price = min(result.exit_price, trigger_price)
    else:
        adverse_exit_price = max(result.exit_price, trigger_price)

    entry_fee = quantity * entry_price * fee_bps / 10_000.0
    exit_fee = quantity * adverse_exit_price * fee_bps / 10_000.0
    exit_nav = (
        nav
        + candidate.event.side * quantity * (adverse_exit_price - entry_price)
        - entry_fee
        - exit_fee
    )
    intratrade = max(result.maximum_intratrade_drawdown, base._drawdown(exit_nav, nav))
    path = max(result.maximum_path_drawdown, base._drawdown(exit_nav, account_peak))
    return replace(
        result,
        exit_price=adverse_exit_price,
        exit_liquidity_overrun=result.exit_liquidity_overrun or trigger_overrun,
        maximum_intratrade_drawdown=intratrade,
        maximum_path_drawdown=path,
    )


def patch_v5() -> None:
    global _PATCHED, _V5B_ENTRY_CANDIDATES, _V5B_RESOLVE_EXIT
    v5b.patch_v5()
    if _PATCHED:
        return
    _V5B_ENTRY_CANDIDATES = base._entry_candidates
    _V5B_RESOLVE_EXIT = base._resolve_exit
    base._entry_candidates = _entry_candidates_v5c
    base._resolve_exit = _resolve_exit_v5c
    _PATCHED = True


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
    patch_v5()
    return base.account_metrics_v5(*args, **kwargs)
