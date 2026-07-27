#!/usr/bin/env python3
"""H1/H2 comparison of feature-only and required BTC/ETH SMT confirmation."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from math import exp, log
from pathlib import Path
from typing import Any

import pandas as pd

from run_research import PRIMARY, load_canonical_frames
from system.coarse import CoarseExecutionConfig
from system.core import FeatureConfig
from system.corpus_alpha import CorpusAlphaConfig, build_corpus_features, generate_corpus_candidates_with_diagnostics
from system.research_pipeline import label_event_dataset
from system.smt import add_pair_smt_features


def account(labels: pd.DataFrame, action: str, start: pd.Timestamp, end: pd.Timestamp, risk: float = 0.01) -> dict[str, Any]:
    column = f'{action}_budget_r' if f'{action}_budget_r' in labels.columns else f'{action}_net_r'
    rows = labels[(labels['event_start'] >= start) & (labels['event_start'] < end) & labels[column].notna()].copy()
    if action == 'passive':
        rows = rows[pd.to_numeric(rows['passive_filled'], errors='coerce').fillna(0).astype(int).eq(1)]
    rows = rows.sort_values(['event_start', 'symbol'], kind='stable')
    nav = peak = 10_000.0
    mdd = 0.0
    occupied_until = start
    values: list[float] = []
    for row in rows.itertuples(index=False):
        if row.event_start < occupied_until:
            continue
        value = float(getattr(row, column))
        fraction = risk * value
        if fraction <= -1:
            nav = 0.0
            values.append(value)
            break
        nav *= 1.0 + fraction
        occupied_until = row.event_end
        values.append(value)
        peak = max(peak, nav)
        mdd = max(mdd, 1.0 - nav / peak)
    days = int((end - start) / pd.Timedelta(days=1))
    growth = -1.0 if nav <= 0 else exp(log(nav / 10_000.0) / days) - 1.0
    return {
        'completed_trades': len(values), 'ending_nav': nav,
        'account_multiple': nav / 10_000.0, 'geometric_daily_growth': growth,
        'maximum_drawdown': mdd,
        'mean_budget_r': sum(values) / len(values) if values else None,
        'available_candidates': len(rows),
    }


def contract(smt_mode: str, session: bool, reference: str, pd_fidelity: bool) -> tuple[str, CorpusAlphaConfig]:
    kwargs: dict[str, Any] = {
        'continuation_requires_liquidity_raid': True,
        'continuation_minimum_htf_bias': 2.0,
        'continuation_requires_discount_premium': True,
        'require_session_amd': session,
        'smt_confirmation_mode': smt_mode,
    }
    if pd_fidelity:
        kwargs.update({
            'order_block_range_mode': 'OPEN_TO_EXTREME',
            'fvg_search_mode': 'IMPULSE_NEAREST',
            'cisd_confirmation_mode': 'DELIVERY_OPEN',
        })
    return reference, CorpusAlphaConfig(**kwargs)


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    decision_frames, execution_frames, _ = load_canonical_frames(args.data_root, args.repo_root, PRIMARY, args.segments)
    contracts = {
        'UTC_CONTINUOUS_SMT_OFF': contract('OFF', False, 'UTC', True),
        'UTC_CONTINUOUS_SMT_FEATURE': contract('FEATURE_ONLY', False, 'UTC', True),
        'UTC_CONTINUOUS_SMT_REQUIRED': contract('REQUIRE_SELF_RAID_DIVERGENCE', False, 'UTC', True),
        'NY_CONTINUOUS_SMT_OFF': contract('OFF', False, 'NEW_YORK', True),
        'NY_CONTINUOUS_SMT_FEATURE': contract('FEATURE_ONLY', False, 'NEW_YORK', True),
        'NY_CONTINUOUS_SMT_REQUIRED': contract('REQUIRE_SELF_RAID_DIVERGENCE', False, 'NEW_YORK', True),
        'NY_SESSION_SMT_OFF': contract('OFF', True, 'NEW_YORK', True),
        'NY_SESSION_SMT_FEATURE': contract('FEATURE_ONLY', True, 'NEW_YORK', True),
        'NY_SESSION_SMT_REQUIRED': contract('REQUIRE_SELF_RAID_DIVERGENCE', True, 'NEW_YORK', True),
    }
    feature_cache: dict[str, dict[str, pd.DataFrame]] = {}
    for reference in ('UTC', 'NEW_YORK'):
        built = {
            symbol: build_corpus_features(frame, FeatureConfig(), reference_time_mode=reference)
            for symbol, frame in sorted(decision_frames.items())
        }
        feature_cache[reference] = add_pair_smt_features(built)
    h1_start = pd.Timestamp('2023-01-01', tz='UTC')
    h1_end = pd.Timestamp('2023-07-01', tz='UTC')
    h2_end = pd.Timestamp('2024-01-01', tz='UTC')
    results: list[dict[str, Any]] = []
    for identifier, (reference, cfg) in contracts.items():
        candidates = []
        diagnostics = {}
        for symbol, features in sorted(feature_cache[reference].items()):
            rows, diag = generate_corpus_candidates_with_diagnostics(features, symbol, cfg)
            candidates.extend(rows)
            diagnostics[symbol] = diag
        candidates.sort(key=lambda row: (row.timestamp, row.symbol, row.family.value, row.side))
        labels = label_event_dataset(candidates, execution_frames, CoarseExecutionConfig())
        labels['event_start'] = pd.to_datetime(labels['event_start'], utc=True)
        labels['event_end'] = pd.to_datetime(labels['event_end'], utc=True)
        labels.to_parquet(args.output / f'{identifier}_LABELS.parquet', index=False)
        results.append({
            'identifier': identifier,
            'reference_time_mode': reference,
            'contract': asdict(cfg),
            'candidate_count': len(candidates),
            'resolved_label_count': len(labels),
            'by_family': dict(sorted(Counter(row.family.value for row in candidates).items())),
            'diagnostics': diagnostics,
            'H1': {'market': account(labels, 'market', h1_start, h1_end), 'passive': account(labels, 'passive', h1_start, h1_end)},
            'H2': {'market': account(labels, 'market', h1_end, h2_end), 'passive': account(labels, 'passive', h1_end, h2_end)},
        })
    options = [(row, action, row['H1'][action]) for row in results for action in ('market', 'passive')]
    selected, action, h1 = max(options, key=lambda item: (
        item[2]['geometric_daily_growth'], item[2]['mean_budget_r'] or -999.0,
        item[2]['completed_trades'], item[0]['identifier'], item[1],
    ))
    h2 = selected['H2'][action]
    payload = {
        'schema_version': 1,
        'stage': 'PRE2024_SMT_CONTRACT_H1_SELECTION_H2_VALIDATION_NOT_RANKABLE',
        'contracts': results,
        'selected_identifier': selected['identifier'],
        'selected_action': action,
        'selected_contract': selected['contract'],
        'H1_selection_metrics': h1,
        'H2_frozen_validation_metrics': h2,
        'decision': 'ADVANCE_SMT_CONTRACT' if h2['geometric_daily_growth'] > 0 else 'KEEP_SMC_PREMISE_REPAIR_LIQUIDITY_FRESHNESS_OR_TARGET_HIERARCHY',
        'ranking_effect': 'NONE_PRE2024_NOT_RANKABLE',
    }
    (args.output / 'SMT_CONTRACT_RESULT.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n')
    pd.DataFrame([
        {
            'identifier': row['identifier'], 'candidates': row['candidate_count'],
            'H1_market_growth': row['H1']['market']['geometric_daily_growth'],
            'H1_passive_growth': row['H1']['passive']['geometric_daily_growth'],
            'H2_market_growth': row['H2']['market']['geometric_daily_growth'],
            'H2_passive_growth': row['H2']['passive']['geometric_daily_growth'],
        }
        for row in results
    ]).to_csv(args.output / 'SMT_CONTRACT_TABLE.csv', index=False)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--segments', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
