from __future__ import annotations

import math

import numpy as np
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


def test_source_gap_forces_adverse_boundary_and_releases_slot():
    rows = run.synthetic_rows(hours=20, prediction=0.003)
    gap_start = pd.Timestamp("2023-01-01T08:00:00Z")
    gap_end = pd.Timestamp("2023-01-01T12:00:00Z")
    rows = rows[(rows["decision_time"] < gap_start) | (rows["decision_time"] >= gap_end)].copy()
    result = run.replay(rows, funding_fixture(), run.PathConfig(12.0))
    assert result.boundary_stop_count >= 1
    assert any(item["reason"] == "SOURCE_GAP_FULL_STOP" for item in result.trade_records)


def test_build_rows_never_bridges_missing_hour():
    index = pd.date_range(run.START, periods=800, freq="1h")
    markets = {}
    x = np.arange(len(index), dtype=float)
    for i, symbol in enumerate(run.SYMBOLS):
        base = 100.0 + i * 10.0
        close = base * np.exp(0.0002 * x + 0.005 * np.sin(x / (7.0 + i)))
        open_ = close * (1.0 + 0.0005 * np.sin(x / 3.0))
        frame = pd.DataFrame(
            {
                "open": open_,
                "high": np.maximum(open_, close) * 1.001,
                "low": np.minimum(open_, close) * 0.999,
                "close": close,
                "volume": 1000.0 + 50.0 * np.cos(x / (5.0 + i)),
                "source_valid": True,
            },
            index=index,
        )
        full = pd.date_range(run.START, run.END_EXCLUSIVE - pd.Timedelta(hours=1), freq="1h")
        markets[symbol] = frame.reindex(full)
        markets[symbol]["source_valid"] = markets[symbol][["open", "high", "low", "close"]].notna().all(axis=1)
    missing = index[350]
    markets["BTCUSDT"].loc[missing, ["open", "high", "low", "close", "volume"]] = float("nan")
    markets["BTCUSDT"].loc[missing, "source_valid"] = False
    rows = run.build_rows(markets)
    assert not ((rows["decision_time"] < missing) & (rows["exit_time"] > missing)).any()
    post = rows[rows["decision_time"] > missing]
    assert len(post)
    assert post["decision_time"].min() >= missing + pd.Timedelta(hours=169)
