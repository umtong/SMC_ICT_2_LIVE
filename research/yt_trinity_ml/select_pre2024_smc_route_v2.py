#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def load(name: str, allow_skipped: bool = False) -> dict[str, Any] | None:
    path = ROOT / name
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    status = payload.get('job_status')
    if status == 'success' or (allow_skipped and status and status.startswith('skipped_')):
        return payload
    return None


def number(value: Any, default: float = float('-inf')) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def metric_row(source: str, kind: str, pointer: dict[str, Any], metrics: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    return {
        'source': source,
        'kind': kind,
        'source_commit': pointer.get('source_commit'),
        'workflow_run_id': pointer.get('workflow_run_id'),
        'geometric_daily_growth': number(metrics.get('geometric_daily_growth')),
        'account_multiple': number(metrics.get('account_multiple'), 0.0),
        'ending_nav': number(metrics.get('ending_nav'), 0.0),
        'maximum_drawdown': number(metrics.get('maximum_drawdown'), 1.0),
        'completed_trades': int(metrics.get('completed_trades', metrics.get('filled_trades', 0)) or 0),
        'frozen_contract': frozen,
    }


def contract_pointer(name: str, result_key: str, source: str, frozen_keys: tuple[str, ...]) -> dict[str, Any] | None:
    pointer = load(name)
    if not pointer:
        return None
    result = pointer['result']
    metrics = result.get('H2_frozen_validation_metrics') or {}
    frozen = {key: result.get(key) for key in frozen_keys}
    return metric_row(source, 'RAW_CANDIDATE_CONTRACT', pointer, metrics, frozen)


def collect() -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    completed: list[str] = []

    specs = [
        ('CANDIDATE_CONTRACT_COMPARISON_POINTER.json', 'CANDIDATE_CONTRACT', ('selected_identifier', 'selected_action')),
        ('REFERENCE_TIME_CONTRACT_V2_POINTER.json', 'REFERENCE_TIME', ('selected_identifier', 'selected_reference_time_mode', 'selected_action')),
        ('PD_ARRAY_CONTRACT_V3_POINTER.json', 'PD_ARRAY', ('selected_identifier', 'selected_reference_time_mode', 'selected_contract', 'selected_action')),
        ('SMT_CONTRACT_V1_POINTER.json', 'SMT', ('selected_identifier', 'selected_contract', 'selected_action')),
        ('OTE_CONTRACT_V1_POINTER.json', 'OTE', ('selected_identifier', 'selected_contract', 'selected_action')),
        ('MTF_ENTRY_CONTRACT_V1_POINTER.json', 'MTF_ENTRY', ('selected_identifier', 'selected_entry_mode', 'selected_contract', 'selected_action')),
    ]
    for filename, source, keys in specs:
        value = contract_pointer(filename, 'H2_frozen_validation_metrics', source, keys)
        if value:
            rows.append(value)
            completed.append(source)

    pointer = load('EXIT_GEOMETRY_V1_POINTER.json')
    if pointer:
        completed.append('EXIT_GEOMETRY')
        selected = (pointer['result'].get('selected') or {})
        rows.append(metric_row('EXIT_GEOMETRY', 'RAW_EXIT_CONTRACT', pointer, ((selected.get('H2') or {}).get('account') or {}), selected))

    for filename, source in (
        ('MULTI_ACTION_EXIT_ML_V2_POINTER.json', 'MULTI_ACTION_EXIT_ML'),
        ('ENTRY_EXIT_ACTION_ML_V2_POINTER.json', 'ENTRY_EXIT_ACTION_ML'),
    ):
        pointer = load(filename)
        if pointer:
            completed.append(source)
            result = pointer['result']
            metrics = result.get('H2_selected') or {}
            rows.append(metric_row(source, 'CONTEXTUAL_ML_POLICY', pointer, metrics, {
                'raw_alpha_run_id': pointer.get('raw_alpha_run_id'),
                'threshold': ((result.get('threshold_choice') or result.get('calibrated_threshold') or {}).get('threshold')),
                'selected_actions': result.get('H2_selected_actions') or result.get('H2_action_counts'),
            }))

    pointer = load('INTEGRATED_SELECTED_CONTRACT_ML_POINTER.json', allow_skipped=True)
    if pointer and pointer.get('job_status') == 'success' and pointer.get('result'):
        completed.append('INTEGRATED_SELECTED_CONTRACT_ML')
        result = pointer['result']
        selected = result.get('selected') or {}
        metrics = selected.get('metrics') or {}
        rows.append(metric_row('INTEGRATED_SELECTED_CONTRACT_ML', 'INTEGRATED_ML_ACCOUNT', pointer, metrics, {
            'configuration': selected.get('configuration'),
            'configuration_payload': selected.get('configuration_payload'),
            'action_restriction': result.get('action_restriction'),
            'resolved_route': pointer.get('resolved_route'),
        }))
    return rows, completed


def main() -> int:
    rows, completed = collect()
    ranked = sorted(rows, key=lambda item: (
        item['geometric_daily_growth'], item['account_multiple'], -item['maximum_drawdown'],
        item['completed_trades'], item['source'],
    ), reverse=True)
    integrated_positive = [row for row in ranked if row['kind'] == 'INTEGRATED_ML_ACCOUNT' and row['geometric_daily_growth'] > 0]
    contextual_positive = [row for row in ranked if row['kind'] == 'CONTEXTUAL_ML_POLICY' and row['geometric_daily_growth'] > 0]
    raw_positive = [row for row in ranked if row['kind'].startswith('RAW_') and row['geometric_daily_growth'] > 0]
    if integrated_positive:
        selected = integrated_positive[0]
        decision = 'FREEZE_INTEGRATED_ML_SYSTEM_FOR_2024H1'
        next_gate = 'materialize exact candidate, action, model-update, risk, cost and order contract; run official continuous 2024H1'
        official = True
    elif contextual_positive:
        selected = contextual_positive[0]
        decision = 'REPRODUCE_CONTEXTUAL_ML_POLICY_THEN_FREEZE'
        next_gate = 'repeat the exact source-bound H1-trained H2 policy and bind code/data hashes before 2024H1'
        official = False
    elif raw_positive:
        selected = raw_positive[0]
        decision = 'ADVANCE_SELECTED_RAW_CONTRACT_TO_INTEGRATED_ML_ACCOUNT'
        next_gate = 'train and validate chronological ML on the selected immutable labels with one global slot'
        official = False
    elif ranked:
        selected = ranked[0]
        decision = 'KEEP_SMC_PREMISE_CONTINUE_IMPLEMENTATION_REFINEMENT'
        next_gate = 'complete pending integrated core, liquidity freshness, structural target, OTE and MTF experiments; inspect earliest economic bottleneck'
        official = False
    else:
        selected = None
        decision = 'WAIT_FOR_IMPLEMENTATION_RESULTS'
        next_gate = 'complete the running pre-2024 SMC implementation experiments'
        official = False
    readiness = load('CORE_FIDELITY_READINESS.json')
    payload = {
        'schema_version': 2,
        'claim_id': 'CLM-20260727-0346-YT-TRINITY-ML-001',
        'stage': 'PRE2024_SMC_RESEARCH_ROUTER_V2_NOT_RANKABLE',
        'core_readiness': readiness,
        'completed_sources': completed,
        'candidate_results': ranked,
        'selected': selected,
        'decision': decision,
        'next_gate': next_gate,
        'official_2024_open_authority': official,
        'ranking_effect': 'NONE_PRE2024_NOT_RANKABLE',
    }
    (ROOT / 'PRE2024_SMC_ROUTE_V2.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
