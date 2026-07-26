from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from run import (
    COSTS_BPS,
    DEVELOPMENT_YEAR,
    FIT_YEAR,
    INITIAL_NAV,
    PIVOT_SPAN,
    PROHIBITED_YEARS,
    Action,
    _coerce_kline,
    _exit_for_action,
    build_feature_panels,
    confirmed_pivot_maps,
    daily_nav_series,
    first_passage,
    maximum_drawdown,
    month_url,
    replay_account,
    resample_15m,
    synthetic_minutes,
)


def action(**overrides: object) -> Action:
    base = Action(
        event_key="event",
        symbol="BTCUSDT",
        side=1,
        decision_time="2022-01-01T00:00:00+00:00",
        entry_time="2022-01-01T00:00:00+00:00",
        exit_time="2022-01-01T00:02:00+00:00",
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        prior_volume=1_000_000.0,
        outcome="high",
        calibrated_probability_high_first=0.75,
        probability_advantage=0.10,
        expected_net_return_at_signal_cost=0.002,
    )
    return Action(**{**asdict(base), **overrides})


def tiny_minutes() -> pd.DataFrame:
    index = pd.date_range("2022-01-01T00:00:00Z", periods=5, freq="1min")
    frame = pd.DataFrame(
        {
            "open": [100.0] * 5,
            "high": [100.2, 102.5, 100.5, 100.5, 100.5],
            "low": [99.8, 98.5, 99.5, 99.5, 99.5],
            "close": [100.0] * 5,
            "volume": [1_000_000.0] * 5,
            "valid": [True] * 5,
        },
        index=index,
    )
    return frame


def test_parser_and_price_invariants() -> None:
    raw = pd.DataFrame(
        [
            ["2022-01-01 00:00:00", 100, 102, 99, 101, 10],
            ["2022-01-01 00:01:00", 101, 103, 100, 102, 11],
        ]
    )
    parsed = _coerce_kline(raw)
    assert len(parsed) == 2
    assert parsed.index.tz is not None
    assert parsed.loc[parsed.index[0], "high"] == 102


def test_sealed_years_are_physically_rejected() -> None:
    assert FIT_YEAR == 2022 and DEVELOPMENT_YEAR == 2023
    assert set(PROHIBITED_YEARS) == {2024, 2025, 2026}
    for year in PROHIBITED_YEARS:
        with pytest.raises(ValueError, match="sealed year"):
            month_url("BTCUSDT", year, 1)


def test_confirmed_pivot_appears_only_after_right_span() -> None:
    minutes = synthetic_minutes(periods=60 * 24 * 12, seed=21)
    bars = resample_15m(minutes)
    high_map, low_map = confirmed_pivot_maps(bars)
    assert high_map and low_map
    for confirmation_index, pool in list(high_map.items()) + list(low_map.items()):
        assert confirmation_index == pool.origin_i + PIVOT_SPAN
        assert pool.confirm_i > pool.origin_i


def test_both_barrier_touch_is_ambiguous_label() -> None:
    minutes = tiny_minutes()
    label, outcome, exit_time, high_price, low_price = first_passage(
        minutes, minutes.index[0], upper=102.0, lower=99.0
    )
    assert label == -1
    assert outcome == "both"
    assert exit_time == minutes.index[1] + pd.Timedelta(minutes=1)
    assert high_price == 102.0 and low_price == 99.0


def test_source_gap_stops_label_scan_without_favorable_fill() -> None:
    minutes = tiny_minutes()
    minutes.loc[minutes.index[1], "valid"] = False
    label, outcome, *_ = first_passage(minutes, minutes.index[0], upper=110.0, lower=90.0)
    assert label == -2
    assert outcome == "source_gap"


def test_same_minute_ambiguity_is_stop_first_for_each_direction() -> None:
    long_price, long_reason = _exit_for_action(action(outcome="both", side=1))
    short_price, short_reason = _exit_for_action(
        action(outcome="both", side=-1, stop_price=102.0, target_price=99.0)
    )
    assert long_price == 99.0 and long_reason == "stop_first_same_minute"
    assert short_price == 102.0 and short_reason == "stop_first_same_minute"


def test_one_global_slot_blocks_overlapping_second_symbol() -> None:
    first = action(event_key="first", exit_time="2022-01-01T00:05:00+00:00")
    second = action(
        event_key="second",
        symbol="ETHUSDT",
        entry_time="2022-01-01T00:01:00+00:00",
        exit_time="2022-01-01T00:03:00+00:00",
    )
    trades, _ = replay_account([first, second], 12.0)
    assert [trade.event_key for trade in trades] == ["first"]


def test_counterfactual_exclusion_releases_global_slot() -> None:
    first = action(event_key="first", exit_time="2022-01-01T00:05:00+00:00")
    second = action(
        event_key="second",
        symbol="ETHUSDT",
        entry_time="2022-01-01T00:01:00+00:00",
        exit_time="2022-01-01T00:03:00+00:00",
    )
    baseline, _ = replay_account([first, second], 12.0)
    counterfactual, _ = replay_account([first, second], 12.0, {"first"})
    assert [trade.event_key for trade in baseline] == ["first"]
    assert [trade.event_key for trade in counterfactual] == ["second"]


def test_cost_stress_decreases_nav_on_identical_action() -> None:
    paths = []
    for cost in COSTS_BPS:
        trades, nav = replay_account([action()], cost)
        assert len(trades) == 1
        paths.append(nav)
    assert paths[0] > paths[1] > paths[2]


def test_boundary_outcome_is_charged_full_structural_stop() -> None:
    unresolved = action(outcome="year_boundary", exit_time="2022-12-31T23:59:00+00:00")
    trades, nav = replay_account([unresolved], 12.0)
    assert trades[0].exit_reason == "conservative_boundary_stop"
    assert trades[0].exit_price == unresolved.stop_price
    assert nav < INITIAL_NAV


def test_daily_nav_contains_every_utc_calendar_day() -> None:
    minutes = tiny_minutes()
    open_trade = action(exit_time="2022-01-03T00:00:00+00:00", outcome="year_boundary")
    trades, _ = replay_account([open_trade], 12.0)
    nav = daily_nav_series(
        trades,
        {"BTCUSDT": minutes},
        pd.Timestamp("2022-01-01T00:00:00Z"),
        pd.Timestamp("2022-01-04T00:00:00Z"),
    )
    assert len(nav) == 3
    assert list(nav.index) == list(pd.date_range("2022-01-01", periods=3, freq="1D", tz="UTC"))
    assert maximum_drawdown(nav) >= 0.0


def test_cross_asset_panel_is_synchronized_and_causal() -> None:
    btc = resample_15m(synthetic_minutes(periods=60 * 24 * 12, seed=31))
    eth = resample_15m(synthetic_minutes(periods=60 * 24 * 12, seed=32))
    panels = build_feature_panels({"BTCUSDT": btc, "ETHUSDT": eth})
    assert panels["BTCUSDT"].index.equals(panels["ETHUSDT"].index)
    np.testing.assert_allclose(
        panels["BTCUSDT"]["market_ret1"].to_numpy(),
        panels["ETHUSDT"]["market_ret1"].to_numpy(),
        equal_nan=True,
    )
