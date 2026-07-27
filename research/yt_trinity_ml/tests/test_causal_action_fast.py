from __future__ import annotations

import numpy as np
import pandas as pd

from system.core import EventCandidate, EventFamily
from run_causal_action_fast import _label, _prepare
from run_causal_action_v1 import ScreenConfig


def _candidate() -> EventCandidate:
    return EventCandidate(
        timestamp=pd.Timestamp("2023-01-01T00:15:00Z"),
        symbol="BTCUSDT",
        family=EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        side=1,
        decision_price=102.0,
        entry_reference=102.0,
        stop_reference=98.0,
        target_reference=108.0,
        structural_level=99.0,
        feature_row={
            "atr": 2.0,
            "zone_midpoint_distance_atr": 1.0,
            "confirmation_age_bars": 2.0,
            "liquidity_quality": 6.0,
            "draw_target_quality": 6.0,
        },
    )


def _bars(low_at_fill: float = 99.9, simultaneous_stop: bool = False) -> pd.DataFrame:
    starts = pd.date_range("2023-01-01T00:05:00Z", periods=20, freq="1min")
    available = starts + pd.Timedelta(minutes=1)
    low = [101.0, 100.5, low_at_fill, 100.5, 101.0, 102.0, 103.0, 104.0] + [101.0] * 12
    high = [102.0, 101.5, 101.0, 102.0, 103.0, 105.0, 108.5, 109.0] + [109.0] * 12
    if simultaneous_stop:
        low[2] = 97.5
        high[2] = 101.0
    return pd.DataFrame(
        {
            "bar_start": starts,
            "available_at": available,
            "open": [101.5] * 20,
            "high": high,
            "low": low,
            "close": [101.5, 101.0, 100.0, 101.5, 102.5, 104.5, 108.0, 108.5] + [108.5] * 12,
        },
        index=available,
    )


def test_early_passive_activates_at_displacement_not_later_confirmation() -> None:
    candidate = _candidate()
    label = _label(
        candidate,
        "EARLY_PASSIVE",
        "FULL_STRUCTURAL",
        _prepare(_bars()),
        {},
        pd.Timestamp("2023-01-02T00:00:00Z"),
        ScreenConfig(),
    )
    assert label is not None
    assert label.activation == pd.Timestamp("2023-01-01T00:05:00.500Z")
    assert label.entry_price == 100.0
    assert label.filled == 1
    assert label.status == "STRUCTURAL_TARGET"
    assert label.net_pnl_per_unit > 0


def test_passive_requires_trade_through_not_mere_touch() -> None:
    candidate = _candidate()
    frame = _bars(low_at_fill=100.0)
    frame.loc[:, "low"] = np.maximum(frame["low"].to_numpy(), 100.0)
    label = _label(
        candidate,
        "EARLY_PASSIVE",
        "FULL_STRUCTURAL",
        _prepare(frame),
        {},
        pd.Timestamp("2023-01-02T00:00:00Z"),
        ScreenConfig(),
    )
    assert label is not None
    assert label.filled == 0
    assert label.net_pnl_per_unit == 0.0


def test_invalidation_on_fill_bar_cancels_passive_order() -> None:
    candidate = _candidate()
    label = _label(
        candidate,
        "EARLY_PASSIVE",
        "FULL_STRUCTURAL",
        _prepare(_bars(simultaneous_stop=True)),
        {},
        pd.Timestamp("2023-01-02T00:00:00Z"),
        ScreenConfig(),
    )
    assert label is not None
    assert label.filled == 0
    assert label.status == "CANCELLED_OR_UNFILLED"


def test_market_action_cannot_use_early_passive_entry_price() -> None:
    candidate = _candidate()
    label = _label(
        candidate,
        "CONFIRMED_MARKET",
        "CAP_2R",
        _prepare(_bars()),
        {},
        pd.Timestamp("2023-01-02T00:00:00Z"),
        ScreenConfig(),
    )
    assert label is not None
    assert label.activation == pd.Timestamp("2023-01-01T00:15:00.500Z")
    assert label.entry_price != 100.0
