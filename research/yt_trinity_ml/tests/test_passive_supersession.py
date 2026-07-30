from __future__ import annotations

import pandas as pd

from system.core import EventCandidate, EventFamily
from run_causal_action_fast import _rows_fast
from run_causal_action_v1 import ScreenConfig


def _candidate(timestamp: str, side: int, stop: float, decision: float) -> EventCandidate:
    return EventCandidate(
        timestamp=pd.Timestamp(timestamp),
        symbol="BTCUSDT",
        family=EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        side=side,
        decision_price=decision,
        entry_reference=100.0 if side > 0 else 104.0,
        stop_reference=stop,
        target_reference=110.0 if side > 0 else 90.0,
        structural_level=99.0 if side > 0 else 105.0,
        feature_row={
            "action_candidate_early_passive": 1.0,
            "action_candidate_confirmed_market": 0.0,
            "atr": 2.0,
            "zone_width_atr": 1.0,
        },
    )


def _bars() -> pd.DataFrame:
    starts = pd.date_range("2023-01-01T00:00:00Z", periods=30, freq="1min")
    available = starts + pd.Timedelta(minutes=1)
    return pd.DataFrame(
        {
            "bar_start": starts,
            "available_at": available,
            "open": 103.0,
            "high": 104.0,
            "low": 102.0,
            "close": 103.0,
        },
        index=available,
    )


def test_deeper_same_draw_raid_cancels_older_unfilled_limit() -> None:
    older = _candidate("2023-01-01T00:05:00Z", 1, 98.0, 102.0)
    deeper = _candidate("2023-01-01T00:10:00Z", 1, 96.0, 101.0)
    rows = _rows_fast(
        [older, deeper],
        {"BTCUSDT": _bars()},
        {},
        pd.Timestamp("2023-01-02T00:00:00Z"),
        ("FULL_STRUCTURAL",),
        ScreenConfig(),
    )
    first = rows.sort_values("activation").iloc[0]
    assert first["filled"] == 0
    assert first["status"] == "CANCELLED_ON_CONFIRMED_TRANSITION"
    assert pd.Timestamp(first["event_end"]) == pd.Timestamp("2023-01-01T00:12:00Z")


def test_opposing_armed_delivery_below_long_entry_cancels_long_limit() -> None:
    long = _candidate("2023-01-01T00:05:00Z", 1, 98.0, 102.0)
    short = _candidate("2023-01-01T00:12:00Z", -1, 106.0, 99.0)
    rows = _rows_fast(
        [long, short],
        {"BTCUSDT": _bars()},
        {},
        pd.Timestamp("2023-01-02T00:00:00Z"),
        ("FULL_STRUCTURAL",),
        ScreenConfig(),
    )
    first = rows.sort_values("activation").iloc[0]
    assert first["filled"] == 0
    assert first["status"] == "CANCELLED_ON_CONFIRMED_TRANSITION"
