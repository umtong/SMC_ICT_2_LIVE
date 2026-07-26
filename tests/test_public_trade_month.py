from __future__ import annotations

import gzip
from datetime import datetime, timezone

import pandas as pd
import pytest

from scripts.market_data import build_public_trade_month as monthly
from scripts.market_data import build_public_trade_segment as segment_builder


def write_trade_gzip(path, rows: list[str]) -> None:
    header = (
        "timestamp,symbol,side,size,price,tickDirection,trdMatchID,"
        "grossValue,homeNotional,foreignNotional\n"
    )
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write(header)
        for row in rows:
            handle.write(row + "\n")


def test_aggregate_trade_file_reconciles_flow_across_chunks(tmp_path) -> None:
    path = tmp_path / "sample.csv.gz"
    write_trade_gzip(path, [
        "0.1000,BTCUSDT,Buy,2,10,PlusTick,a,0,0,0",
        "30.0000,BTCUSDT,Sell,1,12,MinusTick,b,0,0,0",
        "59.9999,BTCUSDT,Buy,3,11,PlusTick,c,0,0,0",
        "60.0000,BTCUSDT,Sell,4,9,MinusTick,d,0,0,0",
        "90.0000,BTCUSDT,Buy,5,10,PlusTick,e,0,0,0",
    ])
    rows, total = monthly.aggregate_trade_file(path, chunksize=2)

    assert total == 5
    assert sorted(rows) == [0, 60_000]
    first = rows[0]
    assert first.open == 10
    assert first.high == 12
    assert first.low == 10
    assert first.close == 11
    assert first.volume == pytest.approx(6)
    assert first.turnover == pytest.approx(65)
    assert first.trade_count == 3
    assert first.buy_volume == pytest.approx(5)
    assert first.sell_volume == pytest.approx(1)
    assert first.buy_turnover == pytest.approx(53)
    assert first.sell_turnover == pytest.approx(12)

    second = rows[60_000]
    assert second.open == 9
    assert second.close == 10
    assert second.volume == pytest.approx(9)
    assert second.buy_volume == pytest.approx(5)
    assert second.sell_volume == pytest.approx(4)


def test_month_grid_preserves_missing_minutes_and_availability() -> None:
    accumulator = monthly.MinuteAccumulator(
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=3.0,
        turnover=4.5,
        trade_count=2,
        buy_volume=2.0,
        sell_volume=1.0,
        buy_turnover=3.0,
        sell_turnover=1.5,
    )
    start = datetime(2024, 2, 1, tzinfo=timezone.utc)
    end = datetime(2024, 2, 1, 0, 3, tzinfo=timezone.utc)
    frame = monthly.to_month_frame({int(start.timestamp() * 1000): accumulator}, start, end)

    assert len(frame) == 3
    assert frame["observed"].tolist() == [True, False, False]
    assert frame["available_at_ms"].tolist() == [
        int(start.timestamp() * 1000) + 60_000,
        int(start.timestamp() * 1000) + 120_000,
        int(start.timestamp() * 1000) + 180_000,
    ]


def test_derived_flow_bar_is_invalidated_by_one_missing_minute() -> None:
    frame = pd.DataFrame({
        "start_time_ms": [0, 60_000, 120_000, 180_000, 240_000],
        "observed": [True, True, False, True, True],
        "open": [1.0, 2.0, float("nan"), 4.0, 5.0],
        "high": [2.0, 3.0, float("nan"), 5.0, 6.0],
        "low": [0.5, 1.5, float("nan"), 3.5, 4.5],
        "close": [1.5, 2.5, float("nan"), 4.5, 5.5],
        "volume": [1.0, 1.0, float("nan"), 1.0, 1.0],
        "turnover": [1.0, 1.0, float("nan"), 1.0, 1.0],
        "trade_count": [1.0, 1.0, float("nan"), 1.0, 1.0],
        "buy_volume": [1.0, 0.0, float("nan"), 1.0, 0.0],
        "sell_volume": [0.0, 1.0, float("nan"), 0.0, 1.0],
        "buy_turnover": [1.0, 0.0, float("nan"), 1.0, 0.0],
        "sell_turnover": [0.0, 1.0, float("nan"), 0.0, 1.0],
    })
    out = monthly.derive_complete_bars(frame, "5min")

    assert len(out) == 1
    assert not bool(out.loc[0, "is_complete"])
    assert int(out.loc[0, "source_rows_observed"]) == 4
    assert pd.isna(out.loc[0, "close"])
    assert pd.isna(out.loc[0, "buy_volume"])
    assert int(out.loc[0, "available_at_ms"]) == 300_000


def test_month_partition_mapping_is_continuous() -> None:
    assert monthly.logical_segment(datetime(2023, 12, 1, tzinfo=timezone.utc)) == "PRE_2024"
    assert monthly.logical_segment(datetime(2024, 1, 1, tzinfo=timezone.utc)) == "2024_H1"
    assert monthly.logical_segment(datetime(2024, 7, 1, tzinfo=timezone.utc)) == "2024_H2"
    assert monthly.logical_segment(datetime(2025, 1, 1, tzinfo=timezone.utc)) == "2025_H1"
    assert monthly.logical_segment(datetime(2025, 7, 1, tzinfo=timezone.utc)) == "2025_H2"
    assert monthly.logical_segment(datetime(2026, 1, 1, tzinfo=timezone.utc)) == "2026_H1"


def test_segment_month_enumeration_is_exact() -> None:
    assert segment_builder.months_between(
        "2024-01-01T00:00:00Z", "2024-07-01T00:00:00Z"
    ) == ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]
    assert segment_builder.months_between(
        "2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z"
    )[0] == "2020-01"
    assert segment_builder.months_between(
        "2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z"
    )[-1] == "2020-12"
