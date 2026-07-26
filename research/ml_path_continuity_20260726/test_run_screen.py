from __future__ import annotations

import math

import numpy as np
import pandas as pd

import run_screen as r


def test_feature_contract_is_single_model_and_fixed() -> None:
    assert len(r.FEATURES) == 22
    assert r.MODEL_PARAMS["random_state"] == 42
    assert set(r.COSTS_BPS) == {12.0, 18.0, 24.0}


def test_prefix_invariance_of_causal_features() -> None:
    market, _, funding = r.synthetic_market("BTCUSDT", bars=5200)
    prefix = r.build_bar_features(market.iloc[:4200], funding)
    full = r.build_bar_features(market, funding).iloc[:4200]
    columns = [
        "path_return_4h",
        "path_efficiency_4h",
        "jump_concentration_4h",
        "atr_percent",
        "prior_4h_high",
        "prior_4h_low",
    ]
    difference = np.nanmax(np.abs(prefix[columns].to_numpy() - full[columns].to_numpy()))
    assert difference <= 1e-12


def test_first_passage_ambiguity_is_explicit() -> None:
    frame = pd.DataFrame(
        {"open": [100.0], "high": [102.0], "low": [98.0], "close": [100.0], "segment": [1]},
        index=[0],
    )
    result = r._first_passage(frame, 0, 101.0, 99.0, r.BAR_MS)
    assert result["label"] == "AMBIGUOUS"


def test_nearest_pool_is_frozen_outside_entry() -> None:
    row = pd.Series(
        {
            "prior_4h_high": 101.0,
            "prior_day_high": 103.0,
            "prior_week_high": 110.0,
            "prior_30d_high": 120.0,
            "prior_4h_low": 99.0,
            "prior_day_low": 97.0,
            "prior_week_low": 90.0,
            "prior_30d_low": 80.0,
        }
    )
    upper, lower = r._nearest_pools(row, 100.0)
    assert upper == 101.0
    assert lower == 99.0


def test_cost_adjusted_action_can_be_long_short_or_flat() -> None:
    class Bundle:
        pass

    frame = pd.DataFrame(
        {
            **{feature: [0.0, 0.0, 0.0] for feature in r.FEATURES},
            "upper_distance_bps": [100.0, 25.0, 40.0],
            "lower_distance_bps": [25.0, 100.0, 40.0],
        }
    )
    original = r._IMPL.predict_probability
    try:
        r._IMPL.predict_probability = lambda bundle, data: np.asarray([0.8, 0.2, 0.5])
        output = r.choose_actions(Bundle(), frame)
    finally:
        r._IMPL.predict_probability = original
    assert list(output.action) == ["LONG", "SHORT", "FLAT"]


def test_funding_sign_is_adverse_to_long_when_rate_positive() -> None:
    timestamp = r.utc_ms("2023-01-01T08:00:00Z")
    funding = {"BTCUSDT": pd.DataFrame({"timestamp_ms": [timestamp], "funding_rate": [0.001]})}
    mark = {
        "BTCUSDT": pd.DataFrame(
            {"timestamp_ms": [timestamp], "open": [100.0], "high": [100.0], "low": [100.0], "close": [100.0]}
        )
    }
    market = {
        "BTCUSDT": pd.DataFrame(
            {
                "timestamp_ms": [timestamp],
                "open": [100.0],
                "high": [100.0],
                "low": [100.0],
                "close": [100.0],
                "volume": [1.0],
                "turnover": [100.0],
            }
        )
    }
    long_pnl, count = r.funding_adjustment(
        "BTCUSDT", timestamp - 1, timestamp, 1, 2.0, funding, mark, market
    )
    short_pnl, _ = r.funding_adjustment(
        "BTCUSDT", timestamp - 1, timestamp, -1, 2.0, funding, mark, market
    )
    assert count == 1
    assert math.isclose(long_pnl, -0.2)
    assert math.isclose(short_pnl, 0.2)


