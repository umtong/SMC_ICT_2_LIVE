from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd

import cross_venue_pilot as v1
import cross_venue_pilot_v2 as v2


def synthetic_frame() -> pd.DataFrame:
    index = np.arange(0, 120_000, v1.BUCKET_MS, dtype=np.int64)
    frame = pd.DataFrame(index=index)
    for prefix in ("bn", "bb"):
        frame[f"{prefix}_bid"] = 99.9
        frame[f"{prefix}_ask"] = 100.1
        frame[f"{prefix}_bid_amount"] = 100.0
        frame[f"{prefix}_ask_amount"] = 100.0
        frame[f"{prefix}_quote_event_ms"] = index + 99
        frame[f"{prefix}_quote_actual"] = True
        frame[f"{prefix}_mid"] = 100.0
        frame[f"{prefix}_spread"] = 0.2
        frame[f"{prefix}_trade_notional"] = 0.0
        frame[f"{prefix}_signed_notional"] = 0.0
        frame[f"{prefix}_trade_count"] = 0.0
        frame[f"{prefix}_quote_imbalance"] = 0.0
    frame.loc[70_000:70_900, "bb_mid"] = np.linspace(100, 101, 10)
    frame.loc[70_000:70_900, "bb_bid"] = frame.loc[70_000:70_900, "bb_mid"] - 0.1
    frame.loc[70_000:70_900, "bb_ask"] = frame.loc[70_000:70_900, "bb_mid"] + 0.1
    frame.loc[70_000:70_900, "bb_trade_notional"] = 1000.0
    frame.loc[70_000:70_900, "bb_signed_notional"] = 900.0
    return frame


def test_completed_bucket_and_latency() -> None:
    v2.patch_v1()
    frame = synthetic_frame()
    config = v1.Config("bybit_to_binance_propagation", 1000, 4.0, 0.60, 0.50, 500, 3000, 4.0, 2.0)
    events = v2.signal_events_v2(frame, config, "synthetic", "BTCUSDT")
    assert events
    assert all(event.decision_ms % v1.BUCKET_MS == 0 for event in events)
    trades = v2.simulate_v2(frame, events, config, 0.0)
    assert all(item.entry_ms >= item.decision_ms + config.latency_ms for item in trades)


def test_future_mutation_does_not_change_prior_events() -> None:
    v2.patch_v1()
    frame = synthetic_frame()
    config = v1.Config("bybit_to_binance_propagation", 1000, 4.0, 0.60, 0.50, 500, 3000, 4.0, 2.0)
    changed = frame.copy()
    changed.loc[90_000:, ["bb_mid", "bb_bid", "bb_ask"]] *= 2.0
    a = [(e.decision_ms, e.side) for e in v2.signal_events_v2(frame, config, "d", "BTCUSDT") if e.decision_ms < 90_000]
    b = [(e.decision_ms, e.side) for e in v2.signal_events_v2(changed, config, "d", "BTCUSDT") if e.decision_ms < 90_000]
    assert a == b


def test_local_arrival_controls_bucket_even_when_exchange_time_reorders(tmp_path: Path) -> None:
    # Real normalized files use microsecond epoch values. Exchange timestamps may
    # arrive out of order while local timestamps remain monotonic.
    raw = (
        "exchange,symbol,timestamp,local_timestamp,id,side,price,amount\n"
        "bybit,BTCUSDT,1700000000200000,1700000000300000,1,buy,100,1\n"
        "bybit,BTCUSDT,1700000000100000,1700000000400000,2,sell,100,1\n"
    )
    path = tmp_path / "trades.csv.gz"
    path.write_bytes(gzip.compress(raw.encode()))
    frame = v2.read_trades_v2(path)
    assert list(frame.index) == [1_700_000_000_300, 1_700_000_000_400]
    assert v2.LATENCY_DIAGNOSTICS[-1]["local_timestamp_monotonic"] is True
    assert v2.LATENCY_DIAGNOSTICS[-1]["exchange_timestamp_monotonic"] is False


def test_chronological_order_precedes_score() -> None:
    events = [
        v1.Event("d", "BTCUSDT", "f", 2000, 1, 100.0, 1.0),
        v1.Event("d", "BTCUSDT", "f", 1000, 1, 1.0, 1.0),
    ]
    ordered = sorted(events, key=lambda item: (item.decision_ms, -item.score, item.symbol, item.family))
    assert [item.decision_ms for item in ordered] == [1000, 2000]
