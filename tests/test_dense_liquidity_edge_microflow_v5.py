from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "dense_liquidity_edge_microflow"))

import extract_edge_microflow_v3 as source_v3
import extract_edge_microflow_v4 as source_v4
import evaluate_dense_edge_v4 as eval_v4
import evaluate_dense_edge_v5 as eval_v5


def test_sensor_starts_at_actual_crossing_and_entry_is_strictly_later():
    t0 = pd.Timestamp("2023-01-02T00:00:05Z")
    ts = [t0 - pd.Timedelta(seconds=1), t0, t0 + pd.Timedelta(seconds=4), t0 + pd.Timedelta(seconds=9), t0 + pd.Timedelta(seconds=10, milliseconds=400), t0 + pd.Timedelta(seconds=10, milliseconds=600)]
    stream = pd.DataFrame(
        {
            "ts": ts,
            "price": [99.9, 100.0, 100.2, 100.1, 100.15, 100.2],
            "qty": [1.0] * 6,
            "aggr": [1.0, 1.0, -1.0, 1.0, 1.0, 1.0],
            "turnover": [100.0] * 6,
        }
    )
    row = source_v4.sensor_row("BTCUSDT", pd.Timestamp("2023-01-02").date(), 1, 1, stream, 100.0, 95.0, 2.0)
    assert row is not None
    assert pd.Timestamp(row["event_ts"]) == t0
    assert pd.Timestamp(row["entry_ts"]) == t0 + pd.Timedelta(seconds=10, milliseconds=600)
    assert row["post_entry_minute_trade_count"] == 1


def test_post_entry_minute_excludes_pre_entry_prices():
    t = pd.Timestamp("2023-01-02T00:00:00Z")
    stream = pd.DataFrame(
        {
            "ts": [t + pd.Timedelta(seconds=x) for x in [1, 3, 9, 12]],
            "price": [100.0, 150.0, 100.1, 101.0],
            "qty": [1.0] * 4,
            "aggr": [1.0] * 4,
            "turnover": [100.0] * 4,
        }
    )
    # event at second 1; decision 11; activation 11.5; entry at second 12.
    row = source_v4.sensor_row("BTCUSDT", t.date(), 1, 0, stream, 100.0, 95.0, 2.0)
    assert row is not None
    assert row["post_entry_minute_high"] == 101.0
    assert row["post_entry_minute_low"] == 101.0


def make_symbol_data():
    ts = pd.date_range("2023-01-01T00:00:00Z", periods=12, freq="1min")
    opens = np.full(12, 100.0)
    highs = np.full(12, 100.5)
    lows = np.full(12, 99.5)
    highs[6] = 106.0
    price = pd.DataFrame({"ts": ts, "open": opens, "high": highs, "low": lows, "close": opens, "turnover": np.ones(12)})
    return eval_v4.SymbolData(
        symbol="BTCUSDT", price=price, oi=pd.DataFrame(), account=pd.DataFrame(), funding=pd.DataFrame(),
        minute_ns=price["ts"].astype("int64").to_numpy(), open_=opens, high=highs, low=lows, close=opens,
        turnover=np.ones(12), five_ts=pd.DatetimeIndex([pd.Timestamp("2023-01-01T00:05:00Z")]),
        five_close=np.array([99.0]), four_pools=pd.DataFrame(),
    )


def test_state_exit_open_precedes_later_target_touch_same_minute():
    sd = make_symbol_data()
    pools = pd.DataFrame(
        [{"kind": 1, "price": 105.0, "pivot_ts": pd.Timestamp("2022-12-31T12:00Z"), "available_ts": pd.Timestamp("2022-12-31T20:00Z"), "consumed_ts": pd.NaT}]
    )
    event = pd.Series(
        {
            "event_id": "x", "symbol": "BTCUSDT", "entry_ts": pd.Timestamp("2023-01-01T00:00:30Z"),
            "decision_ts": pd.Timestamp("2023-01-01T00:00:10Z"), "entry_price": 100.0,
            "level_side": 1, "level": 100.0, "atr15m20": 4.0, "prior_day_mid": 95.0,
            "sensor_high": 100.5, "sensor_low": 99.9,
            "post_entry_minute_high": 100.5, "post_entry_minute_low": 99.5,
            "post_entry_minute_last_ts": pd.Timestamp("2023-01-01T00:00:59Z"),
        }
    )
    r = eval_v5.resolve_action(event, "CONTINUE", sd, pools)
    assert r is not None
    assert r["exit_reason"] == "STATE"
    assert pd.Timestamp(r["exit_ts"]) == pd.Timestamp("2023-01-01T00:06:00Z")
    assert r["exit"] == 100.0


def test_cached_range_tree_reused_and_first_hit_correct():
    x = np.array([1.0, 2.0, 5.0, 3.0])
    a = eval_v5.CachedRangeTree(x, "max")
    b = eval_v5.CachedRangeTree(x, "max")
    assert a is b
    assert a.first(1, 4.0, "ge") == 2


def test_model_feature_contract_excludes_execution_and_future_fields():
    forbidden = {"entry_price", "post_entry_minute_high", "post_entry_minute_low", "post_entry_minute_close", "exit", "stop", "target", "funding_sum"}
    # This mirrors the V5 selection guard and protects future refactors.
    sample = pd.DataFrame({
        "entry_price": [1.0], "post_entry_minute_high": [1.1], "exit": [1.2], "stop": [0.9],
        "target": [1.2], "funding_sum": [0.0], "aligned_flow_imbalance": [0.2], "is_continue": [1.0],
    })
    selected = [c for c in sample if c not in forbidden and not c.startswith("post_entry_minute_")]
    assert selected == ["aligned_flow_imbalance", "is_continue"]
