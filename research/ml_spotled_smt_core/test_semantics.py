from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("spotled", HERE / "run.py")
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
import sys
sys.modules["spotled"] = m
SPEC.loader.exec_module(m)


def test_pivot_is_available_only_after_two_right_bars() -> None:
    bars = pd.DataFrame(
        {
            "bar_start_s": [0, 15, 30, 45, 60],
            "high": [1, 2, 5, 3, 2],
            "low": [0, 0, 0, 0, 0],
        }
    )
    pivots = m.raw_pivots(bars, 15, span=2)
    high = [p for p in pivots if p.kind == "high"][0]
    assert high.pivot_start_s == 30
    assert high.confirmed_s == 75


def test_cross_provider_and_order_latency_are_both_applied() -> None:
    event_sec = 100
    event_end = (event_sec + 1) * 1_000_000
    feature_decision = event_end + m.CROSS_PROVIDER_DELAY_US
    activation = feature_decision + m.ORDER_LATENCY_US
    assert feature_decision == 103_000_000
    assert activation == 103_500_000


def test_same_state_stop_precedes_target() -> None:
    bybit = pd.DataFrame(
        {
            "decision_us": [0, 1_000_000, 2_000_000],
            "ask": [100.1, 100.1, 100.1],
            "bid": [100.0, 100.0, 100.0],
        }
    )
    e = pd.Series(
        {
            "event_key": "e",
            "activation_us": 0,
            "direction": 1,
            "target_price": 99.5,
            "stop_price": 100.5,
        }
    )
    assert m.simulate_action(e, bybit, 24.0) is None


def test_exit_bucket_blocks_equal_timestamp_reentry() -> None:
    events = pd.DataFrame(
        [
            {
                "event_key": "a",
                "activation_us": 100,
                "c24_account_return": 0.01,
                "c24_exit_us": 200,
                "c24_entry_us": 100,
                "direction": 1,
                "c24_exit_reason": "target",
                "c24_completed": True,
                "c24_gross_return": 0.02,
                "c24_net_return": 0.0176,
                "c24_position_fraction": 0.5,
            },
            {
                "event_key": "b",
                "activation_us": 200,
                "c24_account_return": 0.01,
                "c24_exit_us": 300,
                "c24_entry_us": 200,
                "direction": 1,
                "c24_exit_reason": "target",
                "c24_completed": True,
                "c24_gross_return": 0.02,
                "c24_net_return": 0.0176,
                "c24_position_fraction": 0.5,
            },
            {
                "event_key": "c",
                "activation_us": 201,
                "c24_account_return": 0.01,
                "c24_exit_us": 300,
                "c24_entry_us": 201,
                "direction": 1,
                "c24_exit_reason": "target",
                "c24_completed": True,
                "c24_gross_return": 0.02,
                "c24_net_return": 0.0176,
                "c24_position_fraction": 0.5,
            },
        ]
    )
    metrics, ledger = m.route_account(events, 24.0)
    assert ledger["event_key"].tolist() == ["a", "c"]
    assert metrics["trades"] == 2


def test_source_local_timestamp_is_not_in_feature_contract() -> None:
    assert all("local_timestamp" not in f for f in m.FEATURES)
