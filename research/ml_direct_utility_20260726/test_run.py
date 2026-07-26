from __future__ import annotations

import math

import pandas as pd

import run


def funding_fixture():
    result = {symbol: pd.Series(dtype=float) for symbol in run.SYMBOLS}
    for series in result.values():
        series.attrs["mode"] = "ADVERSE_RESERVE_INCOMPLETE_API"
    return result


def test_no_elapsed_time_liquidation_and_one_slot():
    rows = run.synthetic_rows(hours=40, prediction=0.003)
    result = run.replay(rows, funding_fixture(), run.PathConfig(12.0))
    assert result.position_hours >= 30
    assert result.trade_count <= 3
    assert result.turnover < result.position_hours


def test_cost_monotonicity():
    rows = run.synthetic_rows(hours=20, prediction=0.003)
    low = run.replay(rows, funding_fixture(), run.PathConfig(12.0))
    high = run.replay(rows, funding_fixture(), run.PathConfig(24.0))
    assert high.final_nav <= low.final_nav + 1e-9


def test_blocked_start_prevents_original_open():
    rows = run.synthetic_rows(hours=10, prediction=0.003)
    first = rows[rows["symbol"] == "BTCUSDT"].iloc[0]
    key = f"{pd.Timestamp(first['decision_time']).isoformat()}|BTCUSDT|+1"
    ordinary = run.replay(rows, funding_fixture(), run.PathConfig(12.0))
    blocked = run.replay(rows, funding_fixture(), run.PathConfig(12.0), {key})
    assert blocked.blocked_start_count == 1
    assert blocked.trade_records
    assert blocked.trade_records[0]["start_key"] != key
    assert ordinary.trade_records[0]["start_key"] == key


def test_risk_multiplier_respects_cap():
    record = pd.Series({"entry_open": 100.0, "known_low24": 99.0, "known_high24": 101.0})
    config = run.PathConfig(24.0, "risk", 0.60, 20.0)
    assert math.isclose(run.action_multiplier(record, 1, config), 20.0)


def test_prohibited_period_boundary():
    assert run.END_EXCLUSIVE == pd.Timestamp("2024-01-01T00:00:00Z")
    assert run.DEV_END.year == 2024 and run.DEV_END.month == 1 and run.DEV_END.day == 1


def test_gap_resets_all_crossing_horizons():
    prices = pd.Series([100.0, 101.0, math.nan, 103.0, 104.0, 105.0])
    returns = run.continuous_log_return(prices.map(math.log), prices.notna(), 2)
    assert returns.iloc[:5].isna().all()
    assert math.isclose(float(returns.iloc[5]), math.log(105.0 / 103.0))
