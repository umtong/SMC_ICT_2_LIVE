#!/usr/bin/env python3
"""Run a frozen pre-2024 selected SMC/ICT ML system through 2024H1.

All structure, model, cadence, action, risk and costs come from the positive
pre-2024 integrated result. 2023 market state is prepended for feature continuity;
account NAV begins once at 10,000 USDT on 2024-01-01. No 2024 outcome selects or
changes the contract.
"""
from __future__ import annotations

import argparse
from dataclasses import fields
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_integrated_ml_from_labels import RestrictedActionPolicy
from run_mtf_entry_contract_v1 import prepare_one_minute, refine_setup
from run_research import PRIMARY, load_canonical_frames
from system.coarse import CoarseEventReplay, CoarseExecutionConfig, coarse_closeout_price
from system.core import FeatureConfig, RiskConfig
from system.corpus_alpha import (
    CorpusAlphaConfig,
    build_corpus_features,
    generate_corpus_candidates_with_diagnostics,
    generate_corpus_setups_with_diagnostics,
)
from system.metrics import summarize_account
from system.model import ModelConfig
from system.research_pipeline import (
    InstrumentRule,
    ResearchConfiguration,
    label_event_dataset,
    score_candidates_walk_forward,
)
from system.smt import add_pair_smt_features


def instantiate_configuration(payload: dict[str, Any]) -> ResearchConfiguration:
    return ResearchConfiguration(
        identifier=str(payload['identifier']),
        symbols=tuple(payload['symbols']),
        model=ModelConfig(**payload['model']),
        update_cadence_days=int(payload['update_cadence_days']),
        training_completion_lag_minutes=int(payload['training_completion_lag_minutes']),
        passive_fill_threshold=float(payload.get('passive_fill_threshold', 0.55)),
        risk=RiskConfig(**payload['risk']),
        instrument_rules=tuple(InstrumentRule(**row) for row in payload['instrument_rules']),
    )


def contract_from_route(route: dict[str, Any]) -> tuple[str, CorpusAlphaConfig, str]:
    frozen = route.get('frozen_contract') or {}
    reference = str(frozen.get('selected_reference_time_mode') or frozen.get('reference_time_mode') or 'UTC')
    entry_mode = str(frozen.get('selected_entry_mode') or frozen.get('entry_mode') or 'FIVE_MINUTE_RETEST')
    raw = frozen.get('selected_contract') or frozen.get('contract') or {}
    allowed = {field.name for field in fields(CorpusAlphaConfig)}
    contract = CorpusAlphaConfig(**{name: value for name, value in raw.items() if name in allowed})
    return reference, contract, entry_mode


