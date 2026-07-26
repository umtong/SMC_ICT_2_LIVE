from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

import run as wp


def config(**overrides) -> wp.Config:
    payload = dict(
        accumulation_days=1,
        sweep_depth_atr60=0.25,
        maximum_confirmation_hours=3,
        minimum_displacement_atr60=0.5,
        target_mode="opposite_accumulation",
        minimum_reward_risk=2.0,
    )
    payload.update(overrides)
    return wp.Config(**payload)


def frame() -> pd.DataFrame:
    index = pd.date_range("2022-01-03", periods=8, freq="5min", tz="UTC")
    result = pd.DataFrame(
        {
            "open": [100.0, 100.0, 101.0, 100.0, 103.0, 104.0, 104.0, 104.0],
            "high": [100.2, 101.2, 106.0, 105.0, 105.0, 105.0, 105.0, 105.0],
            "low": [99.8, 99.0, 94.0, 95.0, 102.0, 103.0, 103.0, 103.0],
            "close": [100.0, 101.0, 95.0, 104.0, 104.0, 104.0, 104.0, 104.0],
            "volume": [1_000_000.0] * 8,
            "valid": [True] * 8,
        },
        index=index,
    )
    result["quote_volume"] = result["close"] * result["volume"]
    result["close_time"] = result.index + pd.Timedelta(minutes=5)
    return result


def trade(**overrides) -> wp.CandidateTrade:
    payload = dict(
        config_id="cfg",
        event_key="a",
        symbol="BTCUSDT",
        profile="classic_buy_week",
        side=1,
        entry_i=1,
        exit_i=3,
        entry_time="2022-01-04T00:05:00+00:00",
        exit_time="2022-01-04T00:15:00+00:00",
        entry_price=100.0,
        exit_price=104.0,
        stop_price=98.0,
        target_price=104.0,
        exit_reason="weekly_liquidity_target",
        score=3.0,
        quote_volume_prior=10_000_000.0,
        open_at_boundary=False,
        week_start="2022-01-03T00:00:00+00:00",
        accumulation_end="2022-01-04T00:00:00+00:00",
        accumulation_high=110.0,
        accumulation_low=100.0,
        sweep_time="2022-01-04T01:00:00+00:00",
        confirmation_time="2022-01-04T02:00:00+00:00",
        sweep_extreme=95.0,
        displacement_atr60=1.0,
    )
    payload.update(overrides)
    return wp.CandidateTrade(**payload)


def test_grid_exact() -> None:
    assert len(wp.configs()) == 64
    assert len({c.config_id for c in wp.configs()}) == 64


def test_sealed_year_rejected() -> None:
    with pytest.raises(ValueError, match="sealed"):
        wp.month_url("BTCUSDT", 2024, 1)


def test_header_and_headerless_equal() -> None:
    rows = [
        ["2022-01-01 00:00:00", "100", "101", "99", "100.5", "12"],
        ["2022-01-01 00:05:00", "100.5", "102", "100", "101", "13"],
    ]
    a = wp._coerce_kline(pd.DataFrame(rows))
    b = wp._coerce_kline(pd.DataFrame([["datetime", "open", "high", "low", "close", "volume"], *rows]))
    pd.testing.assert_frame_equal(a, b)


def test_week_start_is_monday_utc() -> None:
    assert wp.week_start_for(pd.Timestamp("2022-01-05T12:00:00Z")) == pd.Timestamp("2022-01-03T00:00:00Z")


def test_accumulation_requires_complete_range() -> None:
    index = pd.date_range("2022-01-03", periods=288 + 7 * 288, freq="5min", tz="UTC")
    f = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0, "valid": True}, index=index)
    f.loc[index[100], "valid"] = False
    contexts = wp.weekly_contexts(f, 1)
    assert all(pd.Timestamp(c["week_start"]) != pd.Timestamp("2022-01-03T00:00:00Z") for c in contexts)


def test_last_opposite_candle_is_strictly_before_sweep() -> None:
    index = pd.date_range("2022-01-03T01:00:00Z", periods=3, freq="1h")
    h = pd.DataFrame({"open": [100.0, 102.0, 101.0], "close": [102.0, 101.0, 103.0], "valid": True}, index=index)
    assert wp._last_opposite_open(h, index[2], bullish_setup=True) == 102.0
    assert wp._last_opposite_open(h, index[2], bullish_setup=False) == 100.0


