#!/usr/bin/env python3
"""Pre-2024 contextual exit-action ML for the unified SMC/ICT candidate set.

Candidate generation is frozen. 2023 Jan-Apr trains, May-Jun calibrates the
abstention threshold, and 2023H2 is untouched validation. The model chooses among
causal market exit contracts, never among future realized outcomes.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from math import exp, log
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from run_exit_geometry_v1 import Bars, Candidate, CostContract, Variant, reconstruct_candidates, simulate


def action_set() -> list[Variant]:
    return [
        Variant('BASELINE'),
        Variant('PD_FAILURE', pd_array_failure_exit=True),
        Variant('CAP_0.75R', target_cap_r=0.75),
        Variant('CAP_0.75R_PD_FAILURE', target_cap_r=0.75, pd_array_failure_exit=True),
        Variant('CAP_1R', target_cap_r=1.0),
        Variant('CAP_1R_PD_FAILURE', target_cap_r=1.0, pd_array_failure_exit=True),
        Variant('CAP_1.5R', target_cap_r=1.5),
        Variant('CAP_1.5R_PD_FAILURE', target_cap_r=1.5, pd_array_failure_exit=True),
        Variant('CAP_2R', target_cap_r=2.0),
        Variant('CAP_2R_PD_FAILURE', target_cap_r=2.0, pd_array_failure_exit=True),
        Variant('PARTIAL_50_AT_0.5R_BE', partial_r=0.5, partial_fraction=0.5, break_even_after_partial=True),
        Variant('PARTIAL_50_AT_0.5R_BE_PD_FAILURE', partial_r=0.5, partial_fraction=0.5, break_even_after_partial=True, pd_array_failure_exit=True),
        Variant('PARTIAL_50_AT_1R_BE', partial_r=1.0, partial_fraction=0.5, break_even_after_partial=True),
        Variant('PARTIAL_50_AT_1R_BE_PD_FAILURE', partial_r=1.0, partial_fraction=0.5, break_even_after_partial=True, pd_array_failure_exit=True),
    ]


def numeric_features(labels: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    excluded_tokens = (
        'net_r', 'budget_r', 'target_before_stop', 'status', 'event_start',
        'event_end', 'passive_filled',
    )
    raw_exact = {
        'open', 'high', 'low', 'close', 'volume', 'turnover', 'trade_count',
        'mark_price', 'index_price', 'open_interest',
    }
    raw_suffixes = (
        '_price', '_level', '_lower', '_upper', '_equilibrium', '_high',
        '_low', '_open', '_close', '_volume', '_turnover', '_trade_count',
        '_open_interest', '_ns', '_ms',
    )
    names = [
        name for name in labels.columns
        if pd.api.types.is_numeric_dtype(labels[name])
        and not any(token in name for token in excluded_tokens)
        and name not in raw_exact
        and not name.endswith(raw_suffixes)
    ]
    candidate_rows = labels.loc[rows['candidate_id'].astype(int)].reset_index(drop=True)
    matrix = candidate_rows[names].replace([np.inf, -np.inf], np.nan).copy()
    matrix['symbol_btc'] = candidate_rows['symbol'].eq('BTCUSDT').astype(float)
    matrix['symbol_eth'] = candidate_rows['symbol'].eq('ETHUSDT').astype(float)
    matrix['family_reversal'] = candidate_rows['family'].astype(str).str.contains('LIQUIDITY_SWEEP').astype(float)
    for name in ('target_cap_r', 'partial_r', 'partial_fraction', 'break_even_after_partial', 'pd_array_failure_exit'):
        matrix[f'action_{name}'] = pd.to_numeric(rows[name], errors='coerce').fillna(0.0).astype(float)
    return matrix


def choose_actions(rows: pd.DataFrame, predictions: np.ndarray, threshold: float) -> pd.DataFrame:
    scored = rows.copy()
    scored['predicted_lower_budget_r'] = predictions
    selected_index = scored.groupby('candidate_id')['predicted_lower_budget_r'].idxmax()
    selected = scored.loc[selected_index].copy()
    return selected[selected['predicted_lower_budget_r'] > threshold]


def account(rows: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, risk_fraction: float = 0.01) -> dict[str, Any]:
    rows = rows[
        (rows['event_start'] >= start) & (rows['event_start'] < end)
        & rows['entry_time'].notna() & rows['exit_time'].notna() & rows['budget_r'].notna()
    ].sort_values(['event_start', 'symbol', 'candidate_id'], kind='stable')
    nav = peak = 10_000.0
    drawdown = 0.0
    occupied_until = start
    returns: list[float] = []
    for row in rows.itertuples(index=False):
        if row.entry_time < occupied_until:
            continue
        value = float(row.budget_r)
        account_return = risk_fraction * value
        if account_return <= -1:
            nav = 0.0
            returns.append(value)
            break
        nav *= 1.0 + account_return
        occupied_until = row.exit_time
        returns.append(value)
        peak = max(peak, nav)
        drawdown = max(drawdown, 1.0 - nav / peak)
    days = int((end - start) / pd.Timedelta(days=1))
    growth = -1.0 if nav <= 0 else exp(log(nav / 10_000.0) / days) - 1.0
    return {
        'completed_trades': len(returns),
        'ending_nav': nav,
        'account_multiple': nav / 10_000.0,
        'geometric_daily_growth': growth,
        'maximum_drawdown': drawdown,
        'mean_budget_r': float(np.mean(returns)) if returns else None,
    }


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    labels = pd.read_pickle(args.labels, compression='gzip').reset_index(drop=True)
    labels['event_start'] = pd.to_datetime(labels['event_start'], utc=True)
    labels['event_end'] = pd.to_datetime(labels['event_end'], utc=True)
    candidates = reconstruct_candidates(labels)
    bars = {
        'BTCUSDT': Bars(pd.read_parquet(args.btc_bars)),
        'ETHUSDT': Bars(pd.read_parquet(args.eth_bars)),
    }
    costs = CostContract()
    outcome_rows: list[dict[str, Any]] = []
    for action in action_set():
        for candidate in candidates:
            outcome = simulate(candidate, bars[candidate.symbol], action, costs)
            outcome_rows.append({
                'candidate_id': candidate.row_id,
                'event_start': candidate.event_start,
                'symbol': candidate.symbol,
                'family': candidate.family,
                'action': action.identifier,
                'target_cap_r': action.target_cap_r or 0.0,
                'partial_r': action.partial_r or 0.0,
                'partial_fraction': action.partial_fraction,
                'break_even_after_partial': float(action.break_even_after_partial),
                'pd_array_failure_exit': float(action.pd_array_failure_exit),
                'entry_time': outcome.entry_time,
                'exit_time': outcome.exit_time,
                'status': outcome.status,
                'budget_r': outcome.budget_r,
            })
    outcomes = pd.DataFrame(outcome_rows)
    outcomes.to_parquet(args.output / 'ACTION_OUTCOMES.parquet', index=False)
    usable = outcomes[
        outcomes['budget_r'].notna() & outcomes['entry_time'].notna() & outcomes['exit_time'].notna()
    ].reset_index(drop=True)
    features = numeric_features(labels, usable)
    target = usable['budget_r'].astype(float).to_numpy()
    dates = pd.to_datetime(usable['event_start'], utc=True)
    training_end = pd.Timestamp('2023-05-01', tz='UTC')
    h1_end = pd.Timestamp('2023-07-01', tz='UTC')
    h2_end = pd.Timestamp('2024-01-01', tz='UTC')
    training = dates < training_end
    calibration = (dates >= training_end) & (dates < h1_end)
    test = (dates >= h1_end) & (dates < h2_end)

    def model(loss: str = 'squared_error', quantile: float | None = None) -> HistGradientBoostingRegressor:
        kwargs: dict[str, Any] = {
            'loss': loss,
            'learning_rate': 0.04,
            'max_leaf_nodes': 15,
            'max_iter': 280,
            'min_samples_leaf': 100,
            'l2_regularization': 3.0,
            'random_state': 20260727,
        }
        if quantile is not None:
            kwargs['quantile'] = quantile
        return HistGradientBoostingRegressor(**kwargs)

    mean_model = model()
    lower_model = model('quantile', 0.20)
    mean_model.fit(features.loc[training], target[training])
    lower_model.fit(features.loc[training], target[training])
    calibration_prediction = (
        0.35 * mean_model.predict(features.loc[calibration])
        + 0.65 * lower_model.predict(features.loc[calibration])
    )
    calibration_rows = usable.loc[calibration].reset_index(drop=True)
    thresholds = np.unique(np.quantile(calibration_prediction, np.linspace(0.10, 0.95, 18)))
    threshold_results = []
    for threshold in thresholds:
        selected = choose_actions(calibration_rows, calibration_prediction, float(threshold))
        metrics = account(selected, training_end, h1_end)
        threshold_results.append({'threshold': float(threshold), 'metrics': metrics})
    eligible = [row for row in threshold_results if row['metrics']['completed_trades'] >= 10]
    selected_threshold = max(
        eligible or threshold_results,
        key=lambda row: (
            row['metrics']['geometric_daily_growth'],
            row['metrics']['mean_budget_r'] or -999.0,
            row['metrics']['completed_trades'],
        ),
    )

    full_h1 = dates < h1_end
    mean_model.fit(features.loc[full_h1], target[full_h1])
    lower_model.fit(features.loc[full_h1], target[full_h1])
    test_prediction = (
        0.35 * mean_model.predict(features.loc[test])
        + 0.65 * lower_model.predict(features.loc[test])
    )
    test_rows = usable.loc[test].reset_index(drop=True)
    selected_h2 = choose_actions(test_rows, test_prediction, selected_threshold['threshold'])
    h2_metrics = account(selected_h2, h1_end, h2_end)
    fixed_actions = {
        str(action): account(group, h1_end, h2_end)
        for action, group in test_rows.groupby('action')
    }
    oracle_index = test_rows.groupby('candidate_id')['budget_r'].idxmax()
    oracle = account(test_rows.loc[oracle_index], h1_end, h2_end)
    payload = {
        'schema_version': 1,
        'stage': 'PRE2024_MULTI_ACTION_EXIT_ML_H1_TRAIN_H2_VALIDATION_NOT_RANKABLE',
        'candidate_count': len(candidates),
        'action_count': len(action_set()),
        'training_rows': int(training.sum()),
        'calibration_rows': int(calibration.sum()),
        'test_rows': int(test.sum()),
        'feature_count': len(features.columns),
        'calibrated_threshold': selected_threshold,
        'H2_selected': h2_metrics,
        'H2_selected_candidate_count': len(selected_h2),
        'H2_action_counts': selected_h2['action'].value_counts().to_dict(),
        'H2_fixed_actions': fixed_actions,
        'H2_oracle_noncausal_upper_bound': oracle,
        'decision': (
            'ADVANCE_MULTI_ACTION_EXIT_POLICY_TO_INTEGRATED_SEQUENTIAL_SCREEN'
            if h2_metrics['geometric_daily_growth'] > 0
            else 'KEEP_SMC_NARRATIVE_REFINE_CONTEXT_OR_ACTION_SET'
        ),
        'ranking_effect': 'NONE_PRE2024_NOT_RANKABLE',
    }
    (args.output / 'MULTI_ACTION_EXIT_ML_RESULT.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n'
    )
    selected_h2.to_csv(args.output / 'H2_SELECTED_ACTIONS.csv', index=False)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--btc-bars', type=Path, required=True)
    parser.add_argument('--eth-bars', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
