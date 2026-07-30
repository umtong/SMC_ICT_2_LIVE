#!/usr/bin/env python3
"""Causal contextual entry+exit action model for the unified SMC/ICT narrative.

The structural candidate is fixed. Candidate actions differ only in implementable
entry and management contracts known at decision time: market confirmation or a
post-confirmation limit at the PD-array proximal edge, consequent encroachment, or
deep mitigation; external target, capped target, PD-array failure, and partial/BE
management. Jan-Apr 2023 trains, May-Jun calibrates abstention, and H2 validates
without action/threshold reselection.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import json
from math import exp, log
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from run_exit_geometry_v1 import Bars, Candidate, CostContract, reconstruct_candidates


@dataclass(frozen=True)
class Action:
    identifier: str
    entry_mode: str = 'MARKET_CONFIRM'
    target_cap_r: float | None = None
    partial_r: float | None = None
    partial_mode: str = "FIXED_R"
    partial_fraction: float = 0.0
    break_even_after_partial: bool = False
    pd_array_failure_exit: bool = False


@dataclass(frozen=True)
class ActionOutcome:
    candidate_id: int
    action: str
    order_end_time: pd.Timestamp | None
    entry_time: pd.Timestamp | None
    exit_time: pd.Timestamp | None
    status: str
    budget_r: float | None
    filled: bool


def actions() -> list[Action]:
    management = [
        ('EXT', None, None, 0.0, False, False),
        ('EXT_PDFAIL', None, None, 0.0, False, True),
        ('CAP1', 1.0, None, 0.0, False, False),
        ('CAP1_PDFAIL', 1.0, None, 0.0, False, True),
        ('CAP1_5', 1.5, None, 0.0, False, False),
        ('CAP1_5_PDFAIL', 1.5, None, 0.0, False, True),
        ('P50_0_5_BE', None, 0.5, 0.5, True, False),
        ('P50_0_5_BE_PDFAIL', None, 0.5, 0.5, True, True),
        ('P50_1_BE', None, 1.0, 0.5, True, False),
        ('P50_1_BE_PDFAIL', None, 1.0, 0.5, True, True),
        ('INTERNAL50_BE', None, None, 0.5, True, False),
        ('INTERNAL50_BE_PDFAIL', None, None, 0.5, True, True),
        ('INTERNAL75_BE', None, None, 0.75, True, False),
        ('INTERNAL75_BE_PDFAIL', None, None, 0.75, True, True),
    ]
    result: list[Action] = []
    for entry_mode in ('MARKET_CONFIRM', 'LIMIT_PROXIMAL', 'LIMIT_CE', 'LIMIT_DEEP'):
        for name, cap, partial_r, fraction, be, failure in management:
            # PD-array failure is meaningful only when a reconstructable PD array exists;
            # simulator falls back to structural stop otherwise.
            result.append(Action(
                identifier=f'{entry_mode}__{name}',
                entry_mode=entry_mode,
                target_cap_r=cap,
                partial_r=partial_r,
                partial_mode=("INTERNAL_TARGET" if name.startswith("INTERNAL") else "FIXED_R"),
                partial_fraction=fraction,
                break_even_after_partial=be,
                pd_array_failure_exit=failure,
            ))
    return result


def limit_reference(candidate: Candidate, mode: str) -> float | None:
    if candidate.zone_lower is None or candidate.zone_upper is None:
        return None
    lower, upper = sorted((float(candidate.zone_lower), float(candidate.zone_upper)))
    if mode == 'LIMIT_CE':
        return (lower + upper) / 2.0
    if mode == 'LIMIT_PROXIMAL':
        return upper if candidate.side > 0 else lower
    if mode == 'LIMIT_DEEP':
        # 75% mitigation from the proximal edge toward the distal edge.
        return lower + 0.25 * (upper - lower) if candidate.side > 0 else lower + 0.75 * (upper - lower)
    return None


def spread_fraction(value: float, costs: CostContract) -> float:
    return max(float(value), costs.minimum_spread_bps) / 10_000.0


def market_fill(base: float, side: int, spread_bps: float, slippage_bps: float, costs: CostContract) -> float:
    adverse = spread_fraction(spread_bps, costs) / 2.0 + slippage_bps / 10_000.0
    return float(base) * (1.0 + side * adverse)


def target_fill(target: float, side: int, spread_bps: float, costs: CostContract) -> float:
    return market_fill(target, -side, spread_bps, costs.market_slippage_bps, costs)


def stop_fill(open_price: float, stop: float, side: int, spread_bps: float, costs: CostContract) -> float:
    base = min(float(open_price), stop) if side > 0 else max(float(open_price), stop)
    return market_fill(base, -side, spread_bps, costs.stop_slippage_bps, costs)


def loss_budget(candidate: Candidate, entry: float, entry_fee_rate: float, costs: CostContract) -> float:
    half_spread = costs.minimum_spread_bps / 20_000.0
    stop_rate = costs.taker_fee_rate + costs.stop_slippage_bps / 10_000.0 + half_spread
    return abs(entry - candidate.stop_reference) + abs(entry) * entry_fee_rate + abs(candidate.stop_reference) * stop_rate


def first_cross(candidate: Candidate, bars: Bars, start: int, limit: float, end: int) -> tuple[int | None, str]:
    for pos in range(start, end):
        stop_touched = bars.low[pos] <= candidate.stop_reference if candidate.side > 0 else bars.high[pos] >= candidate.stop_reference
        target_touched = bars.high[pos] >= candidate.target_reference if candidate.side > 0 else bars.low[pos] <= candidate.target_reference
        crossed = bars.low[pos] < limit if candidate.side > 0 else bars.high[pos] > limit
        if stop_touched:
            return pos, 'CANCELLED_STOP_BEFORE_FILL'
        if target_touched:
            return pos, 'CANCELLED_TARGET_BEFORE_FILL'
        if crossed:
            return pos, 'FILLED'
    return None, 'UNRESOLVED_NO_FILL'


def simulate(
    candidate: Candidate,
    bars: Bars,
    action: Action,
    costs: CostContract,
    evaluation_end: pd.Timestamp,
    internal_target: float | None = None,
) -> ActionOutcome:
    activation = candidate.event_start + pd.Timedelta(milliseconds=costs.activation_latency_ms)
    start = int(np.searchsorted(bars.time_ns, activation.value, side='left'))
    end = int(np.searchsorted(bars.time_ns, evaluation_end.value, side='left'))
    end = min(end, len(bars.time))
    if start >= end:
        return ActionOutcome(candidate.row_id, action.identifier, None, None, None, 'NO_EXECUTION_BAR', None, False)

    if action.entry_mode == 'MARKET_CONFIRM':
        entry_pos = start
        entry = market_fill(bars.open[entry_pos], candidate.side, bars.spread[entry_pos], costs.market_slippage_bps, costs)
        entry_fee_rate = costs.taker_fee_rate
    else:
        limit = limit_reference(candidate, action.entry_mode)
        if limit is None:
            return ActionOutcome(candidate.row_id, action.identifier, bars.time[start], None, None, 'NO_PD_ARRAY', 0.0, False)
        if candidate.side * (limit - candidate.stop_reference) <= 0 or candidate.side * (candidate.target_reference - limit) <= 0:
            return ActionOutcome(candidate.row_id, action.identifier, bars.time[start], None, None, 'INVALID_LIMIT_GEOMETRY', 0.0, False)
        entry_pos, status = first_cross(candidate, bars, start, limit, end)
        if entry_pos is None:
            return ActionOutcome(candidate.row_id, action.identifier, bars.time[end - 1], None, None, status, 0.0, False)
        if status != 'FILLED':
            return ActionOutcome(candidate.row_id, action.identifier, bars.time[entry_pos], None, None, status, 0.0, False)
        entry = float(limit)
        entry_fee_rate = costs.maker_fee_rate

    if candidate.side * (entry - candidate.stop_reference) <= 0:
        return ActionOutcome(candidate.row_id, action.identifier, bars.time[entry_pos], None, None, 'INVALID_ENTRY', 0.0, False)
    target = candidate.target_reference
    stop_distance = abs(entry - candidate.stop_reference)
    if action.target_cap_r is not None:
        cap = entry + candidate.side * action.target_cap_r * stop_distance
        target = min(target, cap) if candidate.side > 0 else max(target, cap)
    if candidate.side * (target - entry) <= 0:
        return ActionOutcome(candidate.row_id, action.identifier, bars.time[entry_pos], None, None, 'INVALID_TARGET', 0.0, False)

    budget = loss_budget(candidate, entry, entry_fee_rate, costs)
    pnl = -entry * entry_fee_rate
    remaining = 1.0
    partial_hit = False
    current_stop = candidate.stop_reference
    failure_pending = False
    for pos in range(entry_pos, end):
        if failure_pending:
            exit_price = market_fill(bars.open[pos], -candidate.side, bars.spread[pos], costs.market_slippage_bps, costs)
            pnl += remaining * (candidate.side * (exit_price - entry) - exit_price * costs.taker_fee_rate)
            return ActionOutcome(candidate.row_id, action.identifier, bars.time[pos], bars.time[entry_pos], bars.time[pos], 'PD_ARRAY_FAILURE', pnl / budget, True)
        stop_touched = bars.low[pos] <= current_stop if candidate.side > 0 else bars.high[pos] >= current_stop
        target_touched = bars.high[pos] >= target if candidate.side > 0 else bars.low[pos] <= target
        if stop_touched:
            exit_price = stop_fill(bars.open[pos], current_stop, candidate.side, bars.spread[pos], costs)
            pnl += remaining * (candidate.side * (exit_price - entry) - exit_price * costs.taker_fee_rate)
            return ActionOutcome(candidate.row_id, action.identifier, bars.time[pos], bars.time[entry_pos], bars.time[pos], 'STOP', pnl / budget, True)
        if target_touched:
            exit_price = target_fill(target, candidate.side, bars.spread[pos], costs)
            pnl += remaining * (candidate.side * (exit_price - entry) - exit_price * costs.taker_fee_rate)
            return ActionOutcome(candidate.row_id, action.identifier, bars.time[pos], bars.time[entry_pos], bars.time[pos], 'TARGET', pnl / budget, True)
        partial_enabled = action.partial_r is not None or action.partial_mode == "INTERNAL_TARGET"
        if partial_enabled and not partial_hit:
            if action.partial_mode == "INTERNAL_TARGET":
                level = internal_target
                if level is None or not np.isfinite(float(level)):
                    level = None
                elif candidate.side * (float(level) - entry) <= 0 or candidate.side * (target - float(level)) < 0:
                    level = None
            else:
                level = entry + candidate.side * float(action.partial_r) * stop_distance
            touched = (
                False if level is None else
                bars.high[pos] >= float(level) if candidate.side > 0 else bars.low[pos] <= float(level)
            )
            if touched:
                exit_price = target_fill(float(level), candidate.side, bars.spread[pos], costs)
                pnl += action.partial_fraction * (candidate.side * (exit_price - entry) - exit_price * costs.taker_fee_rate)
                remaining -= action.partial_fraction
                partial_hit = True
                if action.break_even_after_partial:
                    # Cost-recovery stop, not nominal entry BE.
                    if candidate.side > 0:
                        current_stop = entry * (1.0 + entry_fee_rate) / (1.0 - costs.taker_fee_rate - costs.market_slippage_bps / 10_000.0)
                    else:
                        current_stop = entry * (1.0 - entry_fee_rate) / (1.0 + costs.taker_fee_rate + costs.market_slippage_bps / 10_000.0)
        if action.pd_array_failure_exit and candidate.zone_lower is not None and candidate.zone_upper is not None:
            failed = bars.close[pos] < candidate.zone_lower if candidate.side > 0 else bars.close[pos] > candidate.zone_upper
            if failed:
                if pos + 1 < end:
                    failure_pending = True
                else:
                    exit_price = market_fill(bars.close[pos], -candidate.side, bars.spread[pos], costs.market_slippage_bps, costs)
                    pnl += remaining * (candidate.side * (exit_price - entry) - exit_price * costs.taker_fee_rate)
                    return ActionOutcome(candidate.row_id, action.identifier, bars.time[pos], bars.time[entry_pos], bars.time[pos], 'PD_ARRAY_FAILURE', pnl / budget, True)
    return ActionOutcome(candidate.row_id, action.identifier, bars.time[end - 1], bars.time[entry_pos], None, 'CENSORED_AT_PERIOD_END', None, True)


def model_features(labels: pd.DataFrame, action_rows: pd.DataFrame) -> pd.DataFrame:
    forbidden = ('net_r', 'budget_r', 'target_before_stop', 'event_start', 'event_end', 'passive_filled')
    raw_exact = {'open', 'high', 'low', 'close', 'volume', 'turnover', 'trade_count', 'mark_price', 'index_price', 'open_interest'}
    raw_suffixes = ('_price', '_level', '_lower', '_upper', '_equilibrium', '_high', '_low', '_open', '_close', '_volume', '_turnover', '_trade_count', '_open_interest', '_ns', '_ms')
    names = [
        name for name in labels.columns
        if pd.api.types.is_numeric_dtype(labels[name])
        and not any(token in name for token in forbidden)
        and name not in raw_exact and not name.endswith(raw_suffixes)
    ]
    source = labels.loc[action_rows['candidate_id'].astype(int)].reset_index(drop=True)
    matrix = source[names].replace([np.inf, -np.inf], np.nan).copy()
    matrix['symbol_btc'] = source['symbol'].eq('BTCUSDT').astype(float)
    matrix['symbol_eth'] = source['symbol'].eq('ETHUSDT').astype(float)
    matrix['family_reversal'] = source['family'].astype(str).str.contains('LIQUIDITY_SWEEP').astype(float)
    for mode in ('MARKET_CONFIRM', 'LIMIT_PROXIMAL', 'LIMIT_CE', 'LIMIT_DEEP'):
        matrix[f'action_entry_{mode.lower()}'] = action_rows['entry_mode'].eq(mode).astype(float).to_numpy()
    for name in ('target_cap_r', 'partial_r', 'partial_fraction', 'break_even_after_partial', 'pd_array_failure_exit'):
        matrix[f'action_{name}'] = pd.to_numeric(action_rows[name], errors='coerce').fillna(0.0).astype(float).to_numpy()
    matrix['action_partial_internal_target'] = action_rows['partial_mode'].eq('INTERNAL_TARGET').astype(float).to_numpy()
    return matrix


def choose(rows: pd.DataFrame, prediction: np.ndarray, threshold: float) -> pd.DataFrame:
    out = rows.copy()
    out['predicted_lower_budget_r'] = prediction
    indices = out.groupby('candidate_id')['predicted_lower_budget_r'].idxmax()
    selected = out.loc[indices].copy()
    return selected[selected['predicted_lower_budget_r'] > threshold]


def account(rows: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, risk: float = 0.01) -> dict[str, Any]:
    rows = rows[(rows['event_start'] >= start) & (rows['event_start'] < end)].sort_values(['event_start', 'symbol', 'candidate_id'], kind='stable')
    nav = peak = 10_000.0
    mdd = 0.0
    slot_free = start
    values: list[float] = []
    filled = 0
    action_counts: dict[str, int] = {}
    for row in rows.itertuples(index=False):
        if row.event_start < slot_free:
            continue
        if row.order_end_time is None:
            continue
        slot_free = pd.Timestamp(row.order_end_time)
        action_counts[row.identifier] = action_counts.get(row.identifier, 0) + 1
        if not bool(row.filled) or row.budget_r is None or not np.isfinite(float(row.budget_r)):
            continue
        value = float(row.budget_r)
        account_return = risk * value
        if account_return <= -1:
            nav = 0.0
            values.append(value)
            filled += 1
            break
        nav *= 1.0 + account_return
        values.append(value)
        filled += 1
        peak = max(peak, nav)
        mdd = max(mdd, 1.0 - nav / peak)
    days = int((end - start) / pd.Timedelta(days=1))
    growth = -1.0 if nav <= 0 else exp(log(nav / 10_000.0) / days) - 1.0
    return {
        'orders': sum(action_counts.values()),
        'filled_trades': filled,
        'ending_nav': nav,
        'account_multiple': nav / 10_000.0,
        'geometric_daily_growth': growth,
        'maximum_drawdown': mdd,
        'mean_budget_r': float(np.mean(values)) if values else None,
        'action_counts': action_counts,
    }


def make_model(loss: str = 'squared_error', quantile: float | None = None) -> HistGradientBoostingRegressor:
    kwargs: dict[str, Any] = {
        'loss': loss,
        'learning_rate': 0.04,
        'max_leaf_nodes': 15,
        'max_iter': 300,
        'min_samples_leaf': 120,
        'l2_regularization': 4.0,
        'random_state': 20260727,
    }
    if quantile is not None:
        kwargs['quantile'] = quantile
    return HistGradientBoostingRegressor(**kwargs)


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    labels = pd.read_parquet(args.labels).reset_index(drop=True) if args.labels.suffix == '.parquet' else pd.read_pickle(args.labels, compression='gzip').reset_index(drop=True)
    labels['event_start'] = pd.to_datetime(labels['event_start'], utc=True)
    labels['event_end'] = pd.to_datetime(labels['event_end'], utc=True)
    candidates = reconstruct_candidates(labels)
    internal_targets = {
        int(index): (
            float(value) if pd.notna(value) and np.isfinite(float(value)) else None
        )
        for index, value in labels.get(
            'execution_internal_target_reference',
            pd.Series(np.nan, index=labels.index),
        ).items()
    }
    bars = {'BTCUSDT': Bars(pd.read_parquet(args.btc_bars)), 'ETHUSDT': Bars(pd.read_parquet(args.eth_bars))}
    costs = CostContract()
    evaluation_end = pd.Timestamp('2024-01-01', tz='UTC')
    rows: list[dict[str, Any]] = []
    for action in actions():
        for candidate in candidates:
            outcome = simulate(
                candidate, bars[candidate.symbol], action, costs, evaluation_end,
                internal_target=internal_targets.get(candidate.row_id),
            )
            rows.append({
                'candidate_id': candidate.row_id,
                'event_start': candidate.event_start,
                'symbol': candidate.symbol,
                'family': candidate.family,
                **asdict(action),
                'order_end_time': outcome.order_end_time,
                'entry_time': outcome.entry_time,
                'exit_time': outcome.exit_time,
                'status': outcome.status,
                'budget_r': outcome.budget_r,
                'filled': outcome.filled,
            })
    outcomes = pd.DataFrame(rows)
    outcomes.to_parquet(args.output / 'ENTRY_EXIT_ACTION_OUTCOMES.parquet', index=False)
    # Nonfills are valid zero-return action labels; censored filled trades are excluded.
    usable = outcomes[
        outcomes['budget_r'].notna() & outcomes['order_end_time'].notna()
    ].reset_index(drop=True)
    features = model_features(labels, usable)
    target = usable['budget_r'].astype(float).to_numpy()
    dates = pd.to_datetime(usable['event_start'], utc=True)
    train_end = pd.Timestamp('2023-05-01', tz='UTC')
    h1_end = pd.Timestamp('2023-07-01', tz='UTC')
    h2_end = pd.Timestamp('2024-01-01', tz='UTC')
    training = dates < train_end
    calibration = (dates >= train_end) & (dates < h1_end)
    test = (dates >= h1_end) & (dates < h2_end)
    mean_model = make_model()
    lower_model = make_model('quantile', 0.20)
    mean_model.fit(features.loc[training], target[training])
    lower_model.fit(features.loc[training], target[training])
    calibration_prediction = 0.35 * mean_model.predict(features.loc[calibration]) + 0.65 * lower_model.predict(features.loc[calibration])
    calibration_rows = usable.loc[calibration].reset_index(drop=True)
    threshold_rows = []
    for threshold in np.unique(np.quantile(calibration_prediction, np.linspace(0.10, 0.98, 24))):
        selected = choose(calibration_rows, calibration_prediction, float(threshold))
        metrics = account(selected, train_end, h1_end)
        threshold_rows.append({'threshold': float(threshold), 'metrics': metrics})
    eligible = [row for row in threshold_rows if row['metrics']['filled_trades'] >= 10]
    threshold_choice = max(
        eligible or threshold_rows,
        key=lambda row: (row['metrics']['geometric_daily_growth'], row['metrics']['mean_budget_r'] or -999.0, row['metrics']['filled_trades']),
    )
    full_h1 = dates < h1_end
    mean_model.fit(features.loc[full_h1], target[full_h1])
    lower_model.fit(features.loc[full_h1], target[full_h1])
    test_prediction = 0.35 * mean_model.predict(features.loc[test]) + 0.65 * lower_model.predict(features.loc[test])
    test_rows = usable.loc[test].reset_index(drop=True)
    selected_h2 = choose(test_rows, test_prediction, threshold_choice['threshold'])
    h2_metrics = account(selected_h2, h1_end, h2_end)
    fixed = {str(name): account(group, h1_end, h2_end) for name, group in test_rows.groupby('identifier')}
    oracle = account(test_rows.loc[test_rows.groupby('candidate_id')['budget_r'].idxmax()], h1_end, h2_end)
    payload = {
        'schema_version': 1,
        'stage': 'PRE2024_CONTEXTUAL_PD_ARRAY_ENTRY_EXIT_ML_H1_H2_NOT_RANKABLE',
        'candidate_count': len(candidates),
        'action_count': len(actions()),
        'usable_action_rows': len(usable),
        'feature_count': len(features.columns),
        'training_rows': int(training.sum()),
        'calibration_rows': int(calibration.sum()),
        'test_rows': int(test.sum()),
        'threshold_choice': threshold_choice,
        'H2_selected': h2_metrics,
        'H2_selected_candidate_count': len(selected_h2),
        'H2_selected_actions': selected_h2['identifier'].value_counts().to_dict(),
        'H2_fixed_actions': fixed,
        'H2_oracle_noncausal_upper_bound': oracle,
        'decision': 'ADVANCE_CONTEXTUAL_ENTRY_EXIT_POLICY' if h2_metrics['geometric_daily_growth'] > 0 else 'KEEP_SMC_PREMISE_REFINE_PD_ARRAY_OR_CONTEXT',
        'ranking_effect': 'NONE_PRE2024_NOT_RANKABLE',
    }
    (args.output / 'ENTRY_EXIT_ACTION_ML_RESULT.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n')
    selected_h2.to_csv(args.output / 'H2_SELECTED_ENTRY_EXIT_ACTIONS.csv', index=False)
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
