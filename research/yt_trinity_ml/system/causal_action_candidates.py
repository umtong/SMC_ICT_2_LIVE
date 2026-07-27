from __future__ import annotations

from collections import Counter
from typing import Mapping

import numpy as np
import pandas as pd

from .core import EventCandidate, EventFamily, FeatureConfig
from .corpus_alpha import (
    CorpusAlphaConfig,
    _NarrativeState,
    _finite,
    _liquidity_pools,
    _mark_consumed,
    _new_continuation_state,
    _new_reversal_states,
    _process_state,
    _setup_features,
    build_corpus_features,
)


def _passive_event(
    state: _NarrativeState,
    row: pd.Series,
    timestamp: pd.Timestamp,
    symbol: str,
    pos: int,
) -> EventCandidate | None:
    """Create the limit action exactly when displacement arms its PD array."""

    if state.phase != "AWAIT_RETEST":
        return None
    if state.stop is None or state.zone_lower is None or state.zone_upper is None:
        return None
    entry = (float(state.zone_lower) + float(state.zone_upper)) / 2.0
    stop = float(state.stop)
    target = float(state.draw_target)
    if (state.side > 0 and not stop < entry < target) or (
        state.side < 0 and not target < entry < stop
    ):
        return None
    features = _setup_features(row, state, pos, entry, stop)
    features.update(
        {
            "action_candidate_early_passive": 1.0,
            "action_candidate_confirmed_market": 0.0,
            "entry_confirmation_kind": 0.0,
            "causal_pd_array_armed": 1.0,
        }
    )
    return EventCandidate(
        timestamp=timestamp,
        symbol=symbol,
        family=state.family,
        side=state.side,
        decision_price=float(row["close"]),
        entry_reference=entry,
        stop_reference=stop,
        target_reference=target,
        structural_level=float(state.structural_level),
        feature_row=features,
    )


def _market_event(event: EventCandidate) -> EventCandidate:
    features = dict(event.feature_row)
    features.update(
        {
            "action_candidate_early_passive": 0.0,
            "action_candidate_confirmed_market": 1.0,
            "causal_pd_array_armed": 1.0,
        }
    )
    return EventCandidate(
        timestamp=event.timestamp,
        symbol=event.symbol,
        family=event.family,
        side=event.side,
        decision_price=event.decision_price,
        entry_reference=event.entry_reference,
        stop_reference=event.stop_reference,
        target_reference=event.target_reference,
        structural_level=event.structural_level,
        feature_row=features,
    )


