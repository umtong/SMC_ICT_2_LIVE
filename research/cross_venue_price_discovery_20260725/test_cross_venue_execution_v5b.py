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
