from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd

import run as m


def synthetic_grid(n: int = 1400) -> pd.DataFrame:
    idx = pd.RangeIndex(1_000_000, 1_000_000 + n, name="bin")
    g = pd.DataFrame(index=idx)
    base = np.full(n, 20_000.0)
    bin_mid = base.copy()
    by_mid = base.copy()
    for s in range(650, 1300, 50):
        bin_mid[s:s+10] += np.linspace(0, 30, 10)
        bin_mid[s+10:s+25] += 30
        # Bybit remains stale long enough for a passive best-quote order to activate/fill,
        # then catches up toward the frozen external fair value.
        by_mid[s:s+12] += 0.0
        by_mid[s+12:s+25] += np.linspace(0, 28, 13)
    for p, mid in (("bin", bin_mid), ("by", by_mid)):
        g[f"{p}_mid"] = mid
        g[f"{p}_micro"] = mid + 0.05
        g[f"{p}_bid_price"] = mid - 0.5
        g[f"{p}_ask_price"] = mid + 0.5
        g[f"{p}_bid_amount"] = 1.0
        g[f"{p}_ask_amount"] = 1.0
        g[f"{p}_imbalance"] = 0.0
        g[f"{p}_spread_bps"] = (1.0 / (mid - 0.5)) * 10_000
        g[f"{p}_quote_updates"] = 1.0
        g[f"{p}_quote_age_ms"] = 0.0
        g[f"{p}_buy_amount"] = 0.0
        g[f"{p}_sell_amount"] = 0.0
        g[f"{p}_trade_count"] = 0.0
        g[f"{p}_buy_min_price"] = np.nan
        g[f"{p}_sell_max_price"] = np.nan
        g[f"{p}_last_trade_price"] = mid
    for s in range(650, 1300, 50):
        fill_rows = g.index[s + 2:s + 11]
        g.loc[fill_rows, "by_sell_amount"] = 2.0
        g.loc[fill_rows, "by_sell_max_price"] = g.loc[fill_rows, "by_bid_price"]
        g.loc[fill_rows, "by_last_trade_price"] = g.loc[fill_rows, "by_bid_price"]
    return m.add_causal_features(g)


