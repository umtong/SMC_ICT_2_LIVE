from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import cross_venue_execution_v5c as v5c
import cross_venue_pilot as v1
import cross_venue_pilot_v5c as pilot_v5c


def frame() -> pd.DataFrame:
    index = np.arange(0, 100_000, v1.BUCKET_MS, dtype=np.int64)
    result = pd.DataFrame(index=index)
    result["bn_mid"] = 100.0
    result["bb_mid"] = 100.0
    first_us = index * 1_000 + 10_000
    result["bn_first_event_us"] = first_us.astype(float)
    result["bn_first_event_ms"] = (first_us // 1_000).astype(float)
    for name, value in {
        "bn_first_bid": 99.9,
        "bn_first_bid_amount": 1_000.0,
        "bn_first_bid_ask": 100.1,
        "bn_first_bid_ask_amount": 1_000.0,
        "bn_first_ask_bid": 99.9,
        "bn_first_ask_bid_amount": 1_000.0,
        "bn_first_ask": 100.1,
        "bn_first_ask_amount": 1_000.0,
        "bn_low_bid": 99.9,
        "bn_low_bid_amount": 1_000.0,
        "bn_low_bid_ask": 100.1,
        "bn_low_bid_ask_amount": 1_000.0,
        "bn_high_ask_bid": 99.9,
        "bn_high_ask_bid_amount": 1_000.0,
        "bn_high_ask": 100.1,
        "bn_high_ask_amount": 1_000.0,
    }.items():
        result[name] = value
    return result


def config(latency_ms: int = 100) -> v1.Config:
    return v1.Config(
        "bybit_to_binance_propagation",
        1_000,
        4.0,
        0.60,
        0.50,
        latency_ms,
        3_000,
        4.0,
        2.0,
    )


def event() -> v1.Event:
    return v1.Event("synthetic", "BTCUSDT", "f", 60_000, 1, 1.0, 0.0)


def test_stop_rebound_cannot_improve_exit_price() -> None:
    data = frame()
    # Entry is the first quote in bucket 60_100. That same completed bucket
    # subsequently breaches the stop at an executable bid of 90.
    data.loc[60_100, [
        "bn_low_bid", "bn_low_bid_amount", "bn_low_bid_ask", "bn_low_bid_ask_amount",
    ]] = [90.0, 1_000.0, 90.2, 1_000.0]
    # By the delayed exit bucket the market has rebounded far above entry.
    data.loc[60_300, [
        "bn_first_bid", "bn_first_bid_amount", "bn_first_bid_ask", "bn_first_bid_ask_amount",
        "bn_first_ask_bid", "bn_first_ask_bid_amount", "bn_first_ask", "bn_first_ask_amount",
    ]] = [104.9, 1_000.0, 105.1, 1_000.0, 104.9, 1_000.0, 105.1, 1_000.0]
    trade = v5c.simulate_fixed_day_v5(
        {("synthetic", "BTCUSDT"): data},
        [event()],
        config(),
    )[0]
    assert trade.exit_reason == "protective_stop"
    assert trade.exit_us == 60_310_000
    assert trade.exit_price <= 90.0
    assert trade.exit_price < trade.entry_price


def test_unaligned_latency_fails_closed() -> None:
    with pytest.raises(ValueError, match="latency"):
        v5c.simulate_fixed_day_v5(
            {("synthetic", "BTCUSDT"): frame()},
            [event()],
            config(latency_ms=150),
        )


def test_unaligned_decision_fails_closed() -> None:
    bad = v1.Event("synthetic", "BTCUSDT", "f", 60_050, 1, 1.0, 0.0)
    with pytest.raises(ValueError, match="decision"):
        v5c.simulate_fixed_day_v5(
            {("synthetic", "BTCUSDT"): frame()},
            [bad],
            config(),
        )


def fixed_trade(day: str, net_bps: float) -> v5c.FixedTradeV5:
    return v5c.FixedTradeV5(
        "cfg",
        day,
        "BTCUSDT",
        "f",
        0,
        100,
        200,
        100_000,
        200_000,
        1,
        100.0,
        100.1,
        net_bps,
        2.0,
        0.0,
        net_bps,
        "horizon",
        1.0,
        False,
        200_000,
    )


def test_pilot_day_fraction_includes_zero_trade_dates() -> None:
    days = tuple(v1.PILOT_DAYS)
    pilot_v5c.patch_metrics(days)
    metrics = pilot_v5c.metrics_all_preregistered_days([
        fixed_trade(days[0], 5.0),
        fixed_trade(days[0], 5.0),
    ])
    assert metrics["positive_day_fraction"] == 0.25
    assert metrics["median_trades_per_day"] == 0.0
    assert metrics["day_returns_bps"] == {
        days[0]: 10.0,
        days[1]: 0.0,
        days[2]: 0.0,
        days[3]: 0.0,
    }
