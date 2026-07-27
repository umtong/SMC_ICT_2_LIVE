#!/usr/bin/env python3
"""Causal pre-2024 exit-geometry research for the unified SMC/ICT narrative.

The candidate narrative is held fixed. 2023H1 is used to choose an exit contract;
2023H2 is a frozen validation.  The script reconstructs exact candidate geometry
from the immutable event-label artifact and replays marketable entries on canonical
1-minute Bybit bars with the same 500ms, fee, spread and slippage assumptions as
the coarse engine. It does not open 2024 or alter ranking authority.
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


@dataclass(frozen=True)
class CostContract:
    activation_latency_ms: int = 500
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.00055
    market_slippage_bps: float = 2.0
    stop_slippage_bps: float = 4.0
    minimum_spread_bps: float = 0.5


@dataclass(frozen=True)
class Candidate:
    row_id: int
    event_start: pd.Timestamp
    event_end: pd.Timestamp
    symbol: str
    family: str
    side: int
    entry_reference: float
    stop_reference: float
    target_reference: float
    atr: float
    stop_distance: float
    target_distance: float
    zone_lower: float | None
    zone_upper: float | None


@dataclass(frozen=True)
class Variant:
    identifier: str
    target_cap_r: float | None = None
    partial_r: float | None = None
    partial_fraction: float = 0.0
    break_even_after_partial: bool = False
    pd_array_failure_exit: bool = False


@dataclass(frozen=True)
class Outcome:
    row_id: int
    variant: str
    entry_time: pd.Timestamp | None
    exit_time: pd.Timestamp | None
    status: str
    budget_r: float | None
    raw_stop_r: float | None
    partial_hit: bool


def finite(row: pd.Series, names: Iterable[str]) -> float | None:
    for name in names:
        if name in row.index and pd.notna(row[name]):
            value = float(row[name])
            if np.isfinite(value):
                return value
    return None


def reconstruct_candidates(labels: pd.DataFrame) -> list[Candidate]:
    result: list[Candidate] = []
    for row_id, row in labels.reset_index(drop=True).iterrows():
        event_start = pd.Timestamp(row['event_start'])
        event_start = event_start.tz_localize('UTC') if event_start.tzinfo is None else event_start.tz_convert('UTC')
        event_end = pd.Timestamp(row['event_end'])
        event_end = event_end.tz_localize('UTC') if event_end.tzinfo is None else event_end.tz_convert('UTC')
        side = int(row['side'])
        atr = finite(row, ('atr',))
        atr_fraction = finite(row, ('atr_fraction',))
        entry = finite(row, ('entry_reference', 'entry_ref', 'decision_price'))
        if entry is None:
            if atr is None or atr_fraction is None or atr_fraction <= 0:
                raise ValueError(f'cannot reconstruct entry for row {row_id}')
            entry = atr / atr_fraction
        stop_fraction = finite(row, ('stop_distance_fraction',))
        stop_atr = finite(row, ('stop_distance_atr',))
        if stop_fraction is not None:
            stop_distance = stop_fraction * entry
        elif atr is not None and stop_atr is not None:
            stop_distance = stop_atr * atr
        else:
            raise ValueError(f'cannot reconstruct stop for row {row_id}')
        target_fraction = finite(row, ('target_distance_fraction',))
        target_atr = finite(row, ('target_distance_atr',))
        raw_rr = finite(row, ('raw_reward_risk', 'raw_structural_reward_risk'))
        if target_fraction is not None:
            target_distance = target_fraction * entry
        elif atr is not None and target_atr is not None:
            target_distance = target_atr * atr
        elif raw_rr is not None:
            target_distance = raw_rr * stop_distance
        else:
            raise ValueError(f'cannot reconstruct target for row {row_id}')
        stop = entry - side * stop_distance
        target = entry + side * target_distance
        zone_mid_distance = finite(row, ('zone_midpoint_distance_atr', 'retest_midpoint_distance_atr'))
        zone_width_atr = finite(row, ('zone_width_atr',))
        zone_lower = zone_upper = None
        if atr is not None and zone_mid_distance is not None and zone_width_atr is not None:
            midpoint = entry - zone_mid_distance * atr
            width = max(0.0, zone_width_atr * atr)
            zone_lower = midpoint - width / 2.0
            zone_upper = midpoint + width / 2.0
        result.append(Candidate(
            row_id=row_id,
            event_start=event_start,
            event_end=event_end,
            symbol=str(row['symbol']),
            family=str(row['family']),
            side=side,
            entry_reference=float(entry),
            stop_reference=float(stop),
            target_reference=float(target),
            atr=float(atr or 0.0),
            stop_distance=float(stop_distance),
            target_distance=float(target_distance),
            zone_lower=zone_lower,
            zone_upper=zone_upper,
        ))
    return result


def normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for source, target in (
        ('open_price', 'open'), ('high_price', 'high'),
        ('low_price', 'low'), ('close_price', 'close'),
    ):
        if target not in out.columns and source in out.columns:
            out[target] = out[source]
    timestamp = next((name for name in ('start_time_ms', 'timestamp_ms') if name in out.columns), None)
    if timestamp is None:
        raise ValueError('canonical trade bars have no epoch-ms timestamp')
    out['bar_start'] = pd.to_datetime(pd.to_numeric(out[timestamp]), unit='ms', utc=True)
    for name in ('open', 'high', 'low', 'close'):
        out[name] = pd.to_numeric(out[name], errors='coerce')
    out['spread_bps'] = pd.to_numeric(out.get('spread_bps', 0.5), errors='coerce').fillna(0.5)
    return out.dropna(subset=['bar_start', 'open', 'high', 'low', 'close']).sort_values('bar_start').drop_duplicates('bar_start').reset_index(drop=True)


class Bars:
    def __init__(self, frame: pd.DataFrame) -> None:
        frame = normalize_bars(frame)
        self.time = pd.DatetimeIndex(frame['bar_start'])
        self.time_ns = self.time.asi8
        self.open = frame['open'].to_numpy(float)
        self.high = frame['high'].to_numpy(float)
        self.low = frame['low'].to_numpy(float)
        self.close = frame['close'].to_numpy(float)
        self.spread = frame['spread_bps'].to_numpy(float)


def spread_fraction(spread_bps: float, costs: CostContract) -> float:
    return max(float(spread_bps), costs.minimum_spread_bps) / 10_000.0


def market_fill(base: float, side: int, spread_bps: float, slippage_bps: float, costs: CostContract) -> float:
    adverse = spread_fraction(spread_bps, costs) / 2.0 + slippage_bps / 10_000.0
    return float(base) * (1.0 + side * adverse)


def stop_fill(open_price: float, stop: float, side: int, spread_bps: float, costs: CostContract) -> float:
    base = min(float(open_price), stop) if side > 0 else max(float(open_price), stop)
    return market_fill(base, -side, spread_bps, costs.stop_slippage_bps, costs)


def target_fill(target: float, side: int, spread_bps: float, costs: CostContract) -> float:
    return market_fill(target, -side, spread_bps, costs.market_slippage_bps, costs)


def planned_loss_budget(candidate: Candidate, entry: float, costs: CostContract) -> float:
    half_spread = costs.minimum_spread_bps / 20_000.0
    entry_rate = costs.taker_fee_rate + costs.market_slippage_bps / 10_000.0 + half_spread
    stop_rate = costs.taker_fee_rate + costs.stop_slippage_bps / 10_000.0 + half_spread
    return (
        abs(entry - candidate.stop_reference)
        + abs(candidate.entry_reference) * entry_rate
        + abs(candidate.stop_reference) * stop_rate
    )


def simulate(candidate: Candidate, bars: Bars, variant: Variant, costs: CostContract) -> Outcome:
    activation = candidate.event_start + pd.Timedelta(milliseconds=costs.activation_latency_ms)
    position = int(np.searchsorted(bars.time_ns, activation.value, side='left'))
    if position >= len(bars.time):
        return Outcome(candidate.row_id, variant.identifier, None, None, 'NO_BAR', None, None, False)
    end_position = int(np.searchsorted(bars.time_ns, candidate.event_end.value, side='right'))
    end_position = min(max(end_position, position + 1), len(bars.time))
    entry = market_fill(bars.open[position], candidate.side, bars.spread[position], costs.market_slippage_bps, costs)
    if candidate.side * (entry - candidate.stop_reference) <= 0:
        return Outcome(candidate.row_id, variant.identifier, None, bars.time[position], 'INVALID_ENTRY', None, None, False)
    target = candidate.target_reference
    if variant.target_cap_r is not None:
        cap = entry + candidate.side * variant.target_cap_r * candidate.stop_distance
        target = min(target, cap) if candidate.side > 0 else max(target, cap)
    if candidate.side * (target - entry) <= 0:
        return Outcome(candidate.row_id, variant.identifier, None, bars.time[position], 'INVALID_TARGET', None, None, False)
    entry_fee = entry * costs.taker_fee_rate
    budget = planned_loss_budget(candidate, entry, costs)
    raw_stop = abs(entry - candidate.stop_reference)
    current_stop = candidate.stop_reference
    remaining = 1.0
    pnl = -entry_fee
    partial_hit = False
    failure_pending = False
    for offset in range(position, end_position):
        if failure_pending:
            exit_price = market_fill(bars.open[offset], -candidate.side, bars.spread[offset], costs.market_slippage_bps, costs)
            pnl += remaining * (candidate.side * (exit_price - entry) - exit_price * costs.taker_fee_rate)
            return Outcome(candidate.row_id, variant.identifier, bars.time[position], bars.time[offset], 'PD_ARRAY_FAILURE', pnl / budget, pnl / raw_stop, partial_hit)
        stop_touched = bars.low[offset] <= current_stop if candidate.side > 0 else bars.high[offset] >= current_stop
        target_touched = bars.high[offset] >= target if candidate.side > 0 else bars.low[offset] <= target
        if stop_touched:
            exit_price = stop_fill(bars.open[offset], current_stop, candidate.side, bars.spread[offset], costs)
            pnl += remaining * (candidate.side * (exit_price - entry) - exit_price * costs.taker_fee_rate)
            return Outcome(candidate.row_id, variant.identifier, bars.time[position], bars.time[offset], 'STOP', pnl / budget, pnl / raw_stop, partial_hit)
        if target_touched:
            exit_price = target_fill(target, candidate.side, bars.spread[offset], costs)
            pnl += remaining * (candidate.side * (exit_price - entry) - exit_price * costs.taker_fee_rate)
            return Outcome(candidate.row_id, variant.identifier, bars.time[position], bars.time[offset], 'TARGET', pnl / budget, pnl / raw_stop, partial_hit)
        if variant.partial_r is not None and not partial_hit:
            partial_level = entry + candidate.side * variant.partial_r * candidate.stop_distance
            touched = bars.high[offset] >= partial_level if candidate.side > 0 else bars.low[offset] <= partial_level
            if touched:
                exit_price = target_fill(partial_level, candidate.side, bars.spread[offset], costs)
                quantity = variant.partial_fraction
                pnl += quantity * (candidate.side * (exit_price - entry) - exit_price * costs.taker_fee_rate)
                remaining -= quantity
                partial_hit = True
                if variant.break_even_after_partial:
                    if candidate.side > 0:
                        current_stop = entry * (1.0 + costs.taker_fee_rate) / (1.0 - costs.taker_fee_rate - costs.market_slippage_bps / 10_000.0)
                    else:
                        current_stop = entry * (1.0 - costs.taker_fee_rate) / (1.0 + costs.taker_fee_rate + costs.market_slippage_bps / 10_000.0)
        if variant.pd_array_failure_exit and candidate.zone_lower is not None and candidate.zone_upper is not None:
            failed = bars.close[offset] < candidate.zone_lower if candidate.side > 0 else bars.close[offset] > candidate.zone_upper
            if failed:
                if offset + 1 < end_position:
                    failure_pending = True
                else:
                    exit_price = market_fill(bars.close[offset], -candidate.side, bars.spread[offset], costs.market_slippage_bps, costs)
                    pnl += remaining * (candidate.side * (exit_price - entry) - exit_price * costs.taker_fee_rate)
                    return Outcome(candidate.row_id, variant.identifier, bars.time[position], bars.time[offset], 'PD_ARRAY_FAILURE', pnl / budget, pnl / raw_stop, partial_hit)
    return Outcome(candidate.row_id, variant.identifier, bars.time[position], None, 'CENSORED', None, None, partial_hit)


def independent_metrics(rows: pd.DataFrame, half: str) -> dict[str, Any]:
    start = pd.Timestamp('2023-01-01', tz='UTC') if half == 'H1' else pd.Timestamp('2023-07-01', tz='UTC')
    end = pd.Timestamp('2023-07-01', tz='UTC') if half == 'H1' else pd.Timestamp('2024-01-01', tz='UTC')
    selected = rows[(rows['event_start'] >= start) & (rows['event_start'] < end) & rows['budget_r'].notna()].copy()
    return {
        'count': int(len(selected)),
        'mean_budget_r': float(selected['budget_r'].mean()) if len(selected) else None,
        'median_budget_r': float(selected['budget_r'].median()) if len(selected) else None,
        'positive_fraction': float((selected['budget_r'] > 0).mean()) if len(selected) else None,
        'sum_budget_r': float(selected['budget_r'].sum()) if len(selected) else None,
        'status_counts': selected['status'].value_counts().to_dict(),
    }


def sequential_account(rows: pd.DataFrame, half: str, risk_fraction: float = 0.01) -> dict[str, Any]:
    start = pd.Timestamp('2023-01-01', tz='UTC') if half == 'H1' else pd.Timestamp('2023-07-01', tz='UTC')
    end = pd.Timestamp('2023-07-01', tz='UTC') if half == 'H1' else pd.Timestamp('2024-01-01', tz='UTC')
    selected = rows[
        (rows['event_start'] >= start) & (rows['event_start'] < end)
        & rows['entry_time'].notna() & rows['exit_time'].notna() & rows['budget_r'].notna()
    ].sort_values(['event_start', 'symbol', 'row_id'], kind='stable')
    nav = peak = 10_000.0
    maximum_drawdown = 0.0
    occupied_until = start
    trades = 0
    for row in selected.itertuples(index=False):
        if row.entry_time < occupied_until:
            continue
        account_return = risk_fraction * float(row.budget_r)
        if account_return <= -1:
            nav = 0.0
            trades += 1
            break
        nav *= 1.0 + account_return
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, 1.0 - nav / peak)
        occupied_until = row.exit_time
        trades += 1
    days = int((end - start) / pd.Timedelta(days=1))
    growth = -1.0 if nav <= 0 else exp(log(nav / 10_000.0) / days) - 1.0
    return {
        'completed_trades': trades,
        'ending_nav': nav,
        'account_multiple': nav / 10_000.0,
        'geometric_daily_growth': growth,
        'maximum_drawdown': maximum_drawdown,
    }


def variants() -> list[Variant]:
    result = [Variant('BASELINE'), Variant('PD_FAILURE', pd_array_failure_exit=True)]
    for cap in (0.4, 0.5, 0.6, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0):
        result.append(Variant(f'CAP_{cap:g}R', target_cap_r=cap))
        result.append(Variant(f'CAP_{cap:g}R_PD_FAILURE', target_cap_r=cap, pd_array_failure_exit=True))
    for partial_r in (0.4, 0.5, 0.75, 1.0):
        for fraction in (0.25, 0.5, 0.75):
            result.append(Variant(f'PARTIAL_{fraction:g}_AT_{partial_r:g}R', partial_r=partial_r, partial_fraction=fraction))
            result.append(Variant(f'PARTIAL_{fraction:g}_AT_{partial_r:g}R_BE', partial_r=partial_r, partial_fraction=fraction, break_even_after_partial=True))
            result.append(Variant(f'PARTIAL_{fraction:g}_AT_{partial_r:g}R_BE_PD_FAILURE', partial_r=partial_r, partial_fraction=fraction, break_even_after_partial=True, pd_array_failure_exit=True))
    return result


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    labels = pd.read_pickle(args.labels, compression='gzip')
    labels['event_start'] = pd.to_datetime(labels['event_start'], utc=True)
    labels['event_end'] = pd.to_datetime(labels['event_end'], utc=True)
    candidates = reconstruct_candidates(labels)
    by_id = {candidate.row_id: candidate for candidate in candidates}
    bars = {
        'BTCUSDT': Bars(pd.read_parquet(args.btc_bars)),
        'ETHUSDT': Bars(pd.read_parquet(args.eth_bars)),
    }
    cost = CostContract()
    summaries: list[dict[str, Any]] = []
    outcome_tables: dict[str, pd.DataFrame] = {}
    for variant in variants():
        outcomes = [simulate(candidate, bars[candidate.symbol], variant, cost) for candidate in candidates]
        rows = []
        for outcome in outcomes:
            candidate = by_id[outcome.row_id]
            rows.append({
                **asdict(outcome),
                'event_start': candidate.event_start,
                'symbol': candidate.symbol,
                'family': candidate.family,
            })
        table = pd.DataFrame(rows)
        outcome_tables[variant.identifier] = table
        record: dict[str, Any] = {'variant': variant.identifier, **asdict(variant)}
        for half in ('H1', 'H2'):
            record[half] = {
                'independent': independent_metrics(table, half),
                'account': sequential_account(table, half),
            }
        summaries.append(record)
    # Selection is H1-only. Tie-breaks prefer fewer moving pieces.
    def h1_key(row: dict[str, Any]) -> tuple[float, float, int, str]:
        account = row['H1']['account']
        independent = row['H1']['independent']
        complexity = sum(bool(row.get(name)) for name in ('target_cap_r', 'partial_r', 'break_even_after_partial', 'pd_array_failure_exit'))
        return (
            float(account['geometric_daily_growth']),
            float(independent['mean_budget_r'] or -999.0),
            -complexity,
            row['variant'],
        )
    selected = max(summaries, key=h1_key)
    selected_id = selected['variant']
    selected['selection_authority'] = '2023H1_ONLY'
    selected['frozen_2023H2_validation'] = selected['H2']
    ranked = sorted(summaries, key=h1_key, reverse=True)
    payload = {
        'schema_version': 1,
        'stage': 'PRE2024_EXIT_GEOMETRY_H1_DISCOVERY_H2_VALIDATION_NOT_RANKABLE',
        'candidate_count': len(candidates),
        'variant_count': len(summaries),
        'selected': selected,
        'top10_h1': ranked[:10],
        'decision': (
            'ADVANCE_EXIT_CONTRACT_TO_INTEGRATED_ML_SCREEN'
            if selected['H2']['account']['geometric_daily_growth'] > 0
            else 'KEEP_SMC_NARRATIVE_REFINE_DELIVERY_OR_EXIT_GEOMETRY'
        ),
        'ranking_effect': 'NONE_PRE2024_NOT_RANKABLE',
    }
    (args.output / 'EXIT_GEOMETRY_RESULT.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n')
    pd.DataFrame([{
        'variant': row['variant'],
        'H1_mean_budget_r': row['H1']['independent']['mean_budget_r'],
        'H1_growth': row['H1']['account']['geometric_daily_growth'],
        'H1_multiple': row['H1']['account']['account_multiple'],
        'H1_trades': row['H1']['account']['completed_trades'],
        'H2_mean_budget_r': row['H2']['independent']['mean_budget_r'],
        'H2_growth': row['H2']['account']['geometric_daily_growth'],
        'H2_multiple': row['H2']['account']['account_multiple'],
        'H2_trades': row['H2']['account']['completed_trades'],
    } for row in ranked]).to_csv(args.output / 'EXIT_GEOMETRY_TABLE.csv', index=False)
    outcome_tables[selected_id].to_csv(args.output / 'SELECTED_OUTCOMES.csv.gz', index=False, compression='gzip')
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