def test_next_bar_entry_after_hour_close() -> None:
    f = frame()
    assert wp._five_minute_index_at(f, f.index[3]) == 3


def test_stop_first_on_same_bar() -> None:
    f = frame()
    metadata = {
        "week_start": "2022-01-03T00:00:00+00:00",
        "accumulation_end": "2022-01-04T00:00:00+00:00",
        "accumulation_high": 104.0,
        "accumulation_low": 96.0,
        "sweep_time": "2022-01-04T01:00:00+00:00",
        "confirmation_time": "2022-01-04T02:00:00+00:00",
        "sweep_extreme": 94.0,
        "displacement_atr60": 1.0,
    }
    t = wp._resolve_trade(f, config(), "BTCUSDT", 1, 1, 98.0, 104.0, 2.0, metadata)
    assert t.exit_reason == "stop_first"
    assert t.exit_price == 98.0


def test_source_gap_receives_structural_stop() -> None:
    f = frame()
    f.loc[f.index[2], "valid"] = False
    metadata = {
        "week_start": "2022-01-03T00:00:00+00:00",
        "accumulation_end": "2022-01-04T00:00:00+00:00",
        "accumulation_high": 110.0,
        "accumulation_low": 96.0,
        "sweep_time": "2022-01-04T01:00:00+00:00",
        "confirmation_time": "2022-01-04T02:00:00+00:00",
        "sweep_extreme": 94.0,
        "displacement_atr60": 1.0,
    }
    t = wp._resolve_trade(f, config(), "BTCUSDT", 1, 1, 98.0, 110.0, 2.0, metadata)
    assert t.exit_reason == "source_gap_structural_stop"


def test_no_elapsed_time_exit() -> None:
    f = frame()
    f.loc[:, "high"] = np.minimum(f["high"], 103.0)
    f.loc[:, "low"] = np.maximum(f["low"], 99.0)
    metadata = {
        "week_start": "2022-01-03T00:00:00+00:00",
        "accumulation_end": "2022-01-04T00:00:00+00:00",
        "accumulation_high": 110.0,
        "accumulation_low": 96.0,
        "sweep_time": "2022-01-04T01:00:00+00:00",
        "confirmation_time": "2022-01-04T02:00:00+00:00",
        "sweep_extreme": 94.0,
        "displacement_atr60": 1.0,
    }
    t = wp._resolve_trade(f, config(), "BTCUSDT", 1, 1, 98.0, 110.0, 2.0, metadata)
    assert t.exit_reason == "boundary_mark"
    assert t.open_at_boundary is True


def test_global_slot_and_counterfactual_release() -> None:
    winner = trade(event_key="winner", score=5.0, exit_time="2022-01-04T00:20:00+00:00")
    blocked = replace(winner, event_key="blocked", symbol="ETHUSDT", score=1.0)
    later = trade(event_key="later", entry_time="2022-01-04T00:20:00+00:00", exit_time="2022-01-04T00:30:00+00:00")
    assert [x.event_key for x in wp.select_global([winner, blocked, later])] == ["winner", "later"]
    assert [x.event_key for x in wp.select_global([winner, blocked], {"winner"})] == ["blocked"]


def test_cost_stress_reduces_nav() -> None:
    selected = [trade()]
    _, low = wp.replay_account(selected, 12.0)
    _, high = wp.replay_account(selected, 24.0)
    assert float(low["nav"]) > float(high["nav"])


def test_open_position_cannot_pass_gate() -> None:
    passing = {
        "terminal_account_loss": False,
        "completed_trades": 100,
        "total_return": 0.2,
        "median_trade_bps": 2.0,
        "profit_factor": 1.5,
        "maximum_drawdown": 0.1,
        "first_half_return": 0.1,
        "second_half_return": 0.1,
        "top_five_positive_pnl_share": 0.2,
        "open_position_count": 1,
    }
    by_cost = {12.0: dict(passing), 18.0: dict(passing), 24.0: dict(passing)}
    assert wp.preliminary_pass(by_cost) is False
