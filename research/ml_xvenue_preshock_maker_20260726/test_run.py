from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd

import run as m


def contract(latency: int = 100) -> m.Contract:
    return m.Contract(
        placement_latency_ms=latency,
        decision_stride_ms=500,
        range_lookback_seconds=60,
        minimum_range_observations=100,
        minimum_target_bps=1.0,
        maximum_target_bps=100.0,
        minimum_stop_bps=1.0,
        maximum_stop_bps=100.0,
        minimum_train_events=10,
        minimum_calibration_events=10,
        minimum_confirmation_events=10,
        minimum_confirmation_fills=1,
    )


def events(latency: int = 100) -> tuple[pd.DataFrame, pd.DataFrame, m.Contract]:
    c = contract(latency)
    g = m.synthetic_grid()
    return m.generate_candidates(g, c), g, c


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
    assert q.loc[1, "bid_price"] == 101
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
    assert t.loc[1, "buy_min_price"] == 101
    assert t.loc[1, "sell_max_price"] == 100


def test_completed_state_latency_is_exact_for_both_paths() -> None:
    e100, _, _ = events(100)
    e300, _, _ = events(300)
    assert len(e100) and len(e300)
    assert (e100.placement_bin - e100.signal_bin == 2).all()
    assert (e300.placement_bin - e300.signal_bin == 4).all()


def test_both_long_and_short_inside_spread_orders_exist() -> None:
    e, g, c = events()
    assert set(e.side.unique()) == {-1, 1}
    placed = e[e.placed.eq(1)]
    longs = placed[placed.side.eq(1)]
    shorts = placed[placed.side.eq(-1)]
    assert len(longs) and len(shorts)
    for row in placed.head(100).itertuples(index=False):
        state_bin = int(row.placement_bin) - 1
        state = g.loc[state_bin]
        expected = state.by_bid_price + c.tick_size if row.side > 0 else state.by_ask_price - c.tick_size
        assert abs(row.order_price - expected) < 1e-9
        assert state.by_bid_price < row.order_price < state.by_ask_price
    assert (longs.target_price > longs.stop_price).all()
    assert (shorts.target_price < shorts.stop_price).all()


def test_prefix_invariance_for_all_model_features() -> None:
    raw = m.synthetic_grid()
    derived = {
        c for c in raw.columns
        if c.startswith("bin_ret_") or c.startswith("by_ret_")
        or c.endswith("_flow_500ms") or c.endswith("_flow_1s")
        or c.endswith("_update_intensity_1s") or c.endswith("_micro_edge_bps")
        or c in {
            "bin_fair_on_bybit", "fair_gap_bps", "bin_volatility_5s_bps",
            "relative_spread_bps", "prior_fair_high", "prior_fair_low", "tod_sin", "tod_cos",
        }
    }
    base = raw.drop(columns=sorted(derived), errors="ignore")
    c = contract()
    full = m.add_causal_features(base, c)
    cut = 6_500
    prefix = m.add_causal_features(base.iloc[:cut].copy(), c)
    common = prefix.index[-500:]
    cols = [
        "bin_fair_on_bybit", "fair_gap_bps", "prior_fair_high", "prior_fair_low",
        "bin_ret_500ms_bps", "bin_flow_1s", "relative_spread_bps",
        "bin_volatility_5s_bps", "tod_sin", "tod_cos",
    ]
    for col in cols:
        assert np.allclose(
            full.loc[common, col].to_numpy(),
            prefix.loc[common, col].to_numpy(),
            equal_nan=True,
            rtol=0,
            atol=1e-12,
        )


def test_counterfactual_flow_does_not_fill_after_historical_bid_moves_ahead() -> None:
    e, g, c = events()
    row = e[(e.side.eq(1)) & e.placed.eq(1)].iloc[0]
    start = int(row.placement_bin)
    start_i = g.index.get_loc(start)
    g2 = g.copy()
    g2.iloc[start_i:, g2.columns.get_loc("by_bid_price")] = row.order_price + c.tick_size
    g2.iloc[start_i:, g2.columns.get_loc("by_ask_price")] = row.order_price + 3 * c.tick_size
    g2.iloc[start_i:, g2.columns.get_loc("by_sell_amount")] = 100.0
    e2 = m.generate_candidates(g2, c)
    same = e2[e2.event_key.eq(row.event_key)]
    assert len(same) == 1
    assert same.iloc[0].filled == 0


