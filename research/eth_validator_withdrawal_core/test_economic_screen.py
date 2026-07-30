from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

MODULE_PATH = Path(__file__).with_name("economic_screen.py")
SPEC = importlib.util.spec_from_file_location("economic_screen", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["economic_screen"] = MODULE
SPEC.loader.exec_module(MODULE)


def synthetic_actions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_key": "a",
                "entry_ms": 1000,
                "exit_ms": 3000,
                "score": 0.2,
                "baseline_score": 0.1,
                "direction": 1,
                "event_ret": 0.01,
                "reason": "target",
                "account_return_13": 0.01,
                "account_return_18": 0.009,
                "account_return_24": 0.008,
            },
            {
                "event_key": "a",
                "entry_ms": 1000,
                "exit_ms": 2000,
                "score": 0.1,
                "baseline_score": 0.2,
                "direction": -1,
                "event_ret": 0.01,
                "reason": "stop",
                "account_return_13": -0.005,
                "account_return_18": -0.005,
                "account_return_24": -0.005,
            },
            {
                "event_key": "b",
                "entry_ms": 2500,
                "exit_ms": 4000,
                "score": 0.3,
                "baseline_score": 0.3,
                "direction": 1,
                "event_ret": -0.01,
                "reason": "target",
                "account_return_13": 0.01,
                "account_return_18": 0.009,
                "account_return_24": 0.008,
            },
            {
                "event_key": "c",
                "entry_ms": 4001,
                "exit_ms": 5000,
                "score": 0.4,
                "baseline_score": 0.4,
                "direction": -1,
                "event_ret": -0.01,
                "reason": "target",
                "account_return_13": 0.01,
                "account_return_18": 0.009,
                "account_return_24": 0.008,
            },
        ]
    )


def test_route_selects_one_action_and_enforces_global_slot() -> None:
    trades, nav = MODULE.route(synthetic_actions(), "score", 24)
    assert list(trades["event_key"]) == ["a", "c"]
    assert nav > 10_000


def test_response_policy_maps_price_response_to_absorption_or_acceptance() -> None:
    trades, _ = MODULE.route_response(synthetic_actions(), 24)
    assert list(trades["event_key"]) == ["a", "c"]
    assert list(trades["direction"]) == [1, -1]


def test_excluded_winner_event_is_removed_before_slot_rerouting() -> None:
    trades, _ = MODULE.route(synthetic_actions(), "score", 24, exclude={"a"})
    assert list(trades["event_key"]) == ["b", "c"]


def test_summary_reports_tail_concentration() -> None:
    trades, nav = MODULE.route(synthetic_actions(), "score", 24)
    summary = MODULE.summarize(trades, nav)
    assert summary["trades"] == 2
    assert 0 < summary["top5_positive_pnl_share"] <= 1


def test_fixed_contract_has_no_elapsed_time_exit() -> None:
    assert MODULE.RISK == 0.005
    assert MODULE.CAP == 3.0
    assert MODULE.COSTS == (13, 18, 24)
