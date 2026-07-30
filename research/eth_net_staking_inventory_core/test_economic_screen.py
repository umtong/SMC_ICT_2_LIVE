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
            {"event_key":"net:a","entry_ms":1000,"exit_ms":3000,"score":0.2,"baseline_score":0.1,"direction":1,"event_ret":0.01,"source_sign":1,"reason":"target","resolved":True,"account_return_13":0.01,"account_return_18":0.009,"account_return_24":0.008},
            {"event_key":"net:a","entry_ms":1000,"exit_ms":2000,"score":0.1,"baseline_score":0.2,"direction":-1,"event_ret":0.01,"source_sign":1,"reason":"stop","resolved":True,"account_return_13":-0.005,"account_return_18":-0.005,"account_return_24":-0.005},
            {"event_key":"net:b","entry_ms":2500,"exit_ms":4000,"score":0.3,"baseline_score":0.3,"direction":1,"event_ret":-0.01,"source_sign":-1,"reason":"target","resolved":True,"account_return_13":0.01,"account_return_18":0.009,"account_return_24":0.008},
            {"event_key":"net:c","entry_ms":4001,"exit_ms":5000,"score":0.4,"baseline_score":0.4,"direction":-1,"event_ret":-0.01,"source_sign":-1,"reason":"boundary_mark","resolved":False,"account_return_13":0.01,"account_return_18":0.009,"account_return_24":0.008},
        ]
    )


def test_fixed_stage_boundaries() -> None:
    assert MODULE.stage_end(pd.Timestamp("2023-08-31T12:00:00Z")) == MODULE.FIT_END
    assert MODULE.stage_end(pd.Timestamp("2023-09-01T00:00:00Z")) == MODULE.DEVELOP_END
    assert MODULE.stage_end(pd.Timestamp("2023-11-01T00:00:00Z")) == MODULE.END


def test_route_arbitrates_one_action_and_one_slot() -> None:
    trades, nav = MODULE.route(synthetic_actions(), "score", 24)
    assert list(trades["event_key"]) == ["net:a", "net:c"]
    assert nav > 10000


def test_response_and_source_sign_are_distinct_policies() -> None:
    response, _ = MODULE.route_response(synthetic_actions(), 24)
    source, _ = MODULE.route_source_sign(synthetic_actions(), "net", 24)
    assert list(response["direction"]) == [1, -1]
    assert list(source["direction"]) == [1, -1]
    assert list(response["event_key"]) == ["net:a", "net:c"]
    assert list(source["event_key"]) == ["net:a", "net:c"]


def test_exclusion_precedes_full_reroute() -> None:
    trades, _ = MODULE.route(synthetic_actions(), "score", 24, exclude={"net:a"})
    assert list(trades["event_key"]) == ["net:b", "net:c"]


def test_summary_marks_unresolved_boundary_position() -> None:
    trades, nav = MODULE.route(synthetic_actions(), "score", 24)
    summary = MODULE.summarize(trades, nav)
    assert summary["trades"] == 2
    assert summary["boundary_marks"] == 1


def test_pass_rule_requires_two_stage_breadth_winner_resistance_and_control_superiority() -> None:
    stage_good = {
        "ml_policy": {"24": {"trades": 20, "end_nav": 10100.0}},
        "ml_24bp_winner_deleted": {"end_nav": 10020.0},
    }
    results = {
        "net": {"development": stage_good, "confirmation": stage_good},
        "deposit": {"development": {"ml_policy": {"24": {"end_nav": 9900.0}}}, "confirmation": {"ml_policy": {"24": {"end_nav": 9900.0}}}},
        "release": {"development": {"ml_policy": {"24": {"end_nav": 9950.0}}}, "confirmation": {"ml_policy": {"24": {"end_nav": 9950.0}}}},
    }
    passed, reasons = MODULE.pass_rule(results)
    assert passed and reasons == []
    results["net"]["confirmation"]["ml_policy"]["24"]["trades"] = 2
    passed, reasons = MODULE.pass_rule(results)
    assert not passed and any("trades" in reason for reason in reasons)


def test_fixed_account_contract() -> None:
    assert MODULE.RISK == 0.005
    assert MODULE.CAP == 3.0
    assert MODULE.COSTS == (13, 18, 24)
