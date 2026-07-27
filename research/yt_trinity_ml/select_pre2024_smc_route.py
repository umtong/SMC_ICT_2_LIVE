#!/usr/bin/env python3
"""Aggregate implementation experiments and select the next causal SMC route.

This router never opens official 2024 authority. Positive raw contracts route to
an integrated ML account; positive contextual ML policies route to a frozen
reproduction gate. Negative results identify the deepest completed implementation
stage instead of authorizing an unrelated alpha switch.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def load(name: str) -> dict[str, Any] | None:
    path = ROOT / name
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if payload.get('job_status') == 'success' and payload.get('result') else None


def metric(value: Any, default: float = float('-inf')) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def row(source: str, kind: str, pointer: dict[str, Any], h2: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    return {
        'source': source,
        'kind': kind,
        'pointer_source_commit': pointer.get('source_commit'),
        'workflow_run_id': pointer.get('workflow_run_id'),
        'geometric_daily_growth': metric(h2.get('geometric_daily_growth')),
        'account_multiple': metric(h2.get('account_multiple'), 0.0),
        'ending_nav': metric(h2.get('ending_nav'), 0.0),
        'maximum_drawdown': metric(h2.get('maximum_drawdown'), 1.0),
        'completed_trades': int(h2.get('completed_trades', h2.get('filled_trades', 0)) or 0),
        'frozen_contract': frozen,
    }


def collect() -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    completed: list[str] = []

    pointer = load('EXIT_GEOMETRY_V1_POINTER.json')
    if pointer:
        completed.append('EXIT_GEOMETRY_V1')
        result = pointer['result']
        selected = result.get('selected') or {}
        h2 = ((selected.get('H2') or {}).get('account') or {})
        candidates.append(row('EXIT_GEOMETRY_V1', 'RAW_EXIT_CONTRACT', pointer, h2, selected))

    pointer = load('CANDIDATE_CONTRACT_COMPARISON_POINTER.json')
    if pointer:
        completed.append('CANDIDATE_CONTRACT_COMPARISON')
        result = pointer['result']
        h2 = result.get('H2_frozen_validation_metrics') or {}
        candidates.append(row('CANDIDATE_CONTRACT_COMPARISON', 'RAW_CANDIDATE_CONTRACT', pointer, h2, {
            'identifier': result.get('selected_identifier'), 'action': result.get('selected_action'),
        }))

    pointer = load('REFERENCE_TIME_CONTRACT_V2_POINTER.json')
    if pointer:
        completed.append('REFERENCE_TIME_CONTRACT_V2')
        result = pointer['result']
        h2 = result.get('H2_frozen_validation_metrics') or {}
        candidates.append(row('REFERENCE_TIME_CONTRACT_V2', 'RAW_CANDIDATE_CONTRACT', pointer, h2, {
            'identifier': result.get('selected_identifier'),
            'reference_time_mode': result.get('selected_reference_time_mode'),
            'action': result.get('selected_action'),
        }))

    pointer = load('PD_ARRAY_CONTRACT_V3_POINTER.json')
    if pointer:
        completed.append('PD_ARRAY_CONTRACT_V3')
        result = pointer['result']
        h2 = result.get('H2_frozen_validation_metrics') or {}
        candidates.append(row('PD_ARRAY_CONTRACT_V3', 'RAW_CANDIDATE_CONTRACT', pointer, h2, {
            'identifier': result.get('selected_identifier'),
            'reference_time_mode': result.get('selected_reference_time_mode'),
            'contract': result.get('selected_contract'),
            'action': result.get('selected_action'),
        }))

    pointer = load('SMT_CONTRACT_V1_POINTER.json')
    if pointer:
        completed.append('SMT_CONTRACT_V1')
        result = pointer['result']
        h2 = result.get('H2_frozen_validation_metrics') or {}
        candidates.append(row('SMT_CONTRACT_V1', 'RAW_CANDIDATE_CONTRACT', pointer, h2, {
            'identifier': result.get('selected_identifier'),
            'contract': result.get('selected_contract'),
            'action': result.get('selected_action'),
        }))

    pointer = load('MTF_ENTRY_CONTRACT_V1_POINTER.json')
    if pointer:
        completed.append('MTF_ENTRY_CONTRACT_V1')
        result = pointer['result']
        h2 = result.get('H2_frozen_validation_metrics') or {}
        candidates.append(row('MTF_ENTRY_CONTRACT_V1', 'RAW_MTF_CONTRACT', pointer, h2, {
            'identifier': result.get('selected_identifier'),
            'entry_mode': result.get('selected_entry_mode'),
            'contract': result.get('selected_contract'),
            'action': result.get('selected_action'),
        }))

    pointer = load('MULTI_ACTION_EXIT_ML_V2_POINTER.json')
    if pointer:
        completed.append('MULTI_ACTION_EXIT_ML_V2')
        result = pointer['result']
        h2 = result.get('H2_selected') or {}
        candidates.append(row('MULTI_ACTION_EXIT_ML_V2', 'CONTEXTUAL_ML_POLICY', pointer, h2, {
            'threshold': (result.get('calibrated_threshold') or {}).get('threshold'),
            'action_counts': result.get('H2_action_counts'),
            'raw_alpha_run_id': pointer.get('raw_alpha_run_id'),
        }))

    pointer = load('ENTRY_EXIT_ACTION_ML_V2_POINTER.json')
    if pointer:
        completed.append('ENTRY_EXIT_ACTION_ML_V2')
        result = pointer['result']
        h2 = result.get('H2_selected') or {}
        candidates.append(row('ENTRY_EXIT_ACTION_ML_V2', 'CONTEXTUAL_ML_POLICY', pointer, h2, {
            'threshold': (result.get('threshold_choice') or {}).get('threshold'),
            'selected_actions': result.get('H2_selected_actions'),
            'raw_alpha_run_id': pointer.get('raw_alpha_run_id'),
        }))

    return candidates, completed


def main() -> int:
    candidates, completed = collect()
    ranked = sorted(candidates, key=lambda item: (
        item['geometric_daily_growth'], item['account_multiple'],
        -item['maximum_drawdown'], item['completed_trades'], item['source'],
    ), reverse=True)
    positive = [item for item in ranked if item['geometric_daily_growth'] > 0]
    selected = positive[0] if positive else (ranked[0] if ranked else None)
    if selected is None:
        decision = 'WAIT_FOR_IMPLEMENTATION_RESULTS'
        next_gate = 'complete at least one H1-selected H2-validated SMC implementation experiment'
    elif selected['geometric_daily_growth'] <= 0:
        decision = 'KEEP_SMC_PREMISE_CONTINUE_IMPLEMENTATION_REFINEMENT'
        next_gate = 'complete pending PD-array, SMT, liquidity-freshness, structural-target and MTF entry experiments'
    elif selected['kind'] in {'RAW_EXIT_CONTRACT', 'RAW_CANDIDATE_CONTRACT', 'RAW_MTF_CONTRACT'}:
        decision = 'ADVANCE_SELECTED_RAW_CONTRACT_TO_INTEGRATED_ML_ACCOUNT'
        next_gate = 'recreate the exact selected candidate/action contract with chronological ML, global slot and continuous account before any 2024 opening'
    else:
        decision = 'ADVANCE_CONTEXTUAL_ML_POLICY_TO_FROZEN_REPRODUCTION'
        next_gate = 'repeat the exact H1-trained policy from source-bound artifacts, then freeze it for 2024H1 if reproduced'
    payload = {
        'schema_version': 1,
        'claim_id': 'CLM-20260727-0346-YT-TRINITY-ML-001',
        'stage': 'PRE2024_SMC_RESEARCH_ROUTER_NOT_RANKABLE',
        'completed_sources': completed,
        'candidate_results': ranked,
        'selected': selected,
        'decision': decision,
        'next_gate': next_gate,
        'official_2024_open_authority': False,
        'ranking_effect': 'NONE_PRE2024_NOT_RANKABLE',
    }
    (ROOT / 'PRE2024_SMC_ROUTE.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
