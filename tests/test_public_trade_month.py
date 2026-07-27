from __future__ import annotations

import gzip
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from scripts.market_data import build_public_trade_month as monthly
from scripts.market_data import build_public_trade_segment as segment_builder
from scripts.market_data import load_canonical_bybit as loader


def write_trade_gzip(path, rows: list[str]) -> None:
    header = (
        "timestamp,symbol,side,size,price,tickDirection,trdMatchID,"
        "grossValue,homeNotional,foreignNotional\n"
    )
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write(header)
        for row in rows:
            handle.write(row + "\n")


def test_month_range_rejects_earlier_years() -> None:
    with pytest.raises(ValueError):
        monthly.month_bounds("2020-12")
    assert monthly.month_bounds("2021-01")[0] == datetime(2021, 1, 1, tzinfo=timezone.utc)


def test_aggregate_trade_file_reconciles_500ms_flow_and_extreme_offsets(tmp_path) -> None:
    path = tmp_path / "sample.csv.gz"
    write_trade_gzip(path, [
        "0.1000,BTCUSDT,Buy,2,10,PlusTick,a,0,0,0",
        "0.2000,BTCUSDT,Sell,1,12,MinusTick,b,0,0,0",
        "0.3000,BTCUSDT,Buy,3,9,PlusTick,c,0,0,0",
        "0.4990,BTCUSDT,Buy,1,11,PlusTick,d,0,0,0",
        "0.5000,BTCUSDT,Sell,4,8,MinusTick,e,0,0,0",
        "0.9000,BTCUSDT,Buy,5,10,PlusTick,f,0,0,0",
    ])
    rows, total = monthly.aggregate_trade_file(path, chunksize=2)
    assert total == 6
    assert rows["start_time_ms"].tolist() == [0, 500]
    first = rows.iloc[0]
    assert first["open"] == 10
    assert first["high"] == 12
    assert first["low"] == 9
    assert first["close"] == 11
    assert first["first_offset_ms"] == 100
    assert first["high_offset_ms"] == 200
    assert first["low_offset_ms"] == 300
    assert first["last_offset_ms"] == 499
    assert first["volume"] == pytest.approx(7)
    assert first["buy_volume"] == pytest.approx(6)
    assert first["sell_volume"] == pytest.approx(1)


def test_one_second_row_contains_two_exact_half_seconds() -> None:
    half = pd.DataFrame({
        "start_time_ms": [0, 500],
        "open": [10.0, 8.0], "high": [12.0, 10.0], "low": [9.0, 8.0], "close": [11.0, 10.0],
        "volume": [7.0, 9.0], "turnover": [70.0, 86.0], "trade_count": [4, 2],
        "buy_volume": [6.0, 5.0], "sell_volume": [1.0, 4.0],
        "buy_turnover": [58.0, 50.0], "sell_turnover": [12.0, 36.0],
        "first_offset_ms": [100, 0], "high_offset_ms": [200, 400],
        "low_offset_ms": [300, 0], "last_offset_ms": [499, 400],
    })
    frame = monthly.build_one_second_day(half, date(1970, 1, 1), source_available=True)
    row = frame.iloc[0]
    assert row["observed"]
    assert row["open"] == 10
    assert row["high"] == 12
    assert row["low"] == 8
    assert row["close"] == 10
    assert row["trade_count"] == 6
    assert row["h0_available_at_ms"] == 500
    assert row["h1_available_at_ms"] == 1000
    assert row["available_at_ms"] == 1000

    halves = loader.to_500ms_bars(frame.iloc[:2])
    assert halves["start_time_ms"].tolist()[:4] == [0, 500, 1000, 1500]
    assert halves.iloc[0]["high_offset_ms"] == 200
    assert halves.iloc[1]["low_offset_ms"] == 0


def test_unavailable_day_is_distinct_from_no_trade_second() -> None:
    frame = monthly.build_one_second_day(pd.DataFrame(), date(2021, 1, 1), source_available=False)
    assert not frame["source_available"].any()
    assert not frame["observed"].any()
    assert (frame["trade_count"] == -1).all()
    assert frame["open"].isna().all()


def test_derived_five_second_bar_uses_exact_completed_grid() -> None:
    half = pd.DataFrame({
        "start_time_ms": [0, 500, 1_000],
        "open": [10.0, 11.0, 12.0], "high": [10.0, 11.0, 12.0],
        "low": [10.0, 11.0, 12.0], "close": [10.0, 11.0, 12.0],
        "volume": [1.0, 1.0, 1.0], "turnover": [10.0, 11.0, 12.0], "trade_count": [1, 1, 1],
        "buy_volume": [1.0, 0.0, 1.0], "sell_volume": [0.0, 1.0, 0.0],
        "buy_turnover": [10.0, 0.0, 12.0], "sell_turnover": [0.0, 11.0, 0.0],
        "first_offset_ms": [0, 0, 0], "high_offset_ms": [0, 0, 0],
        "low_offset_ms": [0, 0, 0], "last_offset_ms": [0, 0, 0],
    })
    one = monthly.build_one_second_day(half, date(1970, 1, 1), source_available=True)
    five = monthly.derive_seconds(one.iloc[:5], 5)
    assert len(five) == 1
    assert five.iloc[0]["open"] == 10
    assert five.iloc[0]["close"] == 12
    assert five.iloc[0]["trade_count"] == 3
    assert five.iloc[0]["available_at_ms"] == 5_000


def test_first_executable_trade_after_whole_second_decision() -> None:
    half = pd.DataFrame({
        "start_time_ms": [500, 1_000],
        "open": [101.0, 102.0], "high": [101.0, 102.0], "low": [101.0, 102.0], "close": [101.0, 102.0],
        "volume": [1.0, 1.0], "turnover": [101.0, 102.0], "trade_count": [1, 1],
        "buy_volume": [1.0, 0.0], "sell_volume": [0.0, 1.0],
        "buy_turnover": [101.0, 0.0], "sell_turnover": [0.0, 102.0],
        "first_offset_ms": [123, 10], "high_offset_ms": [123, 10],
        "low_offset_ms": [123, 10], "last_offset_ms": [123, 10],
    })
    one = monthly.build_one_second_day(half, date(1970, 1, 1), source_available=True)
    fill = loader.first_executable_trade_after_aligned_500ms(one.iloc[:3], 0)
    assert fill is not None
    assert fill["activation_time_ms"] == 500
    assert fill["trade_time_ms"] == 623
    assert fill["price"] == 101


def test_segment_month_enumeration_starts_at_2021() -> None:
    assert segment_builder.months_between(
        "2021-01-01T00:00:00Z", "2022-01-01T00:00:00Z"
    )[0] == "2021-01"
    assert segment_builder.months_between(
        "2024-01-01T00:00:00Z", "2024-07-01T00:00:00Z"
    ) == ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]
