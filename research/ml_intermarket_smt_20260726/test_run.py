from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

import run
from run import (
    COSTS_BPS,
    DEVELOPMENT_YEAR,
    FIT_YEAR,
    INITIAL_NAV,
    PIVOT_SPAN,
    PROHIBITED_YEARS,
    Action,
    FrozenModel,
    _coerce_kline,
    _exit_for_action,
    _normalize_dukascopy_payload,
    authorize_actions,
    build_candidate_panel,
    build_risk_panel,
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
        shock_sign=1,
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
    return pd.DataFrame(
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


def test_bybit_parser_and_price_invariants() -> None:
    raw = pd.DataFrame(
        [
            ["2022-01-01 00:00:00", 100, 102, 99, 101, 10],
            ["2022-01-01 00:01:00", 101, 103, 100, 102, 11],
        ]
    )
    parsed = _coerce_kline(raw)
    assert len(parsed) == 2
    assert parsed.index.tz is not None
    assert parsed.iloc[0]["high"] == 102


def test_dukascopy_object_and_array_payloads_parse_identically() -> None:
    timestamp = 1_640_995_200_000
    objects = _normalize_dukascopy_payload(
        [{"timestamp": timestamp, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 5}]
    )
    arrays = _normalize_dukascopy_payload([[timestamp, 100, 102, 99, 101, 5]])
    pd.testing.assert_frame_equal(objects, arrays)


def test_sealed_years_are_physically_rejected() -> None:
    assert FIT_YEAR == 2022 and DEVELOPMENT_YEAR == 2023
    assert set(PROHIBITED_YEARS) == {2024, 2025, 2026}
    for year in PROHIBITED_YEARS:
        with pytest.raises(ValueError, match="sealed year"):
            month_url("BTCUSDT", year, 1)


def test_risk_bar_is_available_only_at_its_close_time() -> None:
    minutes = synthetic_minutes(periods=60 * 24, seed=91)
    panel = build_risk_panel({"usatechidxusd": minutes, "usa500idxusd": minutes.copy()})
    assert panel.index[0] == minutes.index[0] + pd.Timedelta(minutes=1)
    assert minutes.index[0] not in panel.index


def test_candidate_requires_synchronized_shock_and_crypto_lag() -> None:
    index = pd.DatetimeIndex([pd.Timestamp("2022-01-03T14:35:00Z")])
    risk = pd.DataFrame(
        {
            "nq_ret1_z": [1.0],
            "nq_ret5_z": [2.0],
            "sp_ret1_z": [0.9],
            "sp_ret5_z": [1.8],
            "risk_common_z5": [1.9],
            "risk_dispersion_z5": [0.2],
            "risk_range_ratio5": [1.4],
            "shock_sign": [1.0],
            "same_direction": [True],
            "minimum_component_abs_z5": [1.8],
        },
        index=index,
    )
    crypto = pd.DataFrame(
        {"crypto_valid": [True], "crypto_ret1_z": [0.1], "crypto_ret5_z": [0.2]},
        index=index,
    )
    candidate = build_candidate_panel(risk, crypto)
    assert len(candidate) == 1
    crypto["crypto_ret5_z"] = 1.8
    assert build_candidate_panel(risk, crypto).empty
    risk["sp_ret5_z"] = -1.8
    risk["same_direction"] = False
    assert build_candidate_panel(risk, crypto).empty


def test_confirmed_pivot_appears_only_after_right_span() -> None:
    bars = resample_15m(synthetic_minutes(periods=60 * 24 * 12, seed=21))
    high_map, low_map = confirmed_pivot_maps(bars)
    assert high_map and low_map
    for confirmation_index, pool in list(high_map.items()) + list(low_map.items()):
        assert confirmation_index == pool.origin_i + PIVOT_SPAN
        assert pool.confirm_i > pool.origin_i


def test_both_barrier_touch_is_ambiguous_label() -> None:
    minutes = tiny_minutes()
    label, outcome, exit_time = first_passage(minutes, minutes.index[0], upper=102.0, lower=99.0)
    assert label == -1
    assert outcome == "both"
    assert exit_time == minutes.index[1] + pd.Timedelta(minutes=1)


def test_source_gap_stops_label_scan_without_favorable_fill() -> None:
    minutes = tiny_minutes()
    minutes.loc[minutes.index[1], "valid"] = False
    label, outcome, _ = first_passage(minutes, minutes.index[0], upper=110.0, lower=90.0)
    assert label == -2
    assert outcome == "source_gap"


def test_same_minute_ambiguity_is_stop_first_for_each_direction() -> None:
    long_price, long_reason = _exit_for_action(action(outcome="both", side=1, shock_sign=1))
    short_price, short_reason = _exit_for_action(
        action(outcome="both", side=-1, shock_sign=-1, stop_price=102.0, target_price=99.0)
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
    navs = []
    for cost in COSTS_BPS:
        trades, nav = replay_account([action()], cost)
        assert len(trades) == 1
        navs.append(nav)
    assert navs[0] > navs[1] > navs[2]


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


def test_authorized_direction_must_equal_external_shock(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = pd.DataFrame(
        [
            {
                "event_key": "long",
                "symbol": "BTCUSDT",
                "shock_sign": 1,
                "decision_time": pd.Timestamp("2022-10-01T00:00:00Z"),
                "entry_time": pd.Timestamp("2022-10-01T00:00:00Z"),
                "exit_time": pd.Timestamp("2022-10-01T00:05:00Z"),
                "entry_price": 100.0,
                "upper_price": 104.0,
                "lower_price": 99.0,
                "prior_volume": 1_000_000.0,
                "outcome": "high",
                **{column: 0.0 for column in run.FEATURE_COLUMNS},
            },
            {
                "event_key": "short",
                "symbol": "ETHUSDT",
                "shock_sign": -1,
                "decision_time": pd.Timestamp("2022-10-01T00:10:00Z"),
                "entry_time": pd.Timestamp("2022-10-01T00:10:00Z"),
                "exit_time": pd.Timestamp("2022-10-01T00:15:00Z"),
                "entry_price": 100.0,
                "upper_price": 101.0,
                "lower_price": 96.0,
                "prior_volume": 1_000_000.0,
                "outcome": "low",
                **{column: 0.0 for column in run.FEATURE_COLUMNS},
            },
        ]
    )
    dummy = FrozenModel(None, None, run.FEATURE_COLUMNS, 0, 0, 0.5, 0.5)  # type: ignore[arg-type]
    monkeypatch.setattr(run, "predict_probability", lambda model, rows: np.array([0.95, 0.05]))
    actions = authorize_actions(dummy, frame)
    assert [(item.event_key, item.side, item.shock_sign) for item in actions] == [
        ("long", 1, 1),
        ("short", -1, -1),
    ]


def test_frozen_model_trains_calibrates_and_scores_chronologically() -> None:
    rng = np.random.default_rng(20260726)
    partitions = [
        (pd.date_range("2022-01-02", "2022-06-29", periods=900, tz="UTC"), "train"),
        (pd.date_range("2022-07-02", "2022-09-28", periods=300, tz="UTC"), "calibration"),
        (pd.date_range("2022-10-02", "2022-12-28", periods=600, tz="UTC"), "confirmation"),
    ]
    rows = []
    for times, _ in partitions:
        for timestamp in times:
            risk = rng.normal()
            geometry = rng.uniform(0.15, 0.85)
            probability = 1.0 / (1.0 + np.exp(-(0.9 * risk + 1.4 * (geometry - 0.5))))
            label = int(rng.random() < probability)
            features = {column: rng.normal() for column in run.FEATURE_COLUMNS}
            features["risk_common_z5"] = risk
            features["range_position"] = geometry
            features["is_eth"] = float(rng.random() < 0.5)
            rows.append(
                {
                    "event_key": f"e{len(rows)}",
                    "symbol": "ETHUSDT" if features["is_eth"] else "BTCUSDT",
                    "shock_sign": 1 if risk >= 0 else -1,
                    "decision_time": timestamp,
                    "entry_time": timestamp,
                    "exit_time": timestamp + pd.Timedelta(minutes=5),
                    "entry_price": 100.0,
                    "upper_price": 101.0,
                    "lower_price": 99.0,
                    "prior_volume": 1_000_000.0,
                    "label": label,
                    "outcome": "high" if label else "low",
                    **features,
                }
            )
    events = pd.DataFrame(rows)
    model = run.fit_frozen_model(events)
    confirmation = events.loc[events["decision_time"] >= run.CALIBRATION_END]
    metrics = run.prediction_metrics(model, confirmation)
    assert model.train_rows == 900
    assert model.calibration_rows == 300
    assert metrics["rows"] == 600
    assert np.isfinite(metrics["auc"])
