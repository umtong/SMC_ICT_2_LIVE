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


def _sequence_rows(direction: int, prices: list[tuple[float, float]], final_prediction: float) -> pd.DataFrame:
    times = pd.date_range("2023-01-01T00:00:00Z", periods=len(prices), freq="1h")
    output = []
    for i, (entry, exit_price) in enumerate(prices):
        prediction = direction * 0.10 if i < len(prices) - 1 else final_prediction
        for symbol in run.SYMBOLS:
            selected = symbol == "BTCUSDT"
            output.append({
                "decision_time": times[i],
                "entry_time": times[i] + pd.Timedelta(hours=1),
                "exit_time": times[i] + pd.Timedelta(hours=2),
                "symbol": symbol,
                "prediction": prediction if selected else 0.0,
                "entry_open": entry,
                "exit_open": exit_price,
                "interval_high": max(entry, exit_price) + 1.0,
                "interval_low": min(entry, exit_price) - 1.0,
                "known_high24": 150.0,
                "known_low24": 50.0,
                "target_log_return": math.log(exit_price / entry),
                **{name: 0.0 for name in run.FEATURE_COLUMNS},
            })
    return pd.DataFrame(output)


def _block_all_starts_at(timestamp: pd.Timestamp) -> set[str]:
    return {
        f"{timestamp.isoformat()}|{symbol}|{direction:+d}"
        for symbol in run.SYMBOLS
        for direction in (-1, 1)
    }


def test_fixed_quantity_linear_pnl_long_and_short_two_steps():
    long_rows = _sequence_rows(1, [(100.0, 90.0), (90.0, 80.0), (80.0, 80.0)], -0.10)
    long_path = run.replay(long_rows, funding_fixture(), run.PathConfig(0.0), _block_all_starts_at(pd.Timestamp("2023-01-01T02:00:00Z")))
    assert math.isclose(long_path.final_nav, 8000.0, rel_tol=0, abs_tol=1e-8)

    short_rows = _sequence_rows(-1, [(100.0, 90.0), (90.0, 80.0), (80.0, 80.0)], 0.10)
    short_path = run.replay(short_rows, funding_fixture(), run.PathConfig(0.0), _block_all_starts_at(pd.Timestamp("2023-01-01T02:00:00Z")))
    assert math.isclose(short_path.final_nav, 12000.0, rel_tol=0, abs_tol=1e-8)


def test_gap_through_trailed_stop_fills_at_adverse_open():
    rows = _sequence_rows(1, [(100.0, 90.0), (90.0, 100.0), (100.0, 100.0)], -0.10)
    # The second decision trails the stop to 95 while the executable next open is already 90.
    mask = (rows["decision_time"] == pd.Timestamp("2023-01-01T01:00:00Z")) & (rows["symbol"] == "BTCUSDT")
    rows.loc[mask, "known_low24"] = 95.0
    path = run.replay(rows, funding_fixture(), run.PathConfig(0.0), _block_all_starts_at(pd.Timestamp("2023-01-01T02:00:00Z")))
    assert math.isclose(path.final_nav, 9000.0, rel_tol=0, abs_tol=1e-8)
    assert path.structural_stop_count == 1
    assert path.trade_records[0]["reason"] == "STRUCTURAL_STOP"


def test_partition_requires_complete_label_interval_inside_boundary():
    boundary = run.TRAIN_END
    rows = pd.DataFrame({
        "decision_time": [boundary - pd.Timedelta(hours=1), boundary - pd.Timedelta(hours=3)],
        "entry_time": [boundary, boundary - pd.Timedelta(hours=2)],
        "exit_time": [boundary + pd.Timedelta(hours=1), boundary - pd.Timedelta(hours=1)],
    })
    selected = run.partition_rows(rows, run.START, boundary)
    assert len(selected) == 1
    assert selected.iloc[0]["exit_time"] < boundary
