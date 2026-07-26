from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from run import (
    COSTS_BPS,
    FEATURES,
    FIT_DATE,
    LABEL_NO_FILL,
    LABEL_STOP,
    LABEL_TARGET,
    Decision,
    STRUCTURE_FEATURES,
    confirmed_pivots,
    exact_expectancy_bps,
    latest_values,
    maximum_drawdown,
    path_metrics,
    replay_policy,
    source_rows,
)


def decision(**overrides: object) -> Decision:
    base = Decision(
        event_key="event",
        date=FIT_DATE,
        side=1,
        signal_time_us=1_000_000,
        order_time_us=1_200_000,
        fill_time_us=1_500_000,
        end_time_us=2_000_000,
        order_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        exit_price=102.0,
        queue_ahead=1.0,
        simulated_quantity=0.02,
        prior_60s_volume=100.0,
        label=LABEL_TARGET,
        exit_reason="opposing_external_liquidity",
        features=tuple([1.0] * len(FEATURES)),
    )
    return replace(base, **overrides)


def test_feature_contract_is_small_and_fixed() -> None:
    assert len(FEATURES) == 20
    assert len(STRUCTURE_FEATURES) == 9
    assert len(set(FEATURES)) == len(FEATURES)


def test_sealed_year_is_rejected_before_manifest_access() -> None:
    with pytest.raises(ValueError, match="sealed year"):
        source_rows(Path("does-not-exist"), "2024-01-01")


def test_latest_pivot_never_appears_before_confirmation() -> None:
    query = np.asarray([9, 10, 19, 20], dtype=np.int64)
    event = np.asarray([10, 20], dtype=np.int64)
    values = np.asarray([100.0, 200.0])
    observed = latest_values(query, event, values)
    assert np.isnan(observed[0])
    assert observed[1] == 100.0
    assert observed[2] == 100.0
    assert observed[3] == 200.0


def test_confirmed_pivot_is_delayed_by_right_span() -> None:
    bars = pd.DataFrame(
        {
            "high": [1, 2, 5, 2, 1, 3, 1],
            "low": [0, -1, 0, -2, 0, -1, 0],
            "valid": [True] * 7,
            "close_us": np.arange(1, 8, dtype=np.int64) * 10,
        }
    )
    high_times, high_prices, low_times, low_prices = confirmed_pivots(bars, 1)
    assert 40 in high_times.tolist()  # origin at close 30, usable only at close 40
    assert 50 in low_times.tolist()   # origin at close 40, usable only at close 50
    assert 5.0 in high_prices.tolist()
    assert -2.0 in low_prices.tolist()


def test_no_fill_occupies_global_slot_without_pnl() -> None:
    first = decision(event_key="first", label=LABEL_NO_FILL, fill_time_us=None, exit_price=None, end_time_us=5_000_000)
    second = decision(event_key="second", signal_time_us=2_000_000, order_time_us=2_200_000, fill_time_us=2_500_000, end_time_us=3_000_000)
    trades, nav, _, accepted = replay_policy([first, second], {"first": True, "second": True}, 12.0)
    assert not trades
    assert nav == 10_000.0
    assert accepted == ["first"]


def test_same_selected_path_degrades_with_cost() -> None:
    row = decision()
    selected = {row.event_key: True}
    finals = [path_metrics([row], selected, cost)["final_nav"] for cost in COSTS_BPS]
    assert finals[0] > finals[1] > finals[2]


def test_stop_trade_is_loss_and_no_liquidation() -> None:
    row = decision(label=LABEL_STOP, exit_price=98.5, exit_reason="structural_stop_or_same_timestamp")
    metrics = path_metrics([row], {row.event_key: True}, 12.0)
    assert metrics["total_return"] < 0
    assert metrics["stop_exits"] == 1
    assert metrics["liquidation"] is False


def test_probability_rule_uses_nofill_as_zero_payoff() -> None:
    row = decision()
    positive = exact_expectancy_bps(row, np.asarray([0.10, 0.80, 0.10]))
    negative = exact_expectancy_bps(row, np.asarray([0.10, 0.10, 0.80]))
    mostly_nofill = exact_expectancy_bps(row, np.asarray([0.98, 0.01, 0.01]))
    assert positive > 0
    assert negative < 0
    assert abs(mostly_nofill) < abs(negative)


def test_counterfactual_removal_releases_slot() -> None:
    first = decision(event_key="first", end_time_us=5_000_000)
    second = decision(event_key="second", signal_time_us=2_000_000, order_time_us=2_200_000, fill_time_us=2_500_000, end_time_us=3_000_000)
    baseline, *_ = replay_policy([first, second], {"first": True, "second": True}, 12.0)
    counterfactual, *_ = replay_policy([first, second], {"first": True, "second": True}, 12.0, {"first"})
    assert [row.event_key for row in baseline] == ["first"]
    assert [row.event_key for row in counterfactual] == ["second"]


def test_maximum_drawdown_is_positive_magnitude() -> None:
    assert maximum_drawdown([100.0, 110.0, 88.0, 99.0]) == pytest.approx(0.20)
