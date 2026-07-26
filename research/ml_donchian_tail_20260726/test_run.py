from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import run


def _market(index: pd.DatetimeIndex, prices: list[float], *, invalid_at: int | None = None) -> pd.DataFrame:
    close = np.asarray(prices, dtype=float)
    frame = pd.DataFrame(index=index)
    frame["open"] = close
    frame["high"] = close * 1.001
    frame["low"] = close * 0.999
    frame["close"] = close
    frame["volume"] = 1000.0
    frame["valid"] = True
    if invalid_at is not None:
        frame.iloc[invalid_at, frame.columns.get_loc("valid")] = False
        frame.iloc[invalid_at, :5] = np.nan
    return frame


def _event(
    *,
    key: str,
    symbol: str,
    side: int,
    index: pd.DatetimeIndex,
    entry_idx: int,
    exit_idx: int,
    entry: float,
    exit_: float,
    stop: float,
    score: float,
    reason: str = "channel_exit",
) -> run.Event:
    return run.Event(
        event_key=key,
        symbol=symbol,
        side=side,
        signal_idx=max(0, entry_idx - 1),
        entry_idx=entry_idx,
        exit_idx=exit_idx,
        signal_time=index[max(0, entry_idx - 1)],
        entry_time=index[entry_idx],
        exit_time=index[exit_idx],
        entry_price=entry,
        exit_price=exit_,
        stop_price=stop,
        exit_reason=reason,
        gross_return=side * (exit_ / entry - 1.0),
        score=score,
        stop_fraction=abs(entry - stop) / entry,
        funding_boundaries=0,
        target_r_24bp=1.0,
        features={name: 0.0 for name in run.FEATURE_COLUMNS},
    )


def test_prior_extreme_uses_completed_history_only() -> None:
    index = pd.date_range("2022-01-01", periods=6, freq="1h", tz="UTC")
    values = pd.Series([1.0, 2.0, 3.0, 100.0, 4.0, 5.0], index=index)
    valid = pd.Series(True, index=index)
    result = run.prior_extreme(values, valid, 3, "max")
    assert result.iloc[3] == 3.0
    changed = values.copy()
    changed.iloc[4:] = 10_000.0
    changed_result = run.prior_extreme(changed, valid, 3, "max")
    assert changed_result.iloc[3] == result.iloc[3]


def test_exit_path_resolves_stop_before_channel_exit() -> None:
    index = pd.date_range("2022-01-01", periods=3, freq="1h", tz="UTC")
    frame = _market(index, [100.0, 90.0, 89.0])
    frame.loc[index[0], "low"] = 94.0
    exit_low = pd.Series([96.0, 96.0, 96.0], index=index)
    exit_high = pd.Series([math.nan] * 3, index=index)
    idx, _time, price, reason = run.exit_path(frame, 0, 100.0, 1, 95.0, exit_low, exit_high)
    assert idx == 0
    assert price == 95.0
    assert reason == "stop"


def test_exit_path_treats_source_gap_as_structural_stop() -> None:
    index = pd.date_range("2022-01-01", periods=3, freq="1h", tz="UTC")
    frame = _market(index, [100.0, 101.0, 102.0], invalid_at=1)
    exit_low = pd.Series([90.0] * 3, index=index)
    exit_high = pd.Series([110.0] * 3, index=index)
    idx, time, price, reason = run.exit_path(frame, 0, 100.0, 1, 95.0, exit_low, exit_high)
    assert idx == 1
    assert time == index[1]
    assert price == 95.0
    assert reason == "source_gap_stop"


def test_ml_selector_uses_highest_positive_prediction_not_breakout_score() -> None:
    index = pd.date_range("2022-01-01", periods=5, freq="1h", tz="UTC")
    markets = {
        "BTCUSDT": _market(index, [100, 100, 102, 104, 104]),
        "ETHUSDT": _market(index, [100, 100, 103, 106, 106]),
        "SOLUSDT": _market(index, [100] * 5),
        "XRPUSDT": _market(index, [100] * 5),
    }
    btc = _event(key="btc", symbol="BTCUSDT", side=1, index=index, entry_idx=1, exit_idx=3, entry=100, exit_=104, stop=98, score=10.0)
    eth = _event(key="eth", symbol="ETHUSDT", side=1, index=index, entry_idx=1, exit_idx=3, entry=100, exit_=106, stop=98, score=1.0)
    path = run.simulate(markets, [btc, eth], {"btc": 0.1, "eth": 0.5}, index[0], index[-1] + pd.Timedelta(hours=1), run.PathConfig(0.005, 5.0, 24.0), "ml")
    assert path.trade_count == 1
    assert path.trade_records[0]["event_key"] == "eth"


def test_winner_removal_releases_global_slot_and_reroutes() -> None:
    index = pd.date_range("2022-01-01", periods=8, freq="1h", tz="UTC")
    markets = {
        "BTCUSDT": _market(index, [100, 100, 102, 104, 106, 106, 106, 106]),
        "ETHUSDT": _market(index, [100, 100, 100, 103, 103, 103, 103, 103]),
        "SOLUSDT": _market(index, [100] * 8),
        "XRPUSDT": _market(index, [100] * 8),
    }
    dominant = _event(key="dominant", symbol="BTCUSDT", side=1, index=index, entry_idx=1, exit_idx=5, entry=100, exit_=106, stop=98, score=2.0)
    blocked = _event(key="blocked", symbol="ETHUSDT", side=1, index=index, entry_idx=2, exit_idx=4, entry=100, exit_=103, stop=98, score=1.0)
    predictions = {"dominant": 0.6, "blocked": 0.4}
    config = run.PathConfig(0.005, 5.0, 12.0)
    base = run.simulate(markets, [dominant, blocked], predictions, index[0], index[-1] + pd.Timedelta(hours=1), config, "ml")
    assert [item["event_key"] for item in base.trade_records] == ["dominant"]
    rerouted, removed = run.winner_removed_path(markets, [dominant, blocked], predictions, index[0], index[-1] + pd.Timedelta(hours=1), config, "ml", base)
    assert removed == ["dominant"]
    assert [item["event_key"] for item in rerouted.trade_records] == ["blocked"]


def test_future_source_year_is_prohibited() -> None:
    assert run.month_url("BTCUSDT", 2024, 1).endswith("BTCUSDT_5_2024-01-01_2024-01-31.csv.gz")
    with pytest.raises(run.ResearchError):
        run.month_url("BTCUSDT", 2025, 1)
