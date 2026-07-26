from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def audit_latency(root: Path, latency_ms: int) -> dict:
    result = json.loads((root / 'RESULT.json').read_text())
    assert result['claim_id'] == 'CLM-20260726-2115-ML-XVENUE-PRESHOCK-MAKER-001'
    assert result['official_2024_2026_opened'] is False
    assert result['orders_submitted'] is False
    expected_delta = 1 + latency_ms // 100
    checks = ['authority and sealed-period flags']
    for stage, date in result['dates'].items():
        assert date < '2024-01-01'
        events = pd.read_csv(root / f'events_{stage}.csv')
        if len(events):
            assert (events['placement_bin'] - events['signal_bin'] == expected_delta).all()
            assert set(events['side'].unique()).issubset({-1, 1})
            assert not events['exit_reason'].astype(str).str.contains('time|timeout', case=False, regex=True).any()
            placed = events[events['placed'].eq(1)]
            if len(placed):
                assert (placed['order_qty'] > 0).all()
                assert (placed['target_bps'] > 0).all()
                assert (placed['stop_bps'] > 0).all()
                filled = placed[placed['filled'].eq(1)]
                if len(filled):
                    assert (filled['fill_bin'] >= filled['placement_bin']).all()
                    assert (filled['exit_bin'] >= filled['fill_bin']).all()
    checks.append('completed-state latency, both-side structural geometry, and no timeout')

    scored_path = root / 'scored_confirmation.csv'
    if scored_path.exists():
        pd.read_csv(scored_path)
        for cost in (12, 18, 24):
            trade_path = root / f'trades_{cost}bp.csv'
            removed_path = root / f'trades_{cost}bp_winner_removed.csv'
            if not trade_path.exists():
                continue
            trades = pd.read_csv(trade_path)
            metrics = result['economic'][str(cost)]
            assert len(trades) == metrics['trade_count']
            if len(trades):
                compounded = float(np.prod(1.0 + trades['account_return'].to_numpy()) - 1.0)
                assert math.isclose(compounded, metrics['total_return'], rel_tol=0, abs_tol=2e-12)
                assert float(trades['leverage'].max()) <= 3.0 + 1e-12
                ordered = trades.sort_values('placement_bin')
                if len(ordered) > 1:
                    assert (ordered['placement_bin'].iloc[1:].to_numpy() > ordered['exit_bin'].iloc[:-1].to_numpy()).all()
            removed = pd.read_csv(removed_path)
            excluded = set(metrics['top10_positive_event_keys_removed'])
            if len(removed):
                assert not set(removed['event_key']).intersection(excluded)
        checks.append('account compounding, placement-time one-slot chronology, leverage, and winner rerouting')
    return {
        'latency_ms': latency_ms,
        'status': 'PASS',
        'result_sha256': sha256(root / 'RESULT.json'),
        'checks': checks,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--latency100', required=True)
    p.add_argument('--latency300', required=True)
    p.add_argument('--combined', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    combined = json.loads(Path(args.combined).read_text())
    assert combined['official_2024_2026_opened'] is False
    assert combined['orders_submitted'] is False
    payload = {
        'claim_id': combined['claim_id'],
        'result_id': combined['result_id'],
        'status': 'PASS',
        'latencies': [
            audit_latency(Path(args.latency100), 100),
            audit_latency(Path(args.latency300), 300),
        ],
        'combined_result_sha256': sha256(Path(args.combined)),
        'official_2024_2026_opened': False,
        'orders_submitted': False,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
