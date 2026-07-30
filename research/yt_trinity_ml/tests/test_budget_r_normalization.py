from __future__ import annotations

import numpy as np
import pandas as pd

from system.coarse import CoarseExecutionConfig
from system.core import EventCandidate, EventFamily
from system.model import ChronologicalEventModel
from system.research_pipeline import estimated_action_loss_budget


def candidate() -> EventCandidate:
    return EventCandidate(
        pd.Timestamp('2023-01-01T00:00:00Z'), 'BTCUSDT',
        EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1,
        100.0, 100.0, 99.0, 103.0, 99.5, {},
    )


def test_budget_exceeds_raw_stop_and_market_exceeds_passive() -> None:
    c = candidate()
    cfg = CoarseExecutionConfig()
    market = estimated_action_loss_budget(c, 'MARKETABLE', cfg)
    passive = estimated_action_loss_budget(c, 'PASSIVE_RETEST', cfg)
    assert market > passive > c.stop_distance


def test_budget_r_is_account_risk_unit() -> None:
    c = candidate()
    cfg = CoarseExecutionConfig()
    budget = estimated_action_loss_budget(c, 'MARKETABLE', cfg)
    raw_stop_r = -budget / c.stop_distance
    normalized = raw_stop_r * c.stop_distance / budget
    assert np.isclose(normalized, -1.0)


def test_model_prefers_budget_r_columns() -> None:
    rows = pd.DataFrame({
        'event_start': pd.date_range('2023-01-01', periods=2, tz='UTC'),
        'event_end': pd.date_range('2023-01-02', periods=2, tz='UTC'),
        'passive_filled': [1, 1],
        'market_target_before_stop': [0, 1],
        'market_net_r': [-1.7, 2.0],
        'market_budget_r': [-1.0, 1.1],
        'passive_target_before_stop': [0, 1],
        'passive_net_r': [-1.4, 1.8],
        'passive_budget_r': [-1.0, 1.0],
    })
    normalized = ChronologicalEventModel._with_action_labels(rows)
    assert normalized['market_net_r'].tolist() == [-1.0, 1.1]
    assert normalized['passive_net_r'].tolist() == [-1.0, 1.0]
