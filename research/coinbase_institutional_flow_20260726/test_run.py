from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import run


def test_timestamp_normalization() -> None:
    assert run.normalize_timestamp_us("2022-01-01T00:00:00Z") == 1640995200000000
    assert run.normalize_timestamp_us(1640995200000) == 1640995200000000


def test_dataset_path_uses_durable_exchanges() -> None:
    assert run.dataset_url("coinbase", "trades", "2022-01-01", "BTCUSD").endswith("/coinbase/trades/2022/01/01/BTCUSD.csv.gz")
    assert run.dataset_url("bybit", "quotes", "2022-01-01", "BTCUSDT").endswith("/bybit/quotes/2022/01/01/BTCUSDT.csv.gz")


def test_stop_first() -> None:
    dummy = object.__new__(run.BybitDay)
    dummy.ts = np.asarray([1, 2], dtype=np.int64)
    dummy.bid = np.asarray([99.0, 102.0])
    dummy.ask = np.asarray([101.0, 103.0])
    index, _, reason = run.BybitDay.scan(dummy, 0, 1, 102.0, 99.0)
    assert index == 0
    assert reason == "STOP"


def test_single_global_slot() -> None:
    events = []
    for index, (entry, exit_ts, gross) in enumerate(((100, 200, 50.0), (150, 180, 100.0), (250, 300, -20.0))):
        path = run.EventPath(2, entry, exit_ts, 100.0, 100.5, gross, 20.0, 40.0, "TARGET" if gross > 0 else "STOP", 10_000_000.0, 0.0)
        event = run.Event(str(index), "2022-01-01", "BTC", "BTCUSD", "BTCUSDT", entry - 10, entry, 1, int(gross > 0), {name: 1.0 for name in run.FULL_FEATURES}, {name: 1.0 for name in run.BASELINE_FEATURES}, {2: path, 5: path}, 0.9, 0.5, True)
        events.append(event)
    _, trades = run.replay(events, 2, 12.0)
    assert [trade.event_id for trade in trades] == ["0", "2"]


def test_preregistration_is_minimal() -> None:
    contract = json.loads((Path(__file__).resolve().parent / "preregistration.json").read_text())
    assert contract["model"]["single_model_only"] is True
    assert contract["model"]["model_grid"] is False
    assert contract["model"]["feature_grid"] is False
    assert contract["model"]["threshold_grid"] is False
    assert contract["event"]["elapsed_time_exit"] is False
    assert contract["account"]["global_slot_count"] == 1
    assert contract["sources"]["bitmex_prohibited"] is True
    assert contract["chronology"]["prohibited_years"] == [2023, 2024, 2025, 2026]


def test_exact_funding_direction() -> None:
    dummy = object.__new__(run.BybitDay)
    dummy.funding_ts = np.asarray([100, 200, 300], dtype=np.int64)
    dummy.funding_rate = np.asarray([0.0001, -0.0002, 0.0003], dtype=np.float64)
    assert abs(run.BybitDay.funding_cost_bps(dummy, 50, 250, 1) - (-1.0)) < 1e-12
    assert abs(run.BybitDay.funding_cost_bps(dummy, 50, 250, -1) - 1.0) < 1e-12
