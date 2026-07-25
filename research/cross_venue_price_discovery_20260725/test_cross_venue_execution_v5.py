from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd

import cross_venue_pilot as v1
import cross_venue_pilot_v2 as v2
import cross_venue_execution_v5 as v5


def _write_quotes(path: Path, rows: list[str]) -> None:
    header = "exchange,symbol,timestamp,local_timestamp,ask_price,ask_amount,bid_price,bid_amount\n"
    path.write_bytes(gzip.compress((header + "".join(rows)).encode()))


def _frame(symbol: str, delayed_until_ms: int | None = None) -> pd.DataFrame:
    del symbol
    index = np.arange(0, 100_000, v1.BUCKET_MS, dtype=np.int64)
    frame = pd.DataFrame(index=index)
    frame["bn_mid"] = 100.0
    frame["bb_mid"] = 100.0
    first_us = index * 1_000 + 10_000
    frame["bn_first_event_us"] = first_us.astype(float)
    frame["bn_first_event_ms"] = (first_us // 1_000).astype(float)
    fields = {
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
    }
    for name, value in fields.items():
        frame[name] = value
    if delayed_until_ms is not None:
        mask = (frame.index >= 60_100) & (frame.index < delayed_until_ms)
        frame.loc[mask, [name for name in frame.columns if name.startswith("bn_first_")]] = np.nan
    return frame


def _config(latency_ms: int = 100, hold_ms: int = 3_000) -> v1.Config:
    return v1.Config(
        "bybit_to_binance_propagation",
        1_000,
        4.0,
        0.60,
        0.50,
        latency_ms,
        hold_ms,
        100.0,
        2.0,
    )


def test_microsecond_first_quote_is_retained_and_legacy_used_bucket_last(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv.gz"
    _write_quotes(path, [
        "binance-futures,BTCUSDT,1700000000000000,1700000000000010,100.1,10,99.9,10\n",
        "binance-futures,BTCUSDT,1700000000000050,1700000000000090,100.3,9,100.1,9\n",
    ])
    corrected = v5.read_quotes_v5(path)
    legacy = v2.read_quotes_v2(path)
    assert int(corrected.iloc[0].first_event_us) == 1_700_000_000_000_010
    assert int(corrected.iloc[0].quote_event_us) == 1_700_000_000_000_090
    assert float(corrected.iloc[0].first_ask) == 100.1
    assert float(corrected.iloc[0].ask) == 100.3
    assert int(legacy.iloc[0].quote_event_ms) == 1_700_000_000_000


def test_identical_local_timestamp_is_resolved_adversely_not_by_file_order(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.csv.gz"
    _write_quotes(path, [
        "binance-futures,BTCUSDT,1700000000000000,1700000000000010,100.1,10,99.9,10\n",
        "binance-futures,BTCUSDT,1700000000000001,1700000000000010,100.4,2,99.6,3\n",
    ])
    corrected = v5.read_quotes_v5(path).iloc[0]
    assert int(corrected.ambiguous_group_count) == 1
    assert float(corrected.first_bid) == 99.6
    assert float(corrected.first_ask) == 100.4
    assert pd.isna(corrected.bid) and pd.isna(corrected.ask)


def test_global_slot_is_awarded_by_actual_entry_time_not_decision_time() -> None:
    day = "synthetic"
    frames = {
        (day, "A"): _frame("A", delayed_until_ms=61_000),
        (day, "B"): _frame("B"),
    }
    events = [
        v1.Event(day, "A", "f", 60_000, 1, 10.0, 0.0),
        v1.Event(day, "B", "f", 60_500, 1, 1.0, 0.0),
    ]
    trades = v5.simulate_fixed_day_v5(frames, events, _config())
    assert len(trades) == 1
    assert trades[0].symbol == "B"
    assert trades[0].entry_us == 60_610_000


def test_horizon_rounds_forward_and_applies_exit_latency() -> None:
    day = "synthetic"
    frame = _frame("A")
    event = v1.Event(day, "A", "f", 60_000, 1, 1.0, 0.0)
    trade = v5.simulate_fixed_day_v5({(day, "A"): frame}, [event], _config(latency_ms=500))[0]
    assert trade.entry_us == 60_510_000
    assert trade.trigger_boundary_us == 63_600_000
    assert trade.exit_us == 64_110_000
    assert trade.exit_us >= trade.trigger_boundary_us + 500_000


def test_future_mutation_after_exit_does_not_change_trade() -> None:
    day = "synthetic"
    event = v1.Event(day, "A", "f", 60_000, 1, 1.0, 0.0)
    frame = _frame("A")
    original = v5.simulate_fixed_day_v5({(day, "A"): frame}, [event], _config())[0]
    changed = frame.copy()
    changed.loc[changed.index > original.exit_ms + 1_000, [
        "bn_mid", "bb_mid", "bn_low_bid", "bn_high_ask",
    ]] *= 2.0
    replay = v5.simulate_fixed_day_v5({(day, "A"): changed}, [event], _config())[0]
    assert (
        original.entry_us,
        original.exit_us,
        original.entry_price,
        original.exit_price,
        original.exit_reason,
    ) == (
        replay.entry_us,
        replay.exit_us,
        replay.entry_price,
        replay.exit_price,
        replay.exit_reason,
    )


def test_entry_capacity_is_fail_closed() -> None:
    day = "synthetic"
    frame = _frame("A")
    frame.loc[:, ["bn_first_ask_amount", "bn_first_bid_amount"]] = 0.01
    event = v1.Event(day, "A", "f", 60_000, 1, 1.0, 0.0)
    assert v5.simulate_fixed_day_v5({(day, "A"): frame}, [event], _config()) == []
