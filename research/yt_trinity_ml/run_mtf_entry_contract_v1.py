#!/usr/bin/env python3
"""Compare five-minute retest entries with one-minute CISD refinement.

The 5m completed-bar narrative freezes PD array, stop and external draw. After
500ms activation, the 1m engine waits for mitigation and a completed delivery-open
CISD. H1 chooses the reference/session/entry contract; H2 validates unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from math import exp, log
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from run_research import PRIMARY, load_canonical_frames
from system.coarse import CoarseExecutionConfig
from system.core import EventCandidate, FeatureConfig
from system.corpus_alpha import (
    CorpusAlphaConfig,
    NarrativeSetup,
    build_corpus_features,
    generate_corpus_candidates_with_diagnostics,
    generate_corpus_setups_with_diagnostics,
)
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
        'maximum_drawdown': mdd, 'mean_budget_r': sum(values) / len(values) if values else None,
        'available_candidates': len(rows),
    }


def prepare_one_minute(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy().sort_index()
    out['open'] = pd.to_numeric(out['open'], errors='coerce')
    out['high'] = pd.to_numeric(out['high'], errors='coerce')
    out['low'] = pd.to_numeric(out['low'], errors='coerce')
    out['close'] = pd.to_numeric(out['close'], errors='coerce')
    prior_close = out['close'].shift(1)
    true_range = pd.concat(
        [out['high'] - out['low'], (out['high'] - prior_close).abs(), (out['low'] - prior_close).abs()], axis=1
    ).max(axis=1)
    out['ltf_atr'] = true_range.shift(1).rolling(20, min_periods=10).mean()
    out['ltf_range'] = out['high'] - out['low']
    out['ltf_body'] = out['close'] - out['open']
    out['ltf_close_location'] = (out['close'] - out['low']) / out['ltf_range'].replace(0, np.nan)
    return out


def refine_setup(setup: NarrativeSetup, frame: pd.DataFrame, latency_ms: int = 500) -> EventCandidate | None:
    activation = setup.timestamp + pd.Timedelta(milliseconds=latency_ms)
    rows = frame.loc[frame.index >= activation]
    if rows.empty:
        return None
    touched = False
    first_touch_time: pd.Timestamp | None = None
    trigger = (setup.zone_lower + setup.zone_upper) / 2.0
    mitigation_extreme = np.inf if setup.side > 0 else -np.inf
    mitigation_bars = 0
    for timestamp, row in rows.iterrows():
        # No order exists yet. Reaching target or structural stop consumes the setup.
        if setup.side > 0:
            if float(row['high']) >= setup.target_reference or float(row['low']) <= setup.stop_reference:
                return None
        else:
            if float(row['low']) <= setup.target_reference or float(row['high']) >= setup.stop_reference:
                return None
        zone_touch = float(row['low']) <= setup.zone_upper and float(row['high']) >= setup.zone_lower
        if zone_touch:
            if not touched:
                touched = True
                first_touch_time = pd.Timestamp(timestamp)
            mitigation_bars += 1
            if setup.side > 0:
                mitigation_extreme = min(mitigation_extreme, float(row['low']))
                if float(row['close']) < float(row['open']):
                    trigger = float(row['open'])
            else:
                mitigation_extreme = max(mitigation_extreme, float(row['high']))
                if float(row['close']) > float(row['open']):
                    trigger = float(row['open'])
        if not touched or not np.isfinite(float(row.get('ltf_atr', np.nan))):
            continue
        body = float(row['ltf_body'])
        range_value = max(float(row['ltf_range']), 1e-12)
        efficiency = abs(body) / range_value
        location = float(row['ltf_close_location'])
        if setup.side > 0:
            confirmed = float(row['close']) > trigger and body > 0 and efficiency >= 0.45 and location >= 0.60
        else:
            confirmed = float(row['close']) < trigger and body < 0 and efficiency >= 0.45 and location <= 0.40
        if not confirmed:
            continue
        entry = float(row['close'])
        if (setup.side > 0 and not setup.stop_reference < entry < setup.target_reference) or (
            setup.side < 0 and not setup.target_reference < entry < setup.stop_reference
        ):
            return None
        atr = float(row['ltf_atr'])
        features = dict(setup.feature_row)
        features.update({
            'entry_timeframe_1m': 1.0,
            'ltf_cisd_body_atr': body / atr,
            'ltf_cisd_range_atr': range_value / atr,
            'ltf_cisd_efficiency': efficiency,
            'ltf_cisd_close_location': location,
            'ltf_mitigation_bars': float(mitigation_bars),
            'ltf_wait_minutes': float((pd.Timestamp(timestamp) - setup.timestamp) / pd.Timedelta(minutes=1)),
            'ltf_retest_depth_atr': (
                abs(float(mitigation_extreme) - (setup.zone_lower + setup.zone_upper) / 2.0) / atr
            ),
            'stop_distance_atr': abs(entry - setup.stop_reference) / atr,
            'target_distance_atr': abs(setup.target_reference - entry) / atr,
            'raw_structural_reward_risk': abs(setup.target_reference - entry) / max(abs(entry - setup.stop_reference), 1e-12),
            'execution_pd_array_midpoint_reference': (setup.zone_lower + setup.zone_upper) / 2.0,
        })
        return EventCandidate(
            timestamp=pd.Timestamp(timestamp), symbol=setup.symbol, family=setup.family, side=setup.side,
            decision_price=entry, entry_reference=entry,
            stop_reference=setup.stop_reference, target_reference=setup.target_reference,
            structural_level=setup.structural_level, feature_row=features,
        )
    return None


def base_config(session: bool, smt: str) -> CorpusAlphaConfig:
    return CorpusAlphaConfig(
        continuation_requires_liquidity_raid=True,
        continuation_minimum_htf_bias=2.0,
        continuation_requires_discount_premium=True,
        require_session_amd=session,
        smt_confirmation_mode=smt,
        order_block_range_mode='OPEN_TO_EXTREME',
        fvg_search_mode='IMPULSE_NEAREST',
        cisd_confirmation_mode='DELIVERY_OPEN',
    )


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    decision_frames, execution_frames, _ = load_canonical_frames(args.data_root, args.repo_root, PRIMARY, args.segments)
    one_minute = {symbol: prepare_one_minute(frame) for symbol, frame in execution_frames.items()}
    contracts = {
        'UTC_CONTINUOUS_SMT_FEATURE': ('UTC', base_config(False, 'FEATURE_ONLY')),
        'UTC_CONTINUOUS_SMT_REQUIRED': ('UTC', base_config(False, 'REQUIRE_SELF_RAID_DIVERGENCE')),
        'NY_CONTINUOUS_SMT_FEATURE': ('NEW_YORK', base_config(False, 'FEATURE_ONLY')),
        'NY_CONTINUOUS_SMT_REQUIRED': ('NEW_YORK', base_config(False, 'REQUIRE_SELF_RAID_DIVERGENCE')),
        'NY_SESSION_SMT_FEATURE': ('NEW_YORK', base_config(True, 'FEATURE_ONLY')),
        'NY_SESSION_SMT_REQUIRED': ('NEW_YORK', base_config(True, 'REQUIRE_SELF_RAID_DIVERGENCE')),
    }
    feature_cache: dict[str, dict[str, pd.DataFrame]] = {}
    for reference in ('UTC', 'NEW_YORK'):
        feature_cache[reference] = add_pair_smt_features({
            symbol: build_corpus_features(frame, FeatureConfig(), reference_time_mode=reference)
            for symbol, frame in sorted(decision_frames.items())
        })
    h1_start = pd.Timestamp('2023-01-01', tz='UTC')
    h1_end = pd.Timestamp('2023-07-01', tz='UTC')
    h2_end = pd.Timestamp('2024-01-01', tz='UTC')
    results: list[dict[str, Any]] = []
    for identifier, (reference, cfg) in contracts.items():
        five_minute_candidates = []
        one_minute_candidates = []
        diagnostics: dict[str, Any] = {}
        for symbol, features in sorted(feature_cache[reference].items()):
            candidates, candidate_diag = generate_corpus_candidates_with_diagnostics(features, symbol, cfg)
            setups, setup_diag = generate_corpus_setups_with_diagnostics(features, symbol, cfg)
            five_minute_candidates.extend(candidates)
            one_minute_candidates.extend(
                candidate for candidate in (refine_setup(setup, one_minute[symbol]) for setup in setups) if candidate is not None
            )
            diagnostics[symbol] = {'candidate': candidate_diag, 'setup': setup_diag, 'refined_entries': sum(1 for row in one_minute_candidates if row.symbol == symbol)}
        for entry_mode, candidates in (
            ('FIVE_MINUTE_RETEST', five_minute_candidates),
            ('ONE_MINUTE_CISD', one_minute_candidates),
        ):
            candidates.sort(key=lambda row: (row.timestamp, row.symbol, row.family.value, row.side))
            labels = label_event_dataset(candidates, execution_frames, CoarseExecutionConfig())
            labels['event_start'] = pd.to_datetime(labels['event_start'], utc=True)
            labels['event_end'] = pd.to_datetime(labels['event_end'], utc=True)
            key = f'{identifier}__{entry_mode}'
            labels.to_parquet(args.output / f'{key}_LABELS.parquet', index=False)
            results.append({
                'identifier': key,
                'candidate_contract': identifier,
                'entry_mode': entry_mode,
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
        'stage': 'PRE2024_MTF_ENTRY_H1_SELECTION_H2_VALIDATION_NOT_RANKABLE',
        'contracts': results,
        'selected_identifier': selected['identifier'],
        'selected_entry_mode': selected['entry_mode'],
        'selected_action': action,
        'selected_contract': selected['contract'],
        'H1_selection_metrics': h1,
        'H2_frozen_validation_metrics': h2,
        'decision': 'ADVANCE_MTF_ENTRY_CONTRACT' if h2['geometric_daily_growth'] > 0 else 'KEEP_SMC_PREMISE_REFINE_LTF_CONFIRMATION_OR_ORDER_ENTRY',
        'ranking_effect': 'NONE_PRE2024_NOT_RANKABLE',
    }
    (args.output / 'MTF_ENTRY_CONTRACT_RESULT.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n')
    pd.DataFrame([
        {
            'identifier': row['identifier'], 'candidates': row['candidate_count'],
            'H1_market_growth': row['H1']['market']['geometric_daily_growth'],
            'H1_passive_growth': row['H1']['passive']['geometric_daily_growth'],
            'H2_market_growth': row['H2']['market']['geometric_daily_growth'],
            'H2_passive_growth': row['H2']['passive']['geometric_daily_growth'],
        }
        for row in results
    ]).to_csv(args.output / 'MTF_ENTRY_CONTRACT_TABLE.csv', index=False)
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