def test_inside_spread_order_gets_first_priority_when_historical_bid_not_ahead() -> None:
    e, g, c = events()
    row = e[(e.side.eq(1)) & e.placed.eq(1)].iloc[0]
    start = int(row.placement_bin)
    start_i = g.index.get_loc(start)
    g2 = g.copy()
    g2.iloc[start_i, g2.columns.get_loc("by_bid_price")] = row.order_price - c.tick_size
    g2.iloc[start_i, g2.columns.get_loc("by_ask_price")] = row.order_price + 2 * c.tick_size
    g2.iloc[start_i, g2.columns.get_loc("by_sell_amount")] = max(row.order_qty * 2.0, 1.0)
    e2 = m.generate_candidates(g2, c)
    same = e2[e2.event_key.eq(row.event_key)]
    assert len(same) == 1
    assert same.iloc[0].filled == 1
    assert same.iloc[0].fill_bin == start


def test_no_elapsed_time_exit_reason_exists() -> None:
    e, _, _ = events()
    assert not e.exit_reason.str.contains("time|timeout", case=False, regex=True).any()
    assert set(e.exit_reason).issubset({
        "not_placed", "unfilled_structural_cancel", "opposite_liquidity_stop",
        "external_liquidity_target", "source_boundary_stop",
    })


def test_global_slot_begins_at_actual_placement_and_unfilled_order_blocks() -> None:
    scored = pd.DataFrame([
        {
            "event_key": "later_signal_earlier_placement", "placed": 1,
            "signal_bin": 90, "placement_bin": 110, "pending_end_bin": 200,
            "filled": 0, "fill_bin": np.nan, "exit_bin": np.nan, "side": 1,
            "gross_return_bps": 0, "predicted_gross_bps": 50,
            "stop_bps": 20, "max_quote_notional": 100_000, "exit_reason": "unfilled_structural_cancel",
        },
        {
            "event_key": "earlier_order", "placed": 1,
            "signal_bin": 100, "placement_bin": 108, "pending_end_bin": 180,
            "filled": 1, "fill_bin": 109, "exit_bin": 180, "side": 1,
            "gross_return_bps": 50, "predicted_gross_bps": 40,
            "stop_bps": 20, "max_quote_notional": 100_000, "exit_reason": "external_liquidity_target",
        },
        {
            "event_key": "blocked", "placed": 1,
            "signal_bin": 120, "placement_bin": 120, "pending_end_bin": 150,
            "filled": 1, "fill_bin": 121, "exit_bin": 150, "side": 1,
            "gross_return_bps": 100, "predicted_gross_bps": 80,
            "stop_bps": 20, "max_quote_notional": 100_000, "exit_reason": "external_liquidity_target",
        },
    ])
    trades, metrics = m.route_account(scored, 12.0, contract())
    assert metrics["trade_count"] == 1
    assert trades.iloc[0].event_key == "earlier_order"


def test_winner_removal_reroutes_released_global_slot() -> None:
    scored = pd.DataFrame([
        {
            "event_key": "winner", "placed": 1, "signal_bin": 90, "placement_bin": 100,
            "pending_end_bin": 200, "filled": 1, "fill_bin": 101, "exit_bin": 200,
            "side": 1, "gross_return_bps": 80, "predicted_gross_bps": 60,
            "stop_bps": 20, "max_quote_notional": 100_000, "exit_reason": "external_liquidity_target",
        },
        {
            "event_key": "rerouted", "placed": 1, "signal_bin": 120, "placement_bin": 120,
            "pending_end_bin": 170, "filled": 1, "fill_bin": 121, "exit_bin": 170,
            "side": 1, "gross_return_bps": 40, "predicted_gross_bps": 45,
            "stop_bps": 20, "max_quote_notional": 100_000, "exit_reason": "external_liquidity_target",
        },
    ])
    base, _ = m.route_account(scored, 12.0, contract())
    removed, _ = m.route_account(scored, 12.0, contract(), {"winner"})
    assert list(base.event_key) == ["winner"]
    assert list(removed.event_key) == ["rerouted"]
