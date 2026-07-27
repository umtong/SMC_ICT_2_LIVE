from __future__ import annotations

import json

import pandas as pd

from scripts.market_data import build_canonical_bybit as builder
from scripts.market_data import load_canonical_bybit as loader


def test_canonicalize_grid_keeps_missing_rows_explicit() -> None:
    frame = pd.DataFrame({
        "start_time_ms": [0, 120_000],
        "open": [1.0, 3.0], "high": [2.0, 4.0], "low": [0.5, 2.5],
        "close": [1.5, 3.5], "volume": [10.0, 30.0], "turnover": [15.0, 105.0],
    })
    grid, stats = builder.canonicalize_grid(
        frame, timestamp_col="start_time_ms", start_ms=0,
        end_exclusive_ms=180_000, step_ms=60_000, available_delay_ms=60_000,
    )
    assert len(grid) == 3
    assert grid["observed"].tolist() == [True, False, True]
    assert stats["observed_rows"] == 2 and stats["missing_rows"] == 1
    assert grid["available_at_ms"].tolist() == [60_000, 120_000, 180_000]


def test_derived_bar_invalidates_incomplete_window() -> None:
    frame = pd.DataFrame({
        "start_time_ms": [0, 60_000, 120_000, 180_000, 240_000],
        "open": [1.0, 2.0, float("nan"), 4.0, 5.0],
        "high": [2.0, 3.0, float("nan"), 5.0, 6.0],
        "low": [0.5, 1.5, float("nan"), 3.5, 4.5],
        "close": [1.5, 2.5, float("nan"), 4.5, 5.5],
        "volume": [10.0, 20.0, float("nan"), 40.0, 50.0],
        "turnover": [15.0, 50.0, float("nan"), 180.0, 275.0],
        "observed": [True, True, False, True, True],
    })
    out = builder.derive_trade_bars(frame, "5min")
    assert len(out) == 1
    assert not bool(out.loc[0, "is_complete"])
    assert pd.isna(out.loc[0, "close"])
    assert int(out.loc[0, "available_at_ms"]) == 300_000


def test_supported_segments_begin_in_2021() -> None:
    assert "PRE_2024_2021" in builder.SEGMENTS
    assert "PRE_2024_2022" in builder.SEGMENTS
    assert "PRE_2024_2023" in builder.SEGMENTS
    assert all("2020" not in name for name in builder.SEGMENTS)


def test_evaluation_half_years_form_one_continuous_path() -> None:
    names = ["2024_H1", "2024_H2", "2025_H1", "2025_H2", "2026_H1"]
    bounds = [(builder.utc_ms(builder.SEGMENTS[n][0]), builder.utc_ms(builder.SEGMENTS[n][1])) for n in names]
    for (_, left_end), (right_start, _) in zip(bounds, bounds[1:]):
        assert left_end == right_start


class FakeCursorClient:
    def get(self, path, params):
        cursor = params.get("cursor")
        if cursor is None:
            page = [
                {"timestamp": "600000", "openInterest": "3"},
                {"timestamp": "300000", "openInterest": "2"},
            ]
            next_cursor = "page2"
        else:
            page = [{"timestamp": "0", "openInterest": "1"}]
            next_cursor = ""
        payload = {"retCode": 0, "result": {"list": page, "nextPageCursor": next_cursor}}
        return payload, json.dumps(payload, sort_keys=True).encode()


def test_cursor_series_uses_provider_cursor() -> None:
    frame, audits = builder.fetch_cursor_series(
        FakeCursorClient(), symbol="BTCUSDT", stream="open_interest_5m",
        path="/v5/market/open-interest", interval_param=("intervalTime", "5min"),
        start_ms=0, end_exclusive_ms=900_000,
    )
    assert frame["timestamp_ms"].tolist() == [0, 300_000, 600_000]
    assert len(audits) == 2


def test_visible_rows_enforces_declared_availability() -> None:
    frame = pd.DataFrame({
        "start_time_ms": [0, 60_000],
        "available_at_ms": [60_000, 120_000],
    })
    visible = loader.visible_rows(frame, 60_000)
    assert visible["start_time_ms"].tolist() == [0]
