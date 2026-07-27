from __future__ import annotations
import numpy as np
import pandas as pd
from run_causal_action_fast import _label, _prepare
from run_causal_action_v1 import ScreenConfig
from system.core import EventCandidate, EventFamily

def candidate() -> EventCandidate:
    return EventCandidate(
        pd.Timestamp('2023-01-01T00:00:00Z'), 'BTCUSDT',
        EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 102.0, 100.0,
        95.0, 110.0, 96.0,
        {'action_candidate_early_passive': 1.0,
         'action_candidate_confirmed_market': 0.0,
         'atr': 2.0, 'zone_width_atr': 2.0,
         'zone_midpoint_distance_atr': 0.0,
         'passive_depth_fraction': 0.5},
    )

def bars(stop_on_failure: bool = False) -> pd.DataFrame:
    starts = pd.date_range('2023-01-01T00:00:00Z', periods=6, freq='1min')
    available = starts + pd.Timedelta(minutes=1)
    low = np.asarray([101.0, 99.0, 96.5, 96.0, 96.5, 97.0])
    if stop_on_failure:
        low[2] = 94.0
    return pd.DataFrame({
        'bar_start': starts, 'available_at': available,
        'open': [102.0, 101.0, 99.0, 96.5, 96.8, 97.0],
        'high': [103.0, 102.0, 100.0, 98.0, 98.5, 99.0],
        'low': low,
        'close': [102.0, 100.0, 97.0, 96.8, 97.5, 98.0],
    }, index=available)

def test_close_confirmed_pd_array_failure_exits_next_observable_open() -> None:
    label = _label(candidate(), 'EARLY_PASSIVE', 'PD_ARRAY_FAILURE',
                   _prepare(bars()), {}, pd.Timestamp('2023-01-02T00:00:00Z'),
                   ScreenConfig())
    assert label is not None and label.filled == 1
    assert label.status == 'PD_ARRAY_CLOSE_FAILURE'
    assert label.event_end == pd.Timestamp('2023-01-01T00:04:00Z')
    assert label.net_pnl_per_unit < 0

def test_structural_stop_wins_on_failure_confirmation_bar() -> None:
    label = _label(candidate(), 'EARLY_PASSIVE', 'PD_ARRAY_FAILURE',
                   _prepare(bars(True)), {}, pd.Timestamp('2023-01-02T00:00:00Z'),
                   ScreenConfig())
    assert label is not None and label.filled == 1
    assert label.status == 'STOP'
