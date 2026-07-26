from __future__ import annotations

import math

import numpy as np

import run_parent_slice_ml as m


def make_event(
    key: str,
    *,
    date: str = "2025-08-02",
    entry_ms: int = 2_000,
    exit_ms: int = 3_000,
    gross_bp: float = 30.0,
    stop_bp: float = 20.0,
    unresolved: bool = False,
) -> m.SliceEvent:
    return m.SliceEvent(
        event_key=key,
        date=date,
        partition="confirmation",
        coin="BTC",
        side=1,
        detection_ms=1_000,
        entry_ms=entry_ms,
        logical_exit_ms=exit_ms,
        exit_ms=exit_ms,
        source_end_ms=10_000,
        entry_price=100.0,
        exit_price=100.3 if not unresolved else 99.8,
        stop_price=99.8,
        stop_distance_bp=stop_bp,
        gross_return_bp=-stop_bp if unresolved else gross_bp,
        has_fourth_child=True,
        outcome="source_boundary" if unresolved else "parent_state_exit",
        unresolved=unresolved,
        features=(1.0, 0.0, 10.0, 0.0, 5.0, 2.0, 4.0, 0.8, 0.5),
    )


def test_stop_precedes_parent_state_exit() -> None:
    times = np.asarray([1_000, 2_000, 3_000, 4_000], dtype=np.int64)
    prices = np.asarray([100.0, 99.0, 101.0, 102.0], dtype=np.float64)
    outcome, exit_ms, exit_price, unresolved = m.stop_or_state_exit(
        times, prices, 0, 1, 99.5, 3_500, 5_000
    )
    assert outcome == "structural_stop"
    assert exit_ms == 2_000
    assert exit_price == 99.0
    assert unresolved is False


def test_state_exit_is_first_print_after_causal_trigger() -> None:
    times = np.asarray([1_000, 2_000, 4_000, 4_500], dtype=np.int64)
    prices = np.asarray([100.0, 100.1, 100.3, 100.4], dtype=np.float64)
    outcome, exit_ms, exit_price, unresolved = m.stop_or_state_exit(
        times, prices, 0, 1, 99.0, 3_500, 5_000
    )
    assert outcome == "parent_state_exit"
    assert exit_ms == 4_000
    assert exit_price == 100.3
    assert unresolved is False


def test_source_boundary_is_full_structural_stop() -> None:
    action = m.SliceAction(make_event("u", gross_bp=-20.0, unresolved=True), 30.0)
    trades, metrics = m.replay([action], 12.0, calendar_dates=["2025-08-02"])
    assert trades[0]["outcome"] == "source_boundary"
    assert trades[0]["net_return_bp"] == -32.0
    assert metrics["final_nav"] < m.INITIAL_NAV


def test_global_slot_rejects_same_timestamp_reentry() -> None:
    first = m.SliceAction(make_event("first", entry_ms=2_000, exit_ms=3_000), 40.0)
    second = m.SliceAction(make_event("second", entry_ms=3_000, exit_ms=4_000), 50.0)
    trades, _ = m.replay([first, second], 12.0)
    assert [row["event_key"] for row in trades] == ["first"]


def test_cost_monotonicity_and_no_trade_dates() -> None:
    action = m.SliceAction(make_event("one"), 40.0)
    _, low = m.replay(
        [action], 12.0, calendar_dates=["2025-08-02", "2025-08-03", "2025-08-04"]
    )
    _, high = m.replay(
        [action], 24.0, calendar_dates=["2025-08-02", "2025-08-03", "2025-08-04"]
    )
    assert low["final_nav"] > high["final_nav"]
    assert set(low["date_returns"]) == {"2025-08-02", "2025-08-03", "2025-08-04"}
    expected = (low["final_nav"] / m.INITIAL_NAV) ** (1 / 3) - 1
    assert math.isclose(low["geometric_sample_day_growth"], expected)


def test_minimal_direction_locked_contract() -> None:
    contract = m.model_contract()
    assert contract["one_model_family"] is True
    assert contract["direction_lock"] is True
    assert contract["one_economic_decision_rule"] is True
    assert contract["elapsed_time_liquidation"] is False
    assert len(contract["feature_columns"]) == 9
    assert m.MODEL_PARAMS["random_state"] == 20260726
