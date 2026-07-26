from __future__ import annotations

import math

import numpy as np

import run_parent_order_ml as m


def make_event(
    key: str,
    *,
    date: str = "2025-08-02",
    entry_ms: int = 2_000,
    exit_ms: int = 3_000,
    gross_bp: float = 100.0,
    unresolved: bool = False,
) -> m.Event:
    return m.Event(
        event_key=key,
        date=date,
        partition="confirmation",
        coin="BTC",
        side=1,
        detection_ms=1_000,
        entry_ms=entry_ms,
        exit_ms=exit_ms,
        source_end_ms=10_000,
        entry_price=100.0,
        exit_price=101.0 if not unresolved else 99.0,
        target_price=101.0,
        stop_price=99.0,
        target_distance_bp=100.0,
        stop_distance_bp=100.0,
        gross_return_bp=gross_bp,
        label=None if unresolved else int(gross_bp > 0),
        outcome="source_boundary" if unresolved else ("target" if gross_bp > 0 else "stop"),
        unresolved=unresolved,
        features=(1.0, 0.0, 10.0, 0.0, 5.0, 2.0, 4.0, 0.8, 100.0, 100.0),
    )


def test_same_timestamp_both_barriers_is_stop_first() -> None:
    times = np.asarray([1_000, 2_000, 2_000], dtype=np.int64)
    prices = np.asarray([100.0, 102.0, 98.0], dtype=np.float64)
    label, reason, _, exit_price, unresolved = m.first_passage(
        times, prices, 0, 1, 101.0, 99.0, 2_000
    )
    assert label == 0
    assert reason == "same_timestamp_stop_first"
    assert exit_price == 98.0
    assert unresolved is False


def test_distance_baseline_is_exact_zero_drift_probability() -> None:
    event = make_event("base")
    assert math.isclose(m.baseline_probability(event), 0.5)
    asymmetric = m.Event(**{**event.__dict__, "target_distance_bp": 300.0, "stop_distance_bp": 100.0})
    assert math.isclose(m.baseline_probability(asymmetric), 0.25)


def test_cost_monotonicity_and_fixed_calendar_denominator() -> None:
    action = m.Action(make_event("one"), 0.8, 0.5, 42.0)
    _, low = m.replay([action], 12.0, calendar_dates=["2025-08-02", "2025-08-03", "2025-08-04"])
    _, high = m.replay([action], 24.0, calendar_dates=["2025-08-02", "2025-08-03", "2025-08-04"])
    assert low["final_nav"] > high["final_nav"]
    expected = (low["final_nav"] / m.INITIAL_NAV) ** (1 / 3) - 1
    assert math.isclose(low["geometric_sample_day_growth"], expected)
    assert set(low["date_returns"]) == {"2025-08-02", "2025-08-03", "2025-08-04"}


def test_global_slot_forbids_same_timestamp_reentry() -> None:
    first = m.Action(make_event("first", entry_ms=2_000, exit_ms=3_000), 0.8, 0.5, 42.0)
    second = m.Action(make_event("second", entry_ms=3_000, exit_ms=4_000), 0.9, 0.5, 50.0)
    trades, _ = m.replay([first, second], 12.0)
    assert [row["event_key"] for row in trades] == ["first"]


def test_source_boundary_is_full_structural_stop() -> None:
    unresolved = m.Action(make_event("u", gross_bp=-100.0, unresolved=True), 0.9, 0.5, 50.0)
    trades, metrics = m.replay([unresolved], 12.0)
    assert trades[0]["outcome"] == "source_boundary"
    assert trades[0]["net_return_bp"] == -112.0
    assert metrics["final_nav"] < m.INITIAL_NAV


def test_model_contract_is_minimal_and_direction_locked() -> None:
    contract = m.model_contract_payload()
    assert contract["one_model_family"] is True
    assert contract["direction_lock"] is True
    assert contract["one_economic_decision_rule"] is True
    assert len(contract["feature_columns"]) == 10
    assert m.MODEL_PARAMS["random_state"] == 20260726
