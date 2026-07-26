from __future__ import annotations

import gzip
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

from model_screen import (
    CandidateAction,
    SourceEvent,
    arbitrate_candidates,
    bybit_month_url,
    ceil_minute,
    load_source_events,
    parse_bybit_month,
    prior_event_features,
    replay,
    split_for_timestamp,
)


def test_bybit_archive_parser_and_envelope() -> None:
    payload = "\n".join([
        "1640995200,100,99,101,100.5,10",
        "1640995260,100.5,101,100,100.8,12",
    ]).encode()
    frame = parse_bybit_month(gzip.compress(payload), "BTCUSDT")
    assert len(frame) == 2
    assert frame.iloc[0].high == 101
    assert frame.iloc[0].low == 99
    assert frame.index[0] == pd.Timestamp("2022-01-01T00:00:00Z")


def test_source_events_reject_2024_stress_availability(tmp_path: Path) -> None:
    path = tmp_path / "EVENTS.jsonl"
    row = {
        "event_id": "x",
        "token": "USDT",
        "direction": "MINT",
        "amount_usd": 1_000_000,
        "block_timestamp": 1,
        "available_timestamp_12": int(pd.Timestamp("2023-12-31T23:50:00Z").timestamp()),
        "available_timestamp_64": int(pd.Timestamp("2024-01-01T00:01:00Z").timestamp()),
    }
    path.write_text(json.dumps(row) + "\n")
    try:
        load_source_events(path)
    except ValueError as exc:
        assert "enters 2024" in str(exc)
    else:
        raise AssertionError("2024 stress availability was accepted")


def test_contemporaneous_events_do_not_leak_into_prior_features() -> None:
    events = [
        SourceEvent("a", "USDT", "MINT", 100.0, 10, 100, 200),
        SourceEvent("b", "USDC", "MINT", 50.0, 20, 100, 210),
        SourceEvent("c", "USDT", "BURN", 25.0, 30, 3700, 3800),
    ]
    prior = prior_event_features(events)
    assert prior["a"] == (0.0, 0.0)
    assert prior["b"] == (0.0, 0.0)
    assert prior["c"][1] > 0


def test_global_slot_and_same_path_cost_replay() -> None:
    candidates = [
        CandidateAction("a", "BTCUSDT", 100, 1, 0.2, 0.7, 110.0, 90.0, 100.0, 200, 1, False, False, "confirmation"),
        CandidateAction("b", "ETHUSDT", 100, 1, 0.1, 0.7, 110.0, 90.0, 100.0, 150, 1, False, False, "confirmation"),
        CandidateAction("c", "BTCUSDT", 160, 1, 0.3, 0.7, 110.0, 90.0, 100.0, 180, 1, False, False, "confirmation"),
        CandidateAction("d", "BTCUSDT", 260, -1, 0.2, 0.3, 110.0, 90.0, 100.0, 300, 0, False, False, "confirmation"),
    ]
    selected = arbitrate_candidates(candidates)
    assert [item.event_id for item in selected] == ["a", "d"]
    start = pd.Timestamp("2022-07-01", tz="UTC")
    end = pd.Timestamp("2023-01-01", tz="UTC")
    trades12, path12 = replay(candidates, 12.0, start, end)
    trades24, path24 = replay(candidates, 24.0, start, end)
    assert [trade.event_id for trade in trades12] == [trade.event_id for trade in trades24]
    assert path12["total_return"] > path24["total_return"] > 0


def test_helpers_are_fixed() -> None:
    assert ceil_minute(61) == 120
    assert bybit_month_url("ETHUSDT", 2023, 2).endswith("ETHUSDT_1_2023-02-01_2023-02-28.csv.gz")
    assert split_for_timestamp(int(pd.Timestamp("2021-04-01T00:00:00Z").timestamp())) == "train"
    assert split_for_timestamp(int(pd.Timestamp("2022-05-01T00:00:00Z").timestamp())) == "calibration"
    assert split_for_timestamp(int(pd.Timestamp("2022-10-01T00:00:00Z").timestamp())) == "confirmation"
    assert split_for_timestamp(int(pd.Timestamp("2023-04-01T00:00:00Z").timestamp())) == "development"