def test_global_slot_blocks_second_overlapping_event() -> None:
    markets = {}
    marks = {}
    fundings = {}
    for index, symbol in enumerate(r.SYMBOLS):
        market, mark, funding = r.synthetic_market(symbol, seed=10 + index, bars=800)
        markets[symbol], marks[symbol], fundings[symbol] = market, mark, funding
    entry = int(markets["BTCUSDT"].timestamp_ms.iloc[100])
    first = {
        "event_key": "a",
        "symbol": "BTCUSDT",
        "action": "LONG",
        "decision_ms": entry - r.BAR_MS,
        "entry_ms": entry,
        "entry_price": 100.0,
        "prior_turnover": 1e10,
        "upper_pool": 101.0,
        "lower_pool": 99.0,
        "label": "UPPER_FIRST",
        "exit_ms": entry + 4 * r.BAR_MS,
        "exit_open": 100.0,
        "gap": False,
        "expected_value_bps": 100.0,
    }
    second = dict(first)
    second["event_key"] = "b"
    second["entry_ms"] = entry + r.BAR_MS
    decisions = pd.DataFrame([first, second])
    result = r.simulate_account(
        decisions,
        r.AccountSpec(0.02, 8.0),
        18.0,
        entry,
        entry + r.DAY_MS,
        markets,
        marks,
        fundings,
    )
    assert result["trade_count"] == 1
    assert result["blocked_signals"] == 1


def test_cost_monotonicity_for_same_decision_path() -> None:
    markets = {}
    marks = {}
    fundings = {}
    for index, symbol in enumerate(r.SYMBOLS):
        market, mark, funding = r.synthetic_market(symbol, seed=20 + index, bars=800)
        markets[symbol], marks[symbol], fundings[symbol] = market, mark, funding
    entry = int(markets["BTCUSDT"].timestamp_ms.iloc[100])
    decisions = pd.DataFrame(
        [
            {
                "event_key": "x",
                "symbol": "BTCUSDT",
                "action": "LONG",
                "decision_ms": entry - r.BAR_MS,
                "entry_ms": entry,
                "entry_price": 100.0,
                "prior_turnover": 1e10,
                "upper_pool": 101.0,
                "lower_pool": 99.0,
                "label": "UPPER_FIRST",
                "exit_ms": entry + r.BAR_MS,
                "exit_open": 100.0,
                "gap": False,
                "expected_value_bps": 100.0,
            }
        ]
    )
    returns = [
        r.simulate_account(
            decisions,
            r.AccountSpec(0.02, 8.0),
            cost,
            entry,
            entry + r.DAY_MS,
            markets,
            marks,
            fundings,
        )["total_return"]
        for cost in r.COSTS_BPS
    ]
    assert returns[0] >= returns[1] >= returns[2]


def test_censored_position_is_not_deleted() -> None:
    markets = {}
    marks = {}
    fundings = {}
    for index, symbol in enumerate(r.SYMBOLS):
        market, mark, funding = r.synthetic_market(symbol, seed=30 + index, bars=800)
        markets[symbol], marks[symbol], fundings[symbol] = market, mark, funding
    entry = int(markets["BTCUSDT"].timestamp_ms.iloc[100])
    decisions = pd.DataFrame(
        [
            {
                "event_key": "u",
                "symbol": "BTCUSDT",
                "action": "LONG",
                "decision_ms": entry - r.BAR_MS,
                "entry_ms": entry,
                "entry_price": 100.0,
                "prior_turnover": 1e10,
                "upper_pool": 101.0,
                "lower_pool": 99.0,
                "label": "CENSORED",
                "exit_ms": entry + 10 * r.BAR_MS,
                "exit_open": 99.7,
                "gap": False,
                "expected_value_bps": 100.0,
            }
        ]
    )
    result = r.simulate_account(
        decisions,
        r.AccountSpec(0.02, 8.0),
        18.0,
        entry,
        entry + r.DAY_MS,
        markets,
        marks,
        fundings,
    )
    assert result["trade_count"] == 1
    assert result["unresolved_positions"] == 1
