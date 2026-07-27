from __future__ import annotations

import gzip

import pandas as pd
import pytest

from scripts.market_data import build_public_trade_compact_robust as robust
from scripts.market_data import build_public_trade_month as original


def write_trade_gzip(path, rows: list[str]) -> None:
    header = (
        "timestamp,symbol,side,size,price,tickDirection,trdMatchID,"
        "grossValue,homeNotional,foreignNotional\n"
    )
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write(header)
        for row in rows:
            handle.write(row + "\n")


def test_unsorted_rows_and_cross_chunk_overlap_are_reconstructed(tmp_path) -> None:
    path = tmp_path / "unsorted.csv.gz"
    write_trade_gzip(path, [
        "0.400000,BTCUSDT,Buy,1,11,PlusTick,a,0,0,0",
        "0.100000,BTCUSDT,Buy,2,10,PlusTick,b,0,0,0",
        "0.300000,BTCUSDT,Sell,3,9,MinusTick,c,0,0,0",
        "0.200000,BTCUSDT,Sell,4,12,PlusTick,d,0,0,0",
        "0.500000,BTCUSDT,Buy,5,8,MinusTick,e,0,0,0",
    ])
    frame, rows = robust.aggregate_trade_file_robust(path, chunksize=2)
    assert rows == 5
    assert frame["start_time_ms"].tolist() == [0, 500]
    first = frame.iloc[0]
    assert first["open"] == 10
    assert first["high"] == 12
    assert first["low"] == 9
    assert first["close"] == 11
    assert first["first_offset_ms"] == 100
    assert first["high_offset_ms"] == 200
    assert first["low_offset_ms"] == 300
    assert first["last_offset_ms"] == 400
    assert first["volume"] == pytest.approx(10)
    assert first["buy_volume"] == pytest.approx(3)
    assert first["sell_volume"] == pytest.approx(7)
    assert frame.attrs["source_timestamp_regressions"] == 2


def test_equal_exchange_timestamp_uses_original_file_row_order(tmp_path) -> None:
    path = tmp_path / "ties.csv.gz"
    write_trade_gzip(path, [
        "0.250000,BTCUSDT,Buy,1,10,PlusTick,a,0,0,0",
        "0.250000,BTCUSDT,Buy,1,12,PlusTick,b,0,0,0",
        "0.250000,BTCUSDT,Sell,1,9,MinusTick,c,0,0,0",
    ])
    frame, _ = robust.aggregate_trade_file_robust(path, chunksize=1)
    row = frame.iloc[0]
    assert row["open"] == 10
    assert row["close"] == 9
    assert row["high"] == 12
    assert row["low"] == 9
    assert row["first_offset_ms"] == 250
    assert row["last_offset_ms"] == 250


def test_sorted_input_matches_original_aggregator(tmp_path) -> None:
    path = tmp_path / "sorted.csv.gz"
    write_trade_gzip(path, [
        "0.100000,BTCUSDT,Buy,2,10,PlusTick,a,0,0,0",
        "0.200000,BTCUSDT,Sell,1,12,MinusTick,b,0,0,0",
        "0.300000,BTCUSDT,Buy,3,9,MinusTick,c,0,0,0",
        "0.499000,BTCUSDT,Buy,1,11,PlusTick,d,0,0,0",
        "0.500000,BTCUSDT,Sell,4,8,MinusTick,e,0,0,0",
    ])
    expected, expected_rows = original.aggregate_trade_file(path, chunksize=2)
    actual, actual_rows = robust.aggregate_trade_file_robust(path, chunksize=2)
    assert actual_rows == expected_rows
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)
