from __future__ import annotations

import numpy as np
import pandas as pd

import run


def test_partition_boundaries() -> None:
    assert run.partition_of(pd.Timestamp("2021-07-01T00:00:00Z")) == "fit"
    assert run.partition_of(pd.Timestamp("2022-07-01T00:00:00Z")) == "calibration"
    assert run.partition_of(pd.Timestamp("2023-01-01T00:00:00Z")) == "confirmation"
    assert run.partition_of(pd.Timestamp("2023-07-01T00:00:00Z")) == "development"
    assert run.partition_of(pd.Timestamp("2024-01-01T00:00:00Z")) is None


def test_event_action_uses_fixed_cost_and_can_flatten() -> None:
    frame = pd.DataFrame({
        "event_id": ["long", "flat"],
        "upper_distance": [0.05, 0.001],
        "lower_distance": [0.02, 0.001],
    })
    acted = run.event_actions(frame, np.array([0.90, 0.50]))
    assert int(acted.loc[0, "side"]) == 1
    assert int(acted.loc[1, "side"]) == 0


def test_same_bar_is_stop_first() -> None:
    bars = pd.DataFrame({
        "timestamp": pd.date_range("2023-07-01", periods=2, freq="5min", tz="UTC"),
        "open": [100.0, 100.0],
        "high": [100.0, 106.0],
        "low": [100.0, 94.0],
        "close": [100.0, 100.0],
        "volume": [1.0, 1.0],
        "segment": [0, 0],
    })
    row = pd.Series({"side": 1, "lower_price": 95.0, "upper_price": 105.0, "entry_index": 0})
    _, price, reason = run.trade_outcome(row, bars, pd.Timestamp("2023-07-02", tz="UTC"))
    assert price == 95.0
    assert reason == "stop"


def test_funding_boundaries_are_strictly_after_entry() -> None:
    assert run.next_funding_boundaries(pd.Timestamp("2023-01-01T08:00:00Z"), pd.Timestamp("2023-01-01T15:59:59Z")) == 0
    assert run.next_funding_boundaries(pd.Timestamp("2023-01-01T07:59:59Z"), pd.Timestamp("2023-01-01T08:00:00Z")) == 1


def test_price_orientation_uses_fit_only() -> None:
    timestamps = pd.date_range("2021-07-01", periods=20_000, freq="5min", tz="UTC")
    eth = np.exp(np.linspace(np.log(2_000), np.log(2_400), len(timestamps)))
    uni = pd.DataFrame({
        "timestamp": timestamps,
        "price_first": 1.0 / eth,
        "price_last": 1.0 / eth,
        "usdc_increment": np.ones(len(timestamps)),
        "weth_increment": np.ones(len(timestamps)),
        "transaction_increment": np.ones(len(timestamps)),
        "block_first": np.arange(len(timestamps)),
        "block_last": np.arange(len(timestamps)),
        "source_rows": np.ones(len(timestamps)),
    })
    bars = pd.DataFrame({"timestamp": timestamps, "close": eth})
    normalized, meta = run.normalize_pool_price(uni, bars)
    assert meta["inverse"] is True
    ratio = normalized["price_last_normalized"].to_numpy() / eth
    assert np.nanmedian(np.abs(np.log(ratio))) < 1e-10


def test_source_boundary_is_punitive_structural_loss() -> None:
    bars = pd.DataFrame({
        "timestamp": pd.date_range("2023-07-01", periods=3, freq="5min", tz="UTC"),
        "open": [100.0, 100.0, 100.0],
        "high": [101.0, 101.0, 101.0],
        "low": [99.0, 99.0, 99.0],
        "close": [100.0, 100.0, 100.0],
        "volume": [1.0, 1.0, 1.0],
        "segment": [0, 0, 0],
    })
    row = pd.Series({"side": -1, "lower_price": 95.0, "upper_price": 105.0, "entry_index": 0})
    _, price, reason = run.trade_outcome(row, bars, pd.Timestamp("2023-07-01T00:15:00Z"))
    assert price == 105.0
    assert reason == "source_boundary_structural_loss"
