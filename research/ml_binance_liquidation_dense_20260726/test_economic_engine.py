from __future__ import annotations

import math

import numpy as np
import pandas as pd

import economic_engine as engine


def _bars(start: str, periods: int, price: float = 100.0) -> pd.DataFrame:
    times = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    drift = np.arange(periods, dtype=float) * 0.0001
    close = price + drift
    return pd.DataFrame(
        {
            "open_time_ms": times.view("int64") // 1_000_000,
            "open": close,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "base_volume": np.full(periods, 10.0),
            "close_time_ms": times.view("int64") // 1_000_000 + 59_999,
            "quote_volume": np.full(periods, 1_000_000.0),
            "trade_count": np.full(periods, 100),
            "taker_buy_base": np.full(periods, 5.0),
            "taker_buy_quote": np.full(periods, 500_000.0),
            "ignore": np.zeros(periods),
        }
    )


def test_bucket_semantics_do_not_treat_absence_as_zero() -> None:
    timestamp = engine.utc_ms("2023-08-01 00:00:10")
    events = pd.DataFrame(
        [
            {
                "event_id": "one",
                "source_symbol": "BTCUSD_PERP",
                "target_symbol": "BTCUSDT",
                "time_ms": timestamp,
                "side_sign": -1,
                "effective_price": 30_000.0,
                "executed_usd_notional": 100_000.0,
                "executed_contract_count": 1_000.0,
            }
        ]
    )
    buckets = engine.aggregate_snapshot_buckets(events)
    assert len(buckets) == 1
    assert buckets.iloc[0]["observed_btc_eth_snapshot_breadth"] == -1.0
    assert buckets.iloc[0]["decision_ms"] == engine.utc_ms("2023-08-01 00:01:05")


def test_feature_cutoff_excludes_forming_and_entry_bars(monkeypatch) -> None:
    frame = _bars("2023-08-01 00:00", 300)
    buckets = pd.DataFrame(
        [
            {
                "bucket_id": "bucket",
                "bucket_start_ms": engine.utc_ms("2023-08-01 02:00"),
                "decision_ms": engine.utc_ms("2023-08-01 02:01:05"),
                "source_symbol": "BTCUSD_PERP",
                "target_symbol": "BTCUSDT",
                "signed_usd_notional": -1_000_000.0,
                "absolute_usd_notional": 1_000_000.0,
                "snapshot_count": 4,
                "price_notional_hhi": 0.25,
                "same_side_share": -1.0,
                "weighted_snapshot_price": 100.0,
                "raw_event_ids": ["a"],
                "observed_btc_eth_snapshot_breadth": -1.0,
            }
        ]
    )
    monkeypatch.setattr(engine, "build_confirmed_pivots", lambda _: (pd.DataFrame(), pd.DataFrame()))
    monkeypatch.setattr(
        engine,
        "nearest_unconsumed_pools",
        lambda decision_ms, completed_index, reference_price, frame, upper, lower, lookback_days=14: (
            reference_price * 1.02,
            reference_price * 0.98,
        ),
    )
    bars = {symbol: frame.copy() for symbol in engine.TARGET_SYMBOLS}
    funding = {
        symbol: pd.DataFrame({"time_ms": [], "rate": []})
        for symbol in engine.TARGET_SYMBOLS
    }
    metrics = {
        symbol: pd.DataFrame({"time_ms": [], "open_interest": []})
        for symbol in engine.TARGET_SYMBOLS
    }
    original = engine.build_event_rows(buckets, bars, funding, metrics).iloc[0]
    assert original["feature_available_through_ms"] <= original["decision_ms"]
    forming_index = int(original["completed_feature_index"]) + 1
    entry_index = int(original["entry_index"])
    mutated = frame.copy()
    mutated.loc[forming_index, ["open", "high", "low", "close", "quote_volume"]] = [500, 900, 1, 700, 9e12]
    mutated.loc[entry_index, "open"] = float(original["upper"]) * 1.2
    changed_bars = {symbol: mutated.copy() for symbol in engine.TARGET_SYMBOLS}
    changed = engine.build_event_rows(buckets, changed_bars, funding, metrics).iloc[0]
    for column in engine.FEATURES:
        a, b = float(original[column]), float(changed[column])
        assert math.isclose(a, b, rel_tol=0, abs_tol=1e-12) or (math.isnan(a) and math.isnan(b)), column
    assert bool(changed["entry_gap_invalidated"])


