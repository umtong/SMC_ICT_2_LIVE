from __future__ import annotations

import pandas as pd

import cross_venue_execution_v5 as base
import cross_venue_pilot as v1
import cross_venue_pilot_cache_v5d as cache


def _trade(config_id: str) -> base.FixedTradeV5:
    return base.FixedTradeV5(
        config_id=config_id,
        day="2022-01-01",
        symbol="BTCUSDT",
        family="bybit_to_binance_propagation",
        decision_ms=1_000,
        entry_ms=1_100,
        exit_ms=4_100,
        entry_us=1_100_000,
        exit_us=4_100_000,
        side=1,
        entry_price=100.0,
        exit_price=100.1,
        gross_bps=9.9950033308,
        spread_bps=1.0,
        fee_bps_per_side=0.0,
        net_bps=9.9950033308,
        exit_reason="horizon",
        score=3.0,
        exit_liquidity_overrun=False,
        trigger_boundary_us=4_000_000,
    )


def test_duplicate_grid_rows_reuse_path_and_preserve_config_id() -> None:
    frames = {("2022-01-01", "BTCUSDT"): pd.DataFrame({"x": [1.0]})}
    events = [
        v1.Event(
            "2022-01-01",
            "BTCUSDT",
            "bybit_to_binance_propagation",
            1_000,
            1,
            3.0,
            0.001,
        )
    ]
    first = v1.Config("bybit_to_binance_propagation", 1000, 4.0, 0.60, 0.25, 100, 3000, 4.0, 2.0)
    duplicate = v1.Config("bybit_to_binance_propagation", 1000, 4.0, 0.60, 0.25, 100, 3000, 4.0, 3.0)
    distinct_stop = v1.Config("bybit_to_binance_propagation", 1000, 4.0, 0.60, 0.25, 100, 3000, 8.0, 2.0)

    calls: list[str] = []
    original = cache._ORIGINAL_SIMULATE_FIXED_DAY

    def fake_simulator(_frames, _events, config):
        calls.append(config.config_id)
        return [_trade(config.config_id)]

    try:
        cache._ORIGINAL_SIMULATE_FIXED_DAY = fake_simulator
        cache.clear()
        first_trades = cache.simulate_fixed_day_cached(frames, events, first)
        duplicate_trades = cache.simulate_fixed_day_cached(frames, events, duplicate)
        distinct_trades = cache.simulate_fixed_day_cached(frames, events, distinct_stop)
    finally:
        cache._ORIGINAL_SIMULATE_FIXED_DAY = original
        cache.clear()

    assert len(calls) == 2
    assert first_trades[0].config_id == first.config_id
    assert duplicate_trades[0].config_id == duplicate.config_id
    assert first_trades[0].gross_bps == duplicate_trades[0].gross_bps
    assert distinct_trades[0].config_id == distinct_stop.config_id


def test_snapback_ignores_non_signal_cartesian_dimensions() -> None:
    frames = {("2022-01-01", "BTCUSDT"): pd.DataFrame({"x": [1.0]})}
    events: list[v1.Event] = []
    left = v1.Config("simultaneous_shock_basis_snapback", 1000, 4.0, 0.60, 0.25, 100, 3000, 4.0, 2.0)
    right = v1.Config("simultaneous_shock_basis_snapback", 1000, 8.0, 0.75, 0.50, 100, 3000, 4.0, 2.0)
    assert cache.semantic_execution_key(frames, events, left) == cache.semantic_execution_key(frames, events, right)