def generate_causal_action_candidates(
    features: pd.DataFrame,
    symbol: str,
    config: CorpusAlphaConfig = CorpusAlphaConfig(),
) -> tuple[list[EventCandidate], dict[str, int]]:
    """Emit every causal PD-array limit and every later confirmed market action.

    Passive candidates do not depend on a future mitigation or CISD. Market candidates
    remain contingent on the later confirmed event. Both belong to the same underlying
    SMC/ICT delivery narrative and share its frozen structural stop and liquidity draw.
    """

    required = {
        "open", "high", "low", "close", "atr", "body_atr", "range_atr",
        "close_location", "last_swing_high", "last_swing_low",
        "internal_high_5", "internal_low_5",
    }
    missing = required - set(features.columns)
    if missing:
        raise ValueError(f"causal action features missing required columns: {sorted(missing)}")

    diagnostics: Counter[str] = Counter()
    diagnostics["rows"] = int(len(features))
    states: list[_NarrativeState] = []
    events: list[EventCandidate] = []
    consumed_high: set[tuple[str, float]] = set()
    consumed_low: set[tuple[str, float]] = set()

    if len(features) and _finite(features.iloc[0].get("atr")) and float(features.iloc[0]["atr"]) > 0:
        first = features.iloc[0]
        atr = float(first["atr"])
        _mark_consumed(
            first,
            _liquidity_pools(first, True, atr, config.liquidity_dedup_tolerance_atr),
            _liquidity_pools(first, False, atr, config.liquidity_dedup_tolerance_atr),
            consumed_high,
            consumed_low,
        )

    for pos in range(1, len(features)):
        row = features.iloc[pos]
        if not _finite(row.get("atr")) or float(row["atr"]) <= 0:
            continue
        timestamp = pd.Timestamp(features.index[pos])

        surviving: list[_NarrativeState] = []
        for state in states:
            phase_before = state.phase
            updated, market = _process_state(
                state, features, pos, timestamp, symbol, config, diagnostics
            )
            if phase_before == "AWAIT_DISPLACEMENT" and updated is not None and updated.phase == "AWAIT_RETEST":
                passive = _passive_event(updated, row, timestamp, symbol, pos)
                if passive is not None:
                    events.append(passive)
                    diagnostics["causal_passive_actions"] += 1
            if market is not None:
                events.append(_market_event(market))
                diagnostics["confirmed_market_actions"] += 1
            if updated is not None:
                surviving.append(updated)
        states = surviving

        new_reversals = _new_reversal_states(
            features, pos, consumed_high, consumed_low, config, diagnostics
        )
        states.extend(new_reversals)

        for side in (1, -1):
            continuation = _new_continuation_state(
                features, pos, side, consumed_high, consumed_low, config, diagnostics
            )
            if continuation is not None:
                states.append(continuation)
                passive = _passive_event(continuation, row, timestamp, symbol, pos)
                if passive is not None:
                    events.append(passive)
                    diagnostics["causal_passive_actions"] += 1

        atr = float(row["atr"])
        high_pools = _liquidity_pools(
            row, True, atr, config.liquidity_dedup_tolerance_atr
        )
        low_pools = _liquidity_pools(
            row, False, atr, config.liquidity_dedup_tolerance_atr
        )
        _mark_consumed(row, high_pools, low_pools, consumed_high, consumed_low)

        # Preserve the core generator's structural-dominance deduplication. No state
        # expires merely because elapsed clock time passed.
        deduped: dict[tuple[EventFamily, int, float], _NarrativeState] = {}
        for state in states:
            key = (state.family, state.side, round(state.draw_target, 8))
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = state
            elif state.family == EventFamily.LIQUIDITY_SWEEP_REVERSAL:
                deeper = (
                    state.origin_extreme < existing.origin_extreme
                    if state.side > 0
                    else state.origin_extreme > existing.origin_extreme
                )
                if deeper:
                    deduped[key] = state
            elif state.created_pos > existing.created_pos:
                deduped[key] = state
        states = list(deduped.values())

    events.sort(
        key=lambda item: (
            item.timestamp,
            item.symbol,
            item.family.value,
            item.side,
            -float(item.feature_row.get("action_candidate_early_passive", 0.0)),
        )
    )
    diagnostics["final_action_candidates"] = len(events)
    return events, dict(sorted(diagnostics.items()))


def generate_causal_action_candidates_by_symbol(
    decision_frames: Mapping[str, pd.DataFrame],
    feature_config: FeatureConfig = FeatureConfig(),
    alpha_config: CorpusAlphaConfig = CorpusAlphaConfig(),
) -> tuple[dict[str, pd.DataFrame], list[EventCandidate], dict[str, dict[str, int]]]:
    feature_frames: dict[str, pd.DataFrame] = {}
    candidates: list[EventCandidate] = []
    diagnostics: dict[str, dict[str, int]] = {}
    for symbol, frame in sorted(decision_frames.items()):
        calculated = build_corpus_features(frame, feature_config)
        rows, counts = generate_causal_action_candidates(
            calculated, symbol, alpha_config
        )
        feature_frames[symbol] = calculated
        candidates.extend(rows)
        diagnostics[symbol] = counts
    candidates.sort(
        key=lambda item: (
            item.timestamp,
            item.symbol,
            item.family.value,
            item.side,
            -float(item.feature_row.get("action_candidate_early_passive", 0.0)),
        )
    )
    return feature_frames, candidates, diagnostics
