from __future__ import annotations

import numpy as np
import pandas as pd

from run_causal_action_fast import _label, _prepare
from run_causal_action_v1 import ScreenConfig
from system.core import EventCandidate, EventFamily


def test_unfilled_limit_cancels_when_confirmed_market_state_arrives() -> None:
    candidate = EventCandidate(
        timestamp=pd.Timestamp("2023-01-01T00:05:00Z"),
        symbol="BTCUSDT",
        family=EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        side=1,
        decision_price=102.0,
        entry_reference=100.0,
        stop_reference=98.0,
        target_reference=108.0,
        structural_level=99.0,
        feature_row={
            "action_candidate_early_passive": 1.0,
            "action_candidate_confirmed_market": 0.0,
            "atr": 2.0,
        },
    )
    starts = pd.date_range("2023-01-01T00:05:00Z", periods=20, freq="1min")
    available = starts + pd.Timedelta(minutes=1)
    frame = pd.DataFrame(
        {
            "bar_start": starts,
            "available_at": available,
            "open": np.full(20, 102.0),
            "high": np.full(20, 103.0),
            "low": np.full(20, 101.0),
            "close": np.full(20, 102.0),
        },
        index=available,
    )
    label = _label(
        candidate,
        "EARLY_PASSIVE",
        "FULL_STRUCTURAL",
        _prepare(frame),
        {},
        pd.Timestamp("2023-01-02T00:00:00Z"),
        ScreenConfig(),
        pd.Timestamp("2023-01-01T00:10:00Z"),
    )
    assert label is not None
    assert label.filled == 0
    assert label.status == "CANCELLED_ON_CONFIRMED_TRANSITION"
    assert label.event_end == pd.Timestamp("2023-01-01T00:12:00Z")
    assert label.net_pnl_per_unit == 0.0
