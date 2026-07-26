from __future__ import annotations

import pandas as pd

from .engine import (
    ActiveSwingBook,
    Config,
    Market,
    Stage,
    confirmed_pivots,
    next_observable_minute,
    resolve_candidate,
    simulate,
)


def _one(rows):
    frame = pd.DataFrame(rows)
    frame.index = pd.to_datetime(frame.pop("timestamp"), utc=True)
    return frame


def _market(one: pd.DataFrame) -> Market:
    empty = pd.DataFrame()
    return Market(
        symbol="BTCUSDT",
        one=one,
        five=empty,
        fifteen=empty,
        one_hour=empty,
        four_hour=empty,
        funding=empty,
        funding_long_cum=pd.Series(0.0, index=one.index),
        source_manifest_sha256="x",
    )


def test_latency_uses_first_open_strictly_after_500ms() -> None:
    one = _one([
        {"timestamp": "2024-01-01T00:05:00Z", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "observed": True},
        {"timestamp": "2024-01-01T00:06:00Z", "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0, "observed": True},
    ])
    assert next_observable_minute(one, pd.Timestamp("2024-01-01T00:05:00Z"), 500) == pd.Timestamp("2024-01-01T00:06:00Z")


def test_same_minute_stop_wins_and_gap_stop_uses_open() -> None:
    one = _one([
        {"timestamp": "2024-01-01T00:06:00Z", "open": 100.0, "high": 110.0, "low": 90.0, "close": 102.0, "observed": True},
    ])
    result = resolve_candidate(_market(one), one.index[0], 95.0, 105.0, 1)
    assert result["resolution"] == "stop"
    assert result["exit_raw"] == 95.0
    gap = _one([
        {"timestamp": "2024-01-01T00:06:00Z", "open": 93.0, "high": 94.0, "low": 90.0, "close": 92.0, "observed": True},
    ])
    result = resolve_candidate(_market(gap), gap.index[0], 95.0, 105.0, 1)
    assert result["resolution"] == "stop"
    assert result["exit_raw"] == 93.0


def test_confirmed_pivot_not_available_until_right_bars_close() -> None:
    index = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    frame = pd.DataFrame({
        "high": [1, 2, 5, 2, 1],
        "low": [0, 0.5, 1, 0.5, 0],
        "available_at_ms": [(ts + pd.Timedelta(hours=1)).value // 1_000_000 for ts in index],
    }, index=index)
    pivots = confirmed_pivots(frame, "1h", 2, 2)
    high = pivots.loc[pivots.kind == "high"].iloc[0]
    assert high.price == 5
    assert high.confirm_ts == pd.Timestamp("2024-01-01T05:00:00Z")


def test_swing_book_consumes_known_level_before_target_selection() -> None:
    pivots = pd.DataFrame([
        {"confirm_ts": pd.Timestamp("2024-01-01T00:00:00Z"), "kind": "high", "price": 110.0, "timeframe_flag": 0.0},
        {"confirm_ts": pd.Timestamp("2024-01-01T00:00:00Z"), "kind": "low", "price": 90.0, "timeframe_flag": 1.0},
    ])
    book = ActiveSwingBook(pivots)
    book.consume_bar(pd.Timestamp("2024-01-01T00:00:00Z"), pd.Timestamp("2024-01-01T00:05:00Z"), 105.0, 95.0)
    assert book.nearest(1, 100.0) == (110.0, 0.0)
    book.consume_bar(pd.Timestamp("2024-01-01T00:05:00Z"), pd.Timestamp("2024-01-01T00:10:00Z"), 111.0, 95.0)
    assert book.nearest(1, 100.0) is None


def test_account_risk_budget_and_global_path_no_liquidation() -> None:
    one = _one([
        {"timestamp": "2024-01-01T00:01:00Z", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "observed": True},
        {"timestamp": "2024-01-01T00:02:00Z", "open": 120.0, "high": 120.0, "low": 120.0, "close": 120.0, "observed": True},
        {"timestamp": "2024-01-01T23:59:00Z", "open": 120.0, "high": 120.0, "low": 120.0, "close": 120.0, "observed": True},
    ])
    market = _market(one)
    sequence = pd.DataFrame([{
        "sequence_id": 0,
        "event_id": "e",
        "symbol": "BTCUSDT",
        "entry_ts": one.index[0],
        "exit_ts_full": one.index[1],
        "exit_raw_full": 120.0,
        "resolution": "target",
        "candidate_direction": 1,
        "is_continuation": 1,
        "probability": 0.8,
        "entry_raw": 100.0,
        "stop_raw": 90.0,
        "target_raw": 120.0,
    }])
    contract = {"sizing": {"maintenance_margin_fraction_proxy": 0.005, "liquidation_distance_buffer_fraction": 1.0}}
    stage = Stage("x", pd.Timestamp("2024-01-01T00:00:00Z"), pd.Timestamp("2024-01-02T00:00:00Z"), 1, 10000.0)
    result = simulate(sequence, {"BTCUSDT": market}, stage, Config(0.5, 0.01, 3.0, 0.0), contract)
    assert result.valid
    assert not result.forced_liquidation
    assert result.final_nav == 10200.0
