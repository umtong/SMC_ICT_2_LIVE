#!/usr/bin/env python3
"""Reproduce a selected raw SMC contract inside the chronological ML account.

The input labels and features come from the exact immutable comparison artifact.
H1 labels train; H2 is sequential validation with monthly/weekly/daily causal
updates, one global slot, cost-aware action labels, fixed latency and account NAV.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from math import isfinite
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from run_exit_geometry_v1 import reconstruct_candidates
from run_research import PRIMARY, basic_configurations, load_canonical_frames, load_instrument_rules
from system.coarse import CoarseEventReplay, CoarseExecutionConfig, coarse_closeout_price
from system.core import EventCandidate
from system.metrics import summarize_account
from system.policy import GlobalSlotPolicy, PolicyDecision, SelectedDecision
from system.research_pipeline import ResearchConfiguration, score_candidates_walk_forward


class RestrictedActionPolicy(GlobalSlotPolicy):
    def __init__(self, action: str) -> None:
        super().__init__(0.55)
        self.action = action.upper()
        if self.action not in {'MARKET', 'PASSIVE', 'ANY'}:
            raise ValueError(f'unknown action restriction: {action}')

    def choose(self, scored_candidates: Iterable[Any], slot_available: bool) -> SelectedDecision:
        if self.action == 'ANY':
            return super().choose(scored_candidates, slot_available)
        if not slot_available:
            return SelectedDecision(PolicyDecision.ABSTAIN, None, 'global entry slot occupied')
        rows = []
        for item in scored_candidates:
            if self.action == 'MARKET':
                score = item.market_lower_confidence_score
                log_growth = item.market_expected_log_growth
                decision = PolicyDecision.MARKETABLE
            else:
                score = item.passive_lower_confidence_score
                log_growth = item.passive_expected_log_growth
                decision = PolicyDecision.PASSIVE_RETEST
            if score is not None and isfinite(float(score)):
                rows.append((float(score), float(log_growth or -np.inf), item.candidate.symbol, item, decision))
        positive = [row for row in rows if row[0] > 0]
        if not positive:
            return SelectedDecision(PolicyDecision.ABSTAIN, None, 'no positive restricted after-cost action value')
        selected = max(positive, key=lambda row: row[:3])
        return SelectedDecision(selected[4], selected[3], 'highest positive restricted action value')


def reconstruct_events(labels: pd.DataFrame) -> list[EventCandidate]:
    labels = labels.reset_index(drop=True)
    geometry = reconstruct_candidates(labels)
    leakage_tokens = (
        'net_r', 'budget_r', 'target_before_stop', 'event_start', 'event_end',
        'passive_filled', 'status', 'entry_time', 'exit_time',
    )
    events = []
    for item in geometry:
        row = labels.iloc[item.row_id]
        features = {
            str(name): float(value)
            for name, value in row.items()
            if isinstance(value, (int, float, np.integer, np.floating))
            and np.isfinite(value)
            and not any(token in str(name) for token in leakage_tokens)
            and not str(name).startswith('execution_')
        }
        # Preserve execution-only structural references outside the model vector.
        for name, value in row.items():
            if str(name).startswith('execution_') and isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value):
                features[str(name)] = float(value)
        events.append(EventCandidate(
            timestamp=item.event_start,
            symbol=item.symbol,
            family=__import__('system.core', fromlist=['EventFamily']).EventFamily(item.family),
            side=item.side,
            decision_price=item.entry_reference,
            entry_reference=item.entry_reference,
            stop_reference=item.stop_reference,
            target_reference=item.target_reference,
            structural_level=item.entry_reference,
            feature_row=features,
        ))
    events.sort(key=lambda event: (event.timestamp, event.symbol, event.family.value, event.side))
    return events


def evaluate(
    configuration: ResearchConfiguration,
    candidates: list[EventCandidate],
    labels: pd.DataFrame,
    execution_frames: dict[str, pd.DataFrame],
    funding: dict[tuple[str, pd.Timestamp], float],
    action: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    scored, updates = score_candidates_walk_forward(candidates, labels, configuration, start, end)
    selected_bars = {
        symbol: frame.loc[pd.to_datetime(frame['bar_start'], utc=True) < end].copy()
        for symbol, frame in execution_frames.items() if symbol in configuration.symbols
    }
    policy = RestrictedActionPolicy(action)
    instrument_rules = {rule.symbol: (rule.quantity_step, rule.minimum_quantity) for rule in configuration.instrument_rules}
    execution = CoarseExecutionConfig()
    account = CoarseEventReplay(selected_bars, execution).run(
        scored, policy, configuration.risk, start, end,
        initial_nav=10_000.0, funding=funding, instrument_rules=instrument_rules,
    )
    final_mark = 0.0
    final_closeout = None
    for frame in selected_bars.values():
        eligible = frame.loc[pd.to_datetime(frame['bar_start'], utc=True) < end]
        if not eligible.empty:
            final_mark = float(eligible.iloc[-1].get('mark_close', eligible.iloc[-1]['close']))
    if account.position is not None:
        frame = selected_bars[account.position.candidate.symbol]
        eligible = frame.loc[pd.to_datetime(frame['bar_start'], utc=True) < end]
        if not eligible.empty:
            final_row = eligible.iloc[-1]
            final_mark = float(final_row.get('mark_close', final_row['close']))
            final_closeout = coarse_closeout_price(final_row, account.position.side, execution)
    metrics = summarize_account(
        account, start, end, final_mark,
        final_closeout_price=final_closeout,
        final_closeout_fee_rate=execution.taker_fee_rate if final_closeout is not None else 0.0,
    )
    return {
        'configuration': configuration.identifier,
        'configuration_payload': asdict(configuration),
        'metrics': metrics.as_dict(),
        'candidate_count': sum(start <= candidate.timestamp < end for candidate in candidates),
        'scored_count': len(scored),
        'positive_score_count': sum(float(row.lower_confidence_score) > 0 for row in scored),
        'model_updates': [asdict(record) for record in updates],
    }


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    labels = pd.read_parquet(args.labels)
    labels['event_start'] = pd.to_datetime(labels['event_start'], utc=True)
    labels['event_end'] = pd.to_datetime(labels['event_end'], utc=True)
    candidates = reconstruct_events(labels)
    rules = load_instrument_rules(args.instrument_rules, PRIMARY)
    _, execution_frames, funding = load_canonical_frames(args.data_root, args.repo_root, PRIMARY, args.segments)
    start = pd.Timestamp('2023-07-01', tz='UTC')
    end = pd.Timestamp('2024-01-01', tz='UTC')
    results = [
        evaluate(configuration, candidates, labels, execution_frames, funding, args.action, start, end)
        for configuration in basic_configurations(rules)
    ]
    selected = max(results, key=lambda row: (
        float(row['metrics']['geometric_daily_growth']),
        float(row['metrics']['account_multiple']),
        -float(row['metrics']['maximum_drawdown']),
        int(row['metrics']['completed_trades']),
        row['configuration'],
    ))
    growth = float(selected['metrics']['geometric_daily_growth'])
    payload = {
        'schema_version': 1,
        'stage': 'PRE2024_SELECTED_CONTRACT_INTEGRATED_ML_H2_NOT_RANKABLE',
        'source_labels': str(args.labels),
        'action_restriction': args.action.upper(),
        'candidate_count': len(candidates),
        'all_results': results,
        'selected': selected,
        'decision': 'FREEZE_INTEGRATED_ML_FOR_2024H1' if growth > 0 else 'RETURN_TO_SMC_IMPLEMENTATION_REFINEMENT',
        'official_2024_open_authority': growth > 0,
        'ranking_effect': 'NONE_PRE2024_NOT_RANKABLE',
    }
    (args.output / 'INTEGRATED_ML_RESULT.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--segments', nargs='+', required=True)
    parser.add_argument('--instrument-rules', type=Path, required=True)
    parser.add_argument('--action', choices=['market', 'passive', 'any'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
