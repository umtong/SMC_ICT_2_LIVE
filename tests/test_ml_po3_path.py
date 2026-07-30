from __future__ import annotations

import numpy as np
import pandas as pd

from research.ml_po3_path.policy_core import (
    ExecutionContract,
    detect_accepted_distribution_events,
    simulate_limit_lifecycle,
)


def _bar_frame() -> pd.DataFrame:
    rows = []
    for i in range(54):
        rows.append({
            "start_time_ms": i * 300_000,
            "available_at_ms": (i + 1) * 300_000,
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.0,
            "volume": 1.0,
            "is_complete": True,
        })
    frame = pd.DataFrame(rows)
    # First outside close, then an inside close: acceptance must reset.
    frame.loc[48, ["open", "high", "low", "close"]] = [100.4, 101.5, 100.2, 101.2]
    frame.loc[49, ["open", "high", "low", "close"]] = [101.1, 101.2, 100.0, 100.4]
    # Two genuinely consecutive closes outside the frozen range.
    frame.loc[50, ["open", "high", "low", "close"]] = [100.5, 101.4, 100.4, 101.1]
    frame.loc[51, ["open", "high", "low", "close"]] = [101.1, 101.8, 101.0, 101.6]
    return frame


def test_acceptance_requires_consecutive_outside_closes() -> None:
    events = detect_accepted_distribution_events(_bar_frame(), symbol="BTCUSDT")
    assert len(events) == 1
    assert int(events.iloc[0].trigger_start_ms) == 51 * 300_000
    assert int(events.iloc[0].outside_n) == 2
    assert int(events.iloc[0].direction) == 1


def test_same_minute_stop_and_target_is_adverse_first() -> None:
    event = pd.Series({
        "decision_time_ms": 0,
        "period_start_ms": 0,
        "direction": 1,
        "limit_price": 100.0,
        "stop": 99.0,
        "target": 102.0,
    })
    minute = pd.DataFrame([
        {"start_time_ms": 60_000, "observed": True, "open": 100.0, "high": 100.1, "low": 99.98, "close": 100.0},
        {"start_time_ms": 120_000, "observed": True, "open": 100.0, "high": 102.1, "low": 98.9, "close": 101.0},
    ])
    funding = pd.DataFrame({"timestamp_ms": np.array([], dtype=np.int64), "funding_rate": np.array([], dtype=float)})
    result = simulate_limit_lifecycle(event, minute, funding, ExecutionContract())
    assert result["status"] == "stop"
    assert result["account_return"] < 0


def test_pending_expiry_does_not_create_a_trade() -> None:
    event = pd.Series({
        "decision_time_ms": 0,
        "period_start_ms": 0,
        "direction": 1,
        "limit_price": 90.0,
        "stop": 80.0,
        "target": 120.0,
    })
    minute = pd.DataFrame([
        {"start_time_ms": 60_000, "observed": True, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"start_time_ms": 86_460_000, "observed": True, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
    ])
    funding = pd.DataFrame({"timestamp_ms": np.array([], dtype=np.int64), "funding_rate": np.array([], dtype=float)})
    result = simulate_limit_lifecycle(event, minute, funding, ExecutionContract())
    assert result["status"] == "pending_expired"
    assert result["account_return"] == 0.0
