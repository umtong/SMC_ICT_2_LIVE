
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("intraday_run", ROOT / "run.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def minute_frame(periods: int = 60 * 24 * 20) -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=periods, freq="1min", tz="UTC")
    rng = np.random.default_rng(7)
    returns = rng.normal(0, 0.0002, periods)
    for start in range(1200, periods, 2500):
        returns[start : start + 20] += 0.001
        returns[start + 20 : start + 80] -= 0.0004
    close = 100 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    width = close * 0.0002
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + width,
            "low": np.minimum(open_, close) - width,
            "close": close,
            "volume": rng.lognormal(5, 0.5, periods),
        },
        index=index,
    )


def test_rejects_tick_and_queue_inputs() -> None:
    frame = minute_frame(100)
    frame["queue_ahead"] = 1.0
    with pytest.raises(ValueError, match="tick/queue"):
        MODULE.validate_minute_bars(frame)


def test_rejects_subminute_clock() -> None:
    frame = minute_frame(100)
    extra = frame.iloc[[5]].copy()
    extra.index = extra.index + pd.Timedelta(seconds=30)
    with pytest.raises(ValueError, match="sub-minute"):
        MODULE.validate_minute_bars(pd.concat([frame, extra]).sort_index())


def test_confirmed_swing_is_delayed_by_right_span() -> None:
    index = pd.date_range("2023-01-01", periods=7, freq="1h", tz="UTC")
    hourly = pd.DataFrame(
        {
            "open": [1, 2, 3, 5, 3, 2, 1],
            "high": [2, 3, 4, 10, 4, 3, 2],
            "low": [0, 1, 2, 3, 2, 1, 0],
            "close": [1, 2, 3, 5, 3, 2, 1],
            "volume": 1.0,
        },
        index=index,
    )
    swings = MODULE.confirmed_swings(hourly, left=2, right=2)
    assert pd.isna(swings.loc[index[4], "swing_high"])
    assert swings.loc[index[5], "swing_high"] == 10


def test_event_entry_waits_beyond_completed_decision() -> None:
    frame = minute_frame()
    events = MODULE.build_events(frame, "BTCUSDT", MODULE.Contract())
    assert not events.empty
    result = MODULE.simulate_plan(frame, events.iloc[0], "continue", MODULE.Contract())
    if result.get("entry_time") is not None:
        assert result["entry_time"] >= events.iloc[0]["decision_time"] + pd.Timedelta(minutes=1)


def test_model_features_have_no_future_outcome_columns() -> None:
    prohibited_tokens = ("gross", "exit", "reason", "resolved", "mfe", "mae")
    for feature in MODULE.FEATURE_COLUMNS:
        assert not any(token in feature.lower() for token in prohibited_tokens)
    contract = MODULE.Contract()
    assert contract.base_frequency == "1min"
    assert contract.fixed_latency_ms == 500
    assert not hasattr(contract, "maximum_holding_time")
