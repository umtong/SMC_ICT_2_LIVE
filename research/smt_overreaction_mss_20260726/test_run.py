from __future__ import annotations

import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import base_probe as base
import run


def day(symbol: str, mark: np.ndarray, signed: np.ndarray | None = None) -> base.DayArrays:
    n = len(mark)
    total = np.full(n, 1_000_000.0)
    if signed is None:
        signed = np.zeros(n)
    count = np.full(n, 10, dtype=np.int32)
    return base.DayArrays(symbol, "1970-01-01", mark.astype(float), total, signed.astype(float), count)


def synthetic_confirmation() -> tuple[base.DayArrays, base.DayArrays, dict[str, np.ndarray], dict]:
    n = 220
    leader_mark = np.full(n, 100.0)
    follower_mark = np.full(n, 100.50)
    start = 90
    shock = 100
    leader_mark[shock:] = 101.0
    follower_mark[shock:105] = [102.00, 102.10, 101.80, 101.10, 100.40]
    follower_mark[105:] = 100.20
    signed = np.zeros(n)
    signed[shock:105] = -600_000.0
    leader = day("BTCUSDT", leader_mark)
    follower = day("SOLUSDT", follower_mark, signed)
    features = {
        "direction": np.zeros(n),
        "start_idx": np.full(n, -1),
        "beta": np.full(n, np.nan),
        "gap": np.full(n, np.nan),
    }
    features["direction"][shock] = 1
    features["start_idx"][shock] = start
    features["beta"][shock] = 1.0
    btc_move = math.log(leader_mark[shock] / leader_mark[start])
    fol_move = math.log(follower_mark[shock] / follower_mark[start])
    features["gap"][shock] = btc_move - fol_move
    result = run.confirm_mss(leader, follower, features, shock, 1)
    assert result is not None
    return leader, follower, features, result


def test_parameter_grid_and_stable_candidate_id() -> None:
    grid = list(run.parameter_grid())
    assert len(grid) == 288
    assert run.candidate_id(grid[0]) == run.candidate_id(dict(grid[0]))


def test_mss_confirmation_is_completed_and_prefix_invariant() -> None:
    leader, follower, features, result = synthetic_confirmation()
    assert result["decision_idx"] == 104
    assert result["confirmation_seconds"] == 0.5
    assert math.isclose(result["extreme"], 102.10)
    assert result["flow_flip"] > 0

    changed = base.DayArrays(
        follower.symbol,
        follower.date,
        follower.mark.copy(),
        follower.total_notional.copy(),
        follower.signed_notional.copy(),
        follower.trade_count.copy(),
    )
    changed.mark[180] = 200.0
    changed.signed_notional[180] = 1_000_000.0
    result2 = run.confirm_mss(leader, changed, features, 100, 1)
    assert result2 is not None
    for key in ("decision_idx", "confirmation_seconds", "flow_flip", "extreme", "fair_price", "remaining_gap_bps"):
        assert result2[key] == result[key]


def test_entry_waits_for_latency_and_structural_target() -> None:
    _, _, _, confirmation = synthetic_confirmation()
    event = {
        "trade_direction": -1,
        "decision_time": 10.5,
        "extreme": confirmation["extreme"],
        "fair_price": 100.40,
    }
    raw = (
        np.array([10.55, 10.60, 10.70, 10.80, 10.90]),
        np.array([101.20, 101.00, 100.80, 100.40, 100.30]),
    )
    outcome = run.barrier_outcome(raw, event, 100, "fair_value")
    assert outcome["valid"] is True
    assert outcome["entry_time"] >= 10.60
    assert outcome["reason"] == "TARGET"
    assert outcome["gross_bps"] > 0


def test_stop_priority_and_terminal_full_stop() -> None:
    event = {"trade_direction": -1, "decision_time": 10.0, "extreme": 102.0, "fair_price": 100.0}
    raw_stop = (
        np.array([10.1, 10.2, 10.3]),
        np.array([101.0, 102.2, 99.0]),
    )
    stopped = run.barrier_outcome(raw_stop, event, 100, "one_point_five_r")
    assert stopped["valid"] is True
    assert stopped["reason"] == "STOP"
    assert stopped["gross_bps"] < 0

    raw_unresolved = (
        np.array([10.1, 10.2, 10.3]),
        np.array([101.0, 101.0, 101.0]),
    )
    unresolved = run.barrier_outcome(raw_unresolved, event, 100, "one_point_five_r")
    assert unresolved["valid"] is True
    assert unresolved["reason"] == "TERMINAL_FULL_STOP"
    assert unresolved["unresolved"] is True
    assert unresolved["gross_bps"] < 0


def test_global_slot_arbitration_and_counterfactual_exclusion() -> None:
    rows = [
        {"event_id": "a", "decision_time": 1.0, "priority": 3.0, "exit_time": 3.0},
        {"event_id": "b", "decision_time": 1.0, "priority": 2.0, "exit_time": 2.0},
        {"event_id": "c", "decision_time": 2.0, "priority": 5.0, "exit_time": 4.0},
        {"event_id": "d", "decision_time": 3.0, "priority": 1.0, "exit_time": 5.0},
    ]
    assert [row["event_id"] for row in run.route(rows)] == ["a", "d"]

    trades = [
        {"gross_bps": 30.0, "event_id": "a"},
        {"gross_bps": 20.0, "event_id": "b"},
        {"gross_bps": -5.0, "event_id": "c"},
    ]
    assert run.top_exclusions(trades) == {"a"}


def test_funding_boundary_counter() -> None:
    assert run.funding_boundaries(1.0, 28_801.0) == 1
    assert run.funding_boundaries(28_799.0, 57_601.0) == 2