def test_quote_aggregation_uses_last_local_arrival(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv.gz"
    data = (
        "exchange,symbol,timestamp,local_timestamp,ask_amount,ask_price,bid_price,bid_amount\n"
        "x,BTCUSDT,1,100001,1,101,100,2\n"
        "x,BTCUSDT,2,100099,3,102,101,4\n"
        "x,BTCUSDT,3,200001,5,103,102,6\n"
    )
    with gzip.open(path, "wt") as fh:
        fh.write(data)
    q = m.aggregate_quotes(path)
    assert list(q.index) == [1, 2]
    assert q.loc[1, "ask_price"] == 102
    assert q.loc[1, "quote_updates"] == 2


def test_trade_aggregation_preserves_aggressor_side(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv.gz"
    data = (
        "exchange,symbol,timestamp,local_timestamp,id,side,price,amount\n"
        "x,BTCUSDT,1,100001,a,buy,101,2\n"
        "x,BTCUSDT,2,100099,b,sell,100,3\n"
    )
    with gzip.open(path, "wt") as fh:
        fh.write(data)
    t = m.aggregate_trades(path)
    assert t.loc[1, "buy_amount"] == 2
    assert t.loc[1, "sell_amount"] == 3
    assert t.loc[1, "trade_count"] == 2
    assert t.loc[1, "buy_min_price"] == 101
    assert t.loc[1, "sell_max_price"] == 100


def test_placement_is_strictly_after_signal_and_fill_consumes_queue() -> None:
    g = synthetic_grid()
    c = m.Contract(signal_shock_bps=1.0, signal_gap_bps=0.2, placement_latency_ms=300)
    events = m.generate_candidates(g, c)
    assert len(events) > 0
    # Completed signal bucket + 300ms latency => four 100ms bins.
    assert (events.placement_bin - events.signal_bin == 4).all()
    filled = events[events.filled.eq(1)]
    assert len(filled) > 0
    assert (filled.fill_bin >= filled.placement_bin).all()
    assert (filled.order_qty > 0).all()


def test_no_elapsed_time_exit_reason_exists() -> None:
    g = synthetic_grid()
    c = m.Contract(signal_shock_bps=1.0, signal_gap_bps=0.2)
    events = m.generate_candidates(g, c)
    assert len(events) > 0
    allowed = {"unfilled_structural_cancel", "fair_value_catchup", "reference_reversal", "source_boundary_stop"}
    assert set(events.exit_reason).issubset(allowed)
    assert not events.exit_reason.str.contains("time|timeout", case=False, regex=True).any()


def test_global_slot_blocks_overlapping_selected_events() -> None:
    scored = pd.DataFrame([
        {
            "event_key": "a", "signal_bin": 100, "placement_bin": 102, "pending_end_bin": 200, "filled": 1,
            "fill_bin": 110, "exit_bin": 200, "side": 1, "gross_return_bps": 50,
            "expected_gross_bps": 40, "stop_distance_bps": 20, "max_quote_notional": 100_000,
            "exit_reason": "fair_value_catchup",
        },
        {
            "event_key": "b", "signal_bin": 150, "placement_bin": 152, "pending_end_bin": 180, "filled": 1,
            "fill_bin": 151, "exit_bin": 180, "side": 1, "gross_return_bps": 100,
            "expected_gross_bps": 80, "stop_distance_bps": 20, "max_quote_notional": 100_000,
            "exit_reason": "fair_value_catchup",
        },
    ])
    trades, metrics = m.route_account(scored, 12.0, m.Contract())
    assert metrics["trade_count"] == 1
    assert trades.iloc[0].event_key == "a"


def test_winner_exclusion_releases_slot_and_reroutes() -> None:
    scored = pd.DataFrame([
        {
            "event_key": "a", "signal_bin": 100, "placement_bin": 102, "pending_end_bin": 200, "filled": 1,
            "fill_bin": 110, "exit_bin": 200, "side": 1, "gross_return_bps": 80,
            "expected_gross_bps": 50, "stop_distance_bps": 20, "max_quote_notional": 100_000,
            "exit_reason": "fair_value_catchup",
        },
        {
            "event_key": "b", "signal_bin": 150, "placement_bin": 152, "pending_end_bin": 180, "filled": 1,
            "fill_bin": 151, "exit_bin": 180, "side": 1, "gross_return_bps": 40,
            "expected_gross_bps": 45, "stop_distance_bps": 20, "max_quote_notional": 100_000,
            "exit_reason": "fair_value_catchup",
        },
    ])
    base, _ = m.route_account(scored, 12.0, m.Contract())
    removed, _ = m.route_account(scored, 12.0, m.Contract(), {"a"})
    assert list(base.event_key) == ["a"]
    assert list(removed.event_key) == ["b"]


def test_ambiguous_mixed_price_volume_does_not_fill_queue(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv.gz"
    data = (
        "exchange,symbol,timestamp,local_timestamp,id,side,price,amount\n"
        "x,BTCUSDT,1,100001,a,sell,100,10\n"
        "x,BTCUSDT,2,100099,b,sell,101,10\n"
    )
    with gzip.open(path, "wt") as fh:
        fh.write(data)
    t = m.aggregate_trades(path)
    assert t.loc[1, "sell_amount"] == 20
    assert t.loc[1, "sell_max_price"] == 101
    # A bid at 100 cannot conservatively claim all 20 units crossed it.
    assert not (t.loc[1, "sell_max_price"] <= 100)


def test_global_slot_starts_at_actual_order_placement() -> None:
    scored = pd.DataFrame([
        {
            "event_key": "late_signal", "signal_bin": 100, "placement_bin": 110,
            "pending_end_bin": 200, "filled": 1, "fill_bin": 111, "exit_bin": 200,
            "side": 1, "gross_return_bps": 50, "expected_gross_bps": 40,
            "stop_distance_bps": 20, "max_quote_notional": 100_000,
            "exit_reason": "fair_value_catchup",
        },
        {
            "event_key": "earlier_order", "signal_bin": 105, "placement_bin": 108,
            "pending_end_bin": 180, "filled": 1, "fill_bin": 109, "exit_bin": 180,
            "side": 1, "gross_return_bps": 50, "expected_gross_bps": 35,
            "stop_distance_bps": 20, "max_quote_notional": 100_000,
            "exit_reason": "fair_value_catchup",
        },
    ])
    trades, metrics = m.route_account(scored, 12.0, m.Contract())
    assert metrics["trade_count"] == 1
    assert trades.iloc[0].event_key == "earlier_order"