def generate_2024_candidates(
    decision_frames: dict[str, pd.DataFrame],
    execution_frames: dict[str, pd.DataFrame],
    reference: str,
    contract: CorpusAlphaConfig,
    entry_mode: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[list[Any], dict[str, Any]]:
    features = add_pair_smt_features({
        symbol: build_corpus_features(frame, FeatureConfig(), reference_time_mode=reference)
        for symbol, frame in sorted(decision_frames.items())
    })
    diagnostics: dict[str, Any] = {}
    candidates = []
    if entry_mode == 'ONE_MINUTE_CISD':
        one_minute = {symbol: prepare_one_minute(frame) for symbol, frame in execution_frames.items()}
        for symbol, frame in sorted(features.items()):
            setups, diag = generate_corpus_setups_with_diagnostics(frame, symbol, contract)
            setups = [setup for setup in setups if start <= setup.timestamp < end]
            refined = [candidate for candidate in (refine_setup(setup, one_minute[symbol]) for setup in setups) if candidate is not None]
            candidates.extend(candidate for candidate in refined if start <= candidate.timestamp < end)
            diagnostics[symbol] = {'armed_setups': len(setups), 'refined_entries': len(refined), 'setup_diagnostics': diag}
    else:
        for symbol, frame in sorted(features.items()):
            rows, diag = generate_corpus_candidates_with_diagnostics(frame, symbol, contract)
            selected = [candidate for candidate in rows if start <= candidate.timestamp < end]
            candidates.extend(selected)
            diagnostics[symbol] = {'candidates': len(selected), 'candidate_diagnostics': diag}
    candidates.sort(key=lambda row: (row.timestamp, row.symbol, row.family.value, row.side))
    return candidates, diagnostics


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    pointer = json.loads(args.integrated_pointer.read_text())
    if pointer.get('job_status') != 'success' or not pointer.get('official_2024_open_authority'):
        raise RuntimeError('positive integrated pre-2024 authority is required')
    result = pointer['result']
    selected = result['selected']
    configuration = instantiate_configuration(selected['configuration_payload'])
    resolved = pointer['resolved_route']['selected']
    reference, contract, entry_mode = contract_from_route(resolved)
    action = str(result.get('action_restriction', 'ANY')).upper()

    decision_frames, execution_frames, funding = load_canonical_frames(
        args.data_root, args.repo_root, PRIMARY, args.segments
    )
    start = pd.Timestamp('2024-01-01T00:00:00Z')
    end = pd.Timestamp('2024-07-01T00:00:00Z')
    candidates, diagnostics = generate_2024_candidates(
        decision_frames, execution_frames, reference, contract, entry_mode, start, end
    )
    labels_2024 = label_event_dataset(candidates, execution_frames, CoarseExecutionConfig())
    labels_2024['event_start'] = pd.to_datetime(labels_2024['event_start'], utc=True)
    labels_2024['event_end'] = pd.to_datetime(labels_2024['event_end'], utc=True)
    labels_2024.to_parquet(args.output / '2024H1_EVENT_LABELS.parquet', index=False)
    labels_2023 = pd.read_parquet(args.pre2024_labels)
    labels_2023['event_start'] = pd.to_datetime(labels_2023['event_start'], utc=True)
    labels_2023['event_end'] = pd.to_datetime(labels_2023['event_end'], utc=True)
    labels = pd.concat([labels_2023, labels_2024], ignore_index=True, sort=False)

    scored, updates = score_candidates_walk_forward(candidates, labels, configuration, start, end)
    selected_bars = {
        symbol: frame.loc[
            (pd.to_datetime(frame['bar_start'], utc=True) >= start)
            & (pd.to_datetime(frame['bar_start'], utc=True) < end)
        ].copy()
        for symbol, frame in execution_frames.items() if symbol in configuration.symbols
    }
    policy = RestrictedActionPolicy(action)
    execution = CoarseExecutionConfig()
    instrument_rules = {rule.symbol: (rule.quantity_step, rule.minimum_quantity) for rule in configuration.instrument_rules}
    account = CoarseEventReplay(selected_bars, execution).run(
        scored, policy, configuration.risk, start, end,
        initial_nav=10_000.0, funding=funding, instrument_rules=instrument_rules,
    )
    final_mark = 0.0
    final_closeout = None
    for frame in selected_bars.values():
        if not frame.empty:
            final_mark = float(frame.iloc[-1].get('mark_close', frame.iloc[-1]['close']))
    if account.position is not None:
        frame = selected_bars[account.position.candidate.symbol]
        if not frame.empty:
            final_row = frame.iloc[-1]
            final_mark = float(final_row.get('mark_close', final_row['close']))
            final_closeout = coarse_closeout_price(final_row, account.position.side, execution)
    metrics = summarize_account(
        account, start, end, final_mark,
        final_closeout_price=final_closeout,
        final_closeout_fee_rate=execution.taker_fee_rate if final_closeout is not None else 0.0,
    )
    payload = {
        'schema_version': 1,
        'stage': '2024H1_FROZEN_SMC_ML_COARSE_PROVISIONAL_NOT_RANKABLE',
        'evaluation_start': start.isoformat(),
        'evaluation_end_exclusive': end.isoformat(),
        'initial_nav': 10_000.0,
        'reference_time_mode': reference,
        'entry_mode': entry_mode,
        'action_restriction': action,
        'candidate_contract': {field.name: getattr(contract, field.name) for field in fields(CorpusAlphaConfig)},
        'configuration': selected['configuration_payload'],
        'candidate_count': len(candidates),
        'resolved_label_count': len(labels_2024),
        'diagnostics': diagnostics,
        'scored_count': len(scored),
        'positive_score_count': sum(float(row.lower_confidence_score) > 0 for row in scored),
        'model_updates': [record.__dict__ for record in updates],
        'metrics': metrics.as_dict(),
        'decision': (
            'ADVANCE_EXACT_2024H1_TRADES_TO_EVENT_TAPE'
            if metrics.geometric_daily_growth > 0
            else 'KEEP_FROZEN_RESULT_AND_RETURN_TO_PRE2024_SMC_REFINEMENT'
        ),
        'ranking_effect': 'NONE_COARSE_PROVISIONAL_NOT_RANKABLE',
    }
    (args.output / 'FROZEN_2024H1_RESULT.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--integrated-pointer', type=Path, required=True)
    parser.add_argument('--pre2024-labels', type=Path, required=True)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--segments', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
