#!/usr/bin/env python3
"""Fast raw economics for the current unified SMC/ICT candidate narrative.

This intentionally omits ML selection and risk search. It separates candidate
construction/exit geometry from model abstention so implementation weakness is
not misclassified as alpha-premise failure.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from math import exp, log
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from run_research import PRIMARY, load_canonical_frames
from system.coarse import CoarseExecutionConfig
from system.core import FeatureConfig
from system.corpus_alpha import build_corpus_features, generate_corpus_candidates_with_diagnostics
from system.research_pipeline import label_event_dataset


def finite_stats(values: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(values, errors='coerce').dropna().astype(float)
    if values.empty:
        return {'count': 0, 'mean': None, 'median': None, 'sum': None, 'positive_fraction': None}
    return {
        'count': int(len(values)),
        'mean': float(values.mean()),
        'median': float(values.median()),
        'sum': float(values.sum()),
        'positive_fraction': float((values > 0).mean()),
        'p10': float(values.quantile(0.10)),
        'p90': float(values.quantile(0.90)),
    }


def account(labels: pd.DataFrame, action: str, start: pd.Timestamp, end: pd.Timestamp, risk: float = 0.01) -> dict[str, Any]:
    return_column = f'{action}_budget_r' if f'{action}_budget_r' in labels.columns else f'{action}_net_r'
    filled = pd.Series(True, index=labels.index)
    if action == 'passive':
        filled = pd.to_numeric(labels['passive_filled'], errors='coerce').fillna(0).astype(int).eq(1)
    rows = labels[
        filled
        & (pd.to_datetime(labels['event_start'], utc=True) >= start)
        & (pd.to_datetime(labels['event_start'], utc=True) < end)
        & labels[return_column].notna()
    ].sort_values(['event_start', 'symbol'], kind='stable')
    nav = peak = 10_000.0
    mdd = 0.0
    occupied_until = start
    trades = 0
    for row in rows.itertuples(index=False):
        event_start = pd.Timestamp(row.event_start)
        event_end = pd.Timestamp(row.event_end)
        if event_start < occupied_until:
            continue
        value = float(getattr(row, return_column))
        account_return = risk * value
        if account_return <= -1:
            nav = 0.0
            trades += 1
            break
        nav *= 1.0 + account_return
        occupied_until = event_end
        trades += 1
        peak = max(peak, nav)
        mdd = max(mdd, 1.0 - nav / peak)
    days = int((end - start) / pd.Timedelta(days=1))
    growth = -1.0 if nav <= 0 else exp(log(nav / 10_000.0) / days) - 1.0
    return {
        'action': action,
        'completed_trades': trades,
        'ending_nav': nav,
        'account_multiple': nav / 10_000.0,
        'geometric_daily_growth': growth,
        'maximum_drawdown': mdd,
    }


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    decision_frames, execution_frames, _ = load_canonical_frames(
        args.data_root, args.repo_root, PRIMARY, args.segments
    )
    candidates = []
    diagnostics_by_symbol = {}
    for symbol, frame in sorted(decision_frames.items()):
        features = build_corpus_features(frame, FeatureConfig())
        rows, diagnostics = generate_corpus_candidates_with_diagnostics(features, symbol)
        candidates.extend(rows)
        diagnostics_by_symbol[symbol] = diagnostics
    candidates.sort(key=lambda row: (row.timestamp, row.symbol, row.family.value, row.side))
    labels = label_event_dataset(candidates, execution_frames, CoarseExecutionConfig())
    labels.to_parquet(args.output / 'EVENT_LABELS.parquet', index=False)
    labels['event_start'] = pd.to_datetime(labels['event_start'], utc=True)
    h1_start = pd.Timestamp('2023-01-01', tz='UTC')
    h1_end = pd.Timestamp('2023-07-01', tz='UTC')
    h2_start = h1_end
    h2_end = pd.Timestamp('2024-01-01', tz='UTC')
    payload: dict[str, Any] = {
        'schema_version': 1,
        'stage': 'PRE2024_RAW_SMC_ALPHA_H1_H2_DIAGNOSTIC_NOT_RANKABLE',
        'candidate_count': len(candidates),
        'resolved_label_count': len(labels),
        'candidate_by_family': dict(sorted(Counter(row.family.value for row in candidates).items())),
        'candidate_by_symbol': dict(sorted(Counter(row.symbol for row in candidates).items())),
        'diagnostics_by_symbol': diagnostics_by_symbol,
        'halves': {},
        'ranking_effect': 'NONE_PRE2024_NOT_RANKABLE',
    }
    for name, start, end in (('H1', h1_start, h1_end), ('H2', h2_start, h2_end)):
        rows = labels[(labels['event_start'] >= start) & (labels['event_start'] < end)]
        half: dict[str, Any] = {
            'rows': len(rows),
            'market': {
                'budget_r': finite_stats(rows['market_budget_r'] if 'market_budget_r' in rows else rows['market_net_r']),
                'raw_stop_r': finite_stats(rows['market_net_r']),
                'target_rate': float(pd.to_numeric(rows['market_target_before_stop'], errors='coerce').mean()) if len(rows) else None,
                'account': account(labels, 'market', start, end),
            },
            'passive': {
                'budget_r_all_nonfills_zero': finite_stats(rows['passive_budget_r'] if 'passive_budget_r' in rows else rows['passive_net_r']),
                'fill_rate': float(pd.to_numeric(rows['passive_filled'], errors='coerce').mean()) if len(rows) else None,
                'account': account(labels, 'passive', start, end),
            },
            'by_family': {},
            'by_symbol': {},
        }
        for family, group in rows.groupby('family'):
            half['by_family'][str(family)] = {
                'count': len(group),
                'market_budget_r': finite_stats(group['market_budget_r'] if 'market_budget_r' in group else group['market_net_r']),
                'passive_budget_r': finite_stats(group['passive_budget_r'] if 'passive_budget_r' in group else group['passive_net_r']),
            }
        for symbol, group in rows.groupby('symbol'):
            half['by_symbol'][str(symbol)] = {
                'count': len(group),
                'market_budget_r': finite_stats(group['market_budget_r'] if 'market_budget_r' in group else group['market_net_r']),
                'passive_budget_r': finite_stats(group['passive_budget_r'] if 'passive_budget_r' in group else group['passive_net_r']),
            }
        payload['halves'][name] = half
    h2_market = payload['halves']['H2']['market']['account']['geometric_daily_growth']
    h2_passive = payload['halves']['H2']['passive']['account']['geometric_daily_growth']
    payload['decision'] = (
        'RAW_ALPHA_POSITIVE_ADVANCE_INTEGRATED_ML'
        if max(h2_market, h2_passive) > 0
        else 'RAW_ALPHA_NEGATIVE_REPAIR_SMC_NARRATIVE_OR_EXIT_GEOMETRY'
    )
    (args.output / 'RAW_ALPHA_RESULT.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n')
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
