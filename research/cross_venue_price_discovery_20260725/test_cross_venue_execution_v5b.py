from __future__ import annotations

import numpy as np
import pandas as pd

import cross_venue_development_v2 as d2
import cross_venue_execution_v5b as v5b
import cross_venue_pilot as v1


def frame_around(start_ms: int, end_ms: int) -> pd.DataFrame:
    index = np.arange(start_ms, end_ms, v1.BUCKET_MS, dtype=np.int64)
    frame = pd.DataFrame(index=index)
    frame["bn_mid"] = 100.0
    frame["bb_mid"] = 100.0
    first_us = index * 1_000 + 10_000
    frame["bn_first_event_us"] = first_us.astype(float)
    frame["bn_first_event_ms"] = (first_us // 1_000).astype(float)
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
        frame[name] = value
    return frame


def config() -> v1.Config:
    return v1.Config(
        "bybit_to_binance_propagation",
        1_000,
        4.0,
        0.60,
        0.50,
        100,
        3_000,
        100.0,
        2.0,
    )


def account_trade(symbol: str, net: float, nav_before: float, nav_after: float) -> v5b.AccountTradeV5:
    return v5b.AccountTradeV5(
        "cfg",
        "2022-01-01",
        symbol,
        "f",
        0,
        1,
        2,
        1_000,
        2_000,
        1,
        100.0,
        100.0,
        99.0,
        1.0,
        100.0,
        1.0,
        net,
        0.0,
        net,
        net / nav_before,
        nav_before,
        nav_after,
        "horizon",
        1.0,
        False,
        0.0,
        2_000,
    )


def test_maximum_exit_path_crossing_funding_is_excluded() -> None:
    settlement = d2.FUNDING_INTERVAL_MS
    day = "synthetic"
    frame = frame_around(settlement - 20_000, settlement + 30_000)
    event = v1.Event(day, "BTCUSDT", "f", settlement - 1_000, 1, 1.0, 0.0)
    trades = v5b.simulate_fixed_day_v5({(day, "BTCUSDT"): frame}, [event], config())
    assert trades == []


def test_entry_after_settlement_remains_eligible() -> None:
    settlement = d2.FUNDING_INTERVAL_MS
    day = "synthetic"
    frame = frame_around(settlement - 20_000, settlement + 40_000)
    event = v1.Event(day, "BTCUSDT", "f", settlement + 1_000, 1, 1.0, 0.0)
    trades = v5b.simulate_fixed_day_v5({(day, "BTCUSDT"): frame}, [event], config())
    assert len(trades) == 1
    assert trades[0].entry_ms > settlement


def test_symbol_concentration_uses_net_symbol_profit_contract() -> None:
    trades = [
        account_trade("BTCUSDT", 10.0, 10_000.0, 10_010.0),
        account_trade("BTCUSDT", -9.0, 10_010.0, 10_001.0),
        account_trade("ETHUSDT", 5.0, 10_001.0, 10_006.0),
    ]
    metrics = v5b.account_metrics_v5(
        trades,
        {"nav": 10_006.0, "peak": 10_010.0, "maximum_drawdown": 9.0 / 10_010.0},
        ["2022-01-01"],
    )
    assert abs(metrics["maximum_single_symbol_positive_pnl_share"] - (5.0 / 6.0)) < 1e-12
    assert metrics["symbol_positive_pnl"] == {"BTCUSDT": 1.0, "ETHUSDT": 5.0}
