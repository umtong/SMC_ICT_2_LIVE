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
                "event_key": "principal:a",
                "entry_ms": 1000,
                "exit_ms": 3000,
                "score": 0.2,
                "baseline_score": 0.1,
                "direction": 1,
                "event_ret": 0.01,
                "reason": "target",
                "resolved": True,
                "account_return_13": 0.01,
                "account_return_18": 0.009,
                "account_return_24": 0.008,
            },
            {
                "event_key": "principal:a",
                "entry_ms": 1000,
                "exit_ms": 2000,
                "score": 0.1,
                "baseline_score": 0.2,
                "direction": -1,
                "event_ret": 0.01,
                "reason": "stop",
                "resolved": True,
                "account_return_13": -0.005,
                "account_return_18": -0.005,
                "account_return_24": -0.005,
            },
            {
                "event_key": "principal:b",
                "entry_ms": 2500,
                "exit_ms": 4000,
                "score": 0.3,
                "baseline_score": 0.3,
                "direction": 1,
                "event_ret": -0.01,
                "reason": "target",
                "resolved": True,
                "account_return_13": 0.01,
                "account_return_18": 0.009,
                "account_return_24": 0.008,
            },
            {
                "event_key": "principal:c",
                "entry_ms": 4001,
                "exit_ms": 5000,
                "score": 0.4,
                "baseline_score": 0.4,
                "direction": -1,
                "event_ret": -0.01,
                "reason": "boundary_mark",
                "resolved": False,
                "account_return_13": 0.01,
                "account_return_18": 0.009,
                "account_return_24": 0.008,
            },
        ]
    )


def test_stage_boundaries_are_fixed() -> None:
    assert MODULE.stage_end(pd.Timestamp("2023-08-31T12:00:00Z")) == MODULE.FIT_END
    assert MODULE.stage_end(pd.Timestamp("2023-09-01T00:00:00Z")) == MODULE.DEVELOP_END
    assert MODULE.stage_end(pd.Timestamp("2023-11-01T00:00:00Z")) == MODULE.END


def test_route_selects_one_action_and_enforces_slot() -> None:
    trades, nav = MODULE.route(synthetic_actions(), "score", 24)
    assert list(trades["event_key"]) == ["principal:a", "principal:c"]
    assert nav > 10_000


def test_response_policy_maps_observed_response() -> None:
    trades, _ = MODULE.route_response(synthetic_actions(), 24)
    assert list(trades["event_key"]) == ["principal:a", "principal:c"]
    assert list(trades["direction"]) == [1, -1]


def test_winner_exclusion_happens_before_rerouting() -> None:
    trades, _ = MODULE.route(
        synthetic_actions(), "score", 24, exclude={"principal:a"}
    )
    assert list(trades["event_key"]) == ["principal:b", "principal:c"]


def test_summary_separates_boundary_marks() -> None:
    trades, nav = MODULE.route(synthetic_actions(), "score", 24)
    summary = MODULE.summarize(trades, nav)
    assert summary["trades"] == 2
    assert summary["boundary_marks"] == 1


def test_pass_rule_requires_breadth_nav_winner_resistance_and_control_superiority() -> None:
    good = {
        "principal": {
            stage: {
                "ml_policy": {"24": {"trades": 20, "end_nav": 10_100.0}},
                "ml_24bp_winner_deleted": {"end_nav": 10_020.0},
            }
            for stage in ("development", "confirmation")
        },
        "partial": {
            stage: {"ml_policy": {"24": {"trades": 20, "end_nav": 9_900.0}}}
            for stage in ("development", "confirmation")
        },
    }
    passed, reasons = MODULE.pass_rule(good)
    assert passed and reasons == []
    good["principal"]["confirmation"]["ml_24bp_winner_deleted"]["end_nav"] = 9_999.0
    passed, reasons = MODULE.pass_rule(good)
    assert not passed and any("winner-deleted" in reason for reason in reasons)


def test_fixed_account_contract() -> None:
    assert MODULE.RISK == 0.005
    assert MODULE.CAP == 3.0
    assert MODULE.COSTS == (13, 18, 24)
