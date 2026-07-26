from __future__ import annotations

import math

import numpy as np
import pandas as pd

import run


def synthetic_execution(start: str = "2024-01-01", hours: int = 240, drift: float = 0.001) -> pd.DataFrame:
    idx = pd.date_range(start, periods=hours, freq="1h", tz="UTC")
    price = 100.0 * np.exp(np.arange(hours) * drift)
    return pd.DataFrame(
        {"open": price, "high": price * 1.001, "low": price * 0.999, "close": price},
        index=idx,
    )


def synthetic_signal(hours: int = 500) -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2023-01-01", periods=hours, freq="1h", tz="UTC")
    output: dict[str, pd.DataFrame] = {}
    for i, symbol in enumerate(run.SYMBOLS):
        price = 100.0 * np.exp(np.arange(hours) * 0.0001 * (i + 1))
        quote = 1_000_000.0 + np.arange(hours) * 100.0
        output[symbol] = pd.DataFrame(
            {
                "open": price,
                "high": price * 1.001,
                "low": price * 0.999,
                "close": price,
                "quote_volume": quote,
                "taker_buy_quote": quote * (0.50 + 0.01 * i),
            },
            index=idx,
        )
    return output


def test_feature_prefix_invariance_and_next_open_target() -> None:
    signal = synthetic_signal()
    pool, cols = run.build_pool(signal)
    t = pd.Timestamp("2023-01-12T00:00:00Z")
    before = pool[(pool.index == t) & (pool["symbol"] == "XRPUSDT")].iloc[0]

    changed = {symbol: frame.copy() for symbol, frame in signal.items()}
    for frame in changed.values():
        future = frame.index > t
        frame.loc[future, ["open", "high", "low", "close"]] *= 5.0
    pool_changed, _ = run.build_pool(changed)
    after = pool_changed[(pool_changed.index == t) & (pool_changed["symbol"] == "XRPUSDT")].iloc[0]
    np.testing.assert_allclose(before[cols].astype(float), after[cols].astype(float), equal_nan=True)

    xrp = signal["XRPUSDT"]
    expected = math.log(xrp.loc[t + pd.Timedelta(hours=25), "open"] / xrp.loc[t + pd.Timedelta(hours=1), "open"])
    assert math.isclose(float(before["target24"]), expected, rel_tol=0, abs_tol=1e-14)


def test_no_elapsed_time_liquidation_and_terminal_nav_valuation() -> None:
    bybit = synthetic_execution(hours=120)
    start = bybit.index[0]
    end = bybit.index[-1] + pd.Timedelta(hours=1)
    decisions = pd.date_range(start - pd.Timedelta(hours=1), end - pd.Timedelta(hours=2), freq="1h")
    pred = pd.Series(0.02, index=decisions)
    threshold = pd.Series(0.001, index=decisions)
    result, trades, _ = run.replay(pred, threshold, bybit, pd.Series(dtype=float), start, end, cost_bps=24.0)
    assert result.terminal_position == 1
    assert result.completed_trades == 0
    assert trades.empty
    assert len(decisions) > 96
    assert result.ending_nav > 1.0


def test_cost_monotonicity() -> None:
    bybit = synthetic_execution(hours=96)
    start = bybit.index[0]
    end = bybit.index[-1] + pd.Timedelta(hours=1)
    decisions = pd.date_range(start - pd.Timedelta(hours=1), end - pd.Timedelta(hours=2), freq="1h")
    pred = pd.Series(0.02, index=decisions)
    threshold = pd.Series(0.001, index=decisions)
    low, _, _ = run.replay(pred, threshold, bybit, pd.Series(dtype=float), start, end, cost_bps=12.0)
    high, _, _ = run.replay(pred, threshold, bybit, pd.Series(dtype=float), start, end, cost_bps=96.0)
    assert high.ending_nav < low.ending_nav


def test_exact_event_exclusion_precedes_reroute() -> None:
    bybit = synthetic_execution(hours=120, drift=0.002)
    start = bybit.index[0]
    end = bybit.index[-1] + pd.Timedelta(hours=1)
    decisions = pd.date_range(start - pd.Timedelta(hours=1), end - pd.Timedelta(hours=2), freq="1h")
    pred = pd.Series(0.0, index=decisions)
    threshold = pd.Series(0.0001, index=decisions)
    for day in range(4):
        base = start.normalize() + pd.Timedelta(days=day)
        pred.loc[base + pd.Timedelta(hours=7)] = 0.02
        pred.loc[base + pd.Timedelta(hours=9)] = -0.02
        pred.loc[base + pd.Timedelta(hours=11)] = 0.02
        pred.loc[base + pd.Timedelta(hours=15)] = -0.001
    base_result, base_trades, _ = run.replay(pred, threshold, bybit, pd.Series(dtype=float), start, end, cost_bps=12.0)
    assert len(base_trades) >= 4
    removed_result, removed_trades, _, keys = run.winner_removed(
        pred, threshold, bybit, pd.Series(dtype=float), start, end, base_trades, cost_bps=12.0
    )
    assert keys
    assert set(keys).isdisjoint(set(removed_trades.get("start_key", [])))
    assert removed_result.completed_trades <= base_result.completed_trades


def test_actual_and_adverse_funding_sign() -> None:
    bybit = synthetic_execution(hours=48, drift=0.0)
    start = bybit.index[0]
    end = bybit.index[-1] + pd.Timedelta(hours=1)
    decisions = pd.date_range(start - pd.Timedelta(hours=1), end - pd.Timedelta(hours=2), freq="1h")
    threshold = pd.Series(0.0001, index=decisions)
    funding = pd.Series(0.001, index=pd.DatetimeIndex([start + pd.Timedelta(hours=8), start + pd.Timedelta(hours=16)]))

    long_pred = pd.Series(0.02, index=decisions)
    long_actual, _, _ = run.replay(long_pred, threshold, bybit, funding, start, end, cost_bps=12.0, adverse_unsigned_funding=False)
    long_adverse, _, _ = run.replay(long_pred, threshold, bybit, funding, start, end, cost_bps=12.0, adverse_unsigned_funding=True)
    assert math.isclose(long_actual.ending_nav, long_adverse.ending_nav, rel_tol=0, abs_tol=1e-12)

    short_pred = pd.Series(-0.02, index=decisions)
    short_actual, _, _ = run.replay(short_pred, threshold, bybit, funding, start, end, cost_bps=12.0, adverse_unsigned_funding=False)
    short_adverse, _, _ = run.replay(short_pred, threshold, bybit, funding, start, end, cost_bps=12.0, adverse_unsigned_funding=True)
    assert short_actual.ending_nav > short_adverse.ending_nav