def test_partition_label_never_crosses_2024(monkeypatch) -> None:
    frame = _bars("2023-12-31 20:00", 360)
    bucket_start = engine.utc_ms("2023-12-31 22:00")
    buckets = pd.DataFrame(
        [
            {
                "bucket_id": "boundary",
                "bucket_start_ms": bucket_start,
                "decision_ms": bucket_start + 65_000,
                "source_symbol": "BTCUSD_PERP",
                "target_symbol": "BTCUSDT",
                "signed_usd_notional": 1_000_000.0,
                "absolute_usd_notional": 1_000_000.0,
                "snapshot_count": 2,
                "price_notional_hhi": 0.5,
                "same_side_share": 1.0,
                "weighted_snapshot_price": 100.0,
                "raw_event_ids": ["x"],
                "observed_btc_eth_snapshot_breadth": 1.0,
            }
        ]
    )
    monkeypatch.setattr(engine, "build_confirmed_pivots", lambda _: (pd.DataFrame(), pd.DataFrame()))
    monkeypatch.setattr(
        engine,
        "nearest_unconsumed_pools",
        lambda *args, **kwargs: (101.0, 99.0),
    )
    post_boundary = np.flatnonzero(frame["open_time_ms"].to_numpy() >= engine.utc_ms("2024-01-01 00:01"))
    frame.loc[post_boundary, "high"] = 102.0
    bars = {symbol: frame.copy() for symbol in engine.TARGET_SYMBOLS}
    empty_funding = {symbol: pd.DataFrame({"time_ms": [], "rate": []}) for symbol in engine.TARGET_SYMBOLS}
    empty_metrics = {symbol: pd.DataFrame({"time_ms": [], "open_interest": []}) for symbol in engine.TARGET_SYMBOLS}
    row = engine.build_event_rows(buckets, bars, empty_funding, empty_metrics).iloc[0]
    assert pd.isna(row["label_up"])
    assert row["label_reason"] == "UNRESOLVED_AT_PARTITION_BOUNDARY"
    assert row["stage_end_ms"] == engine.utc_ms("2024-01-01")


def test_one_global_slot_selects_stronger_same_timestamp() -> None:
    frame = _bars("2023-08-01 00:00", 120)
    rows = pd.DataFrame(
        [
            {
                "event_id": "weak",
                "target_symbol": "BTCUSDT",
                "decision_ms": engine.utc_ms("2023-08-01 00:00:30"),
                "entry_ms": engine.utc_ms("2023-08-01 00:01"),
                "entry_index": 1,
                "stage_end_ms": engine.utc_ms("2023-08-01 02:00"),
                "stage_end_index": 119,
                "entry_price": 100.0,
                "decision_reference_price": 100.0,
                "upper": 102.0,
                "lower": 98.0,
                "distance_to_frozen_upper_liquidity": 0.02,
                "distance_to_frozen_lower_liquidity": 0.02,
                "entry_gap_invalidated": False,
            },
            {
                "event_id": "strong",
                "target_symbol": "ETHUSDT",
                "decision_ms": engine.utc_ms("2023-08-01 00:00:30"),
                "entry_ms": engine.utc_ms("2023-08-01 00:01"),
                "entry_index": 1,
                "stage_end_ms": engine.utc_ms("2023-08-01 02:00"),
                "stage_end_index": 119,
                "entry_price": 100.0,
                "decision_reference_price": 100.0,
                "upper": 104.0,
                "lower": 98.0,
                "distance_to_frozen_upper_liquidity": 0.04,
                "distance_to_frozen_lower_liquidity": 0.02,
                "entry_gap_invalidated": False,
            },
        ]
    )
    bars = {symbol: frame.copy() for symbol in engine.TARGET_SYMBOLS}
    funding = {symbol: pd.DataFrame({"time_ms": [], "rate": []}) for symbol in engine.TARGET_SYMBOLS}
    trades = engine.route_global_slot(rows, np.array([0.70, 0.70]), bars, funding, 24.0)
    assert len(trades) == 1
    assert trades[0].event_id == "strong"


def test_risk_grid_and_no_elapsed_time_exit() -> None:
    assert len(engine.RISK_GRID) * len(engine.CAP_GRID) == 99
    forbidden = {"TIMEOUT", "MAX_HOLD", "ELAPSED_TIME"}
    assert forbidden.isdisjoint({"TARGET", "STOP", "STOP_FIRST_AMBIGUOUS", "COMPLETED_STATE_INVALIDATION", "MARK_TO_MARKET_STAGE_BOUNDARY"})
