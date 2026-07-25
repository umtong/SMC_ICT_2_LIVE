from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import cross_venue_basis_v5d as basis_v5d
import cross_venue_execution_v5d as v5d
import cross_venue_pilot as v1
import cross_venue_signals_v5d as signals_v5d
import test_cross_venue_execution_v5c as fixtures


def execution_frame() -> pd.DataFrame:
    frame = fixtures.frame()
    frame["bn_spread"] = 0.2
    frame["bb_spread"] = 0.2
    return frame


def config() -> v1.Config:
    return fixtures.config(latency_ms=100)


def event() -> v1.Event:
    return fixtures.event()


def account_trade(
    day: str,
    before: float,
    after: float,
    net: float,
    intratrade: float,
) -> v5d.AccountTradeV5:
    return v5d.AccountTradeV5(
        config_id="cfg",
        day=day,
        symbol="BTCUSDT",
        family="f",
        decision_ms=1,
        entry_ms=2,
        exit_ms=3,
        entry_us=2_000,
        exit_us=3_000,
        side=1,
        entry_price=100.0,
        exit_price=101.0,
        stop_price=99.0,
        quantity=1.0,
        notional=100.0,
        leverage=0.01,
        gross_pnl=net,
        fees=0.0,
        net_pnl=net,
        account_return=net / before,
        nav_before=before,
        nav_after=after,
        exit_reason="horizon",
        score=1.0,
        exit_liquidity_overrun=False,
        maximum_intratrade_drawdown=intratrade,
        trigger_boundary_us=2_500,
    )


def test_long_exit_has_no_ten_percent_economic_floor() -> None:
    quote = {"bid": 100.0, "bid_amount": 0.001, "ask": 101.0, "ask_amount": 100.0}
    price, overrun = v5d._mandatory_exit_without_economic_floor(quote, 1, 1.0)
    assert overrun is True
    assert 0 < price < 10.0


def test_drawdown_is_not_closed_plus_intratrade_double_counted() -> None:
    trades = [
        account_trade("2022-01-01", 10_000.0, 11_000.0, 1_000.0, 0.05),
        account_trade("2022-02-01", 11_000.0, 9_900.0, -1_100.0, 0.10),
    ]
    metrics = v5d.account_metrics_v5d(
        trades,
        {"nav": 9_900.0, "peak": 11_000.0, "maximum_drawdown": 0.10},
        ("2022-01-01", "2022-02-01"),
    )
    assert abs(metrics["closed_path_drawdown"] - 0.10) < 1e-12
    assert abs(metrics["maximum_drawdown"] - 0.10) < 1e-12
    assert metrics["conservative_combined_drawdown"] == metrics["maximum_drawdown"]


def test_terminal_account_loss_is_finite_and_clamped() -> None:
    trade = account_trade("2022-01-01", 10_000.0, -100.0, -10_100.0, 1.0)
    metrics = v5d.account_metrics_v5d(
        [trade],
        {"nav": -100.0, "peak": 10_000.0, "maximum_drawdown": 1.0},
        ("2022-01-01",),
    )
    assert metrics["terminal_account_loss"] is True
    assert metrics["ending_nav"] == 0.0
    assert metrics["total_return"] == -1.0
    assert metrics["geometric_sample_day_return"] == -1.0
    assert metrics["maximum_drawdown"] == 1.0


def test_position_crossing_unavailable_state_fails_closed() -> None:
    basis_v5d.patch()
    v5d.patch_v5()
    frame = execution_frame()
    frame.loc[61_000:61_500, "bb_mid"] = np.nan
    with pytest.raises(ValueError, match="unavailable"):
        v5d.simulate_fixed_day_v5({("synthetic", "BTCUSDT"): frame}, [event()], config())


def test_exit_quote_delayed_over_one_second_fails_closed() -> None:
    basis_v5d.patch()
    v5d.patch_v5()
    frame = execution_frame()
    columns = [name for name in frame.columns if name.startswith("bn_first_")]
    frame.loc[63_300:64_400, columns] = np.nan
    with pytest.raises(ValueError, match="exit exceeded"):
        v5d.simulate_fixed_day_v5({("synthetic", "BTCUSDT"): frame}, [event()], config())


def test_segmented_basis_history_does_not_cross_source_gap() -> None:
    index = np.arange(0, 100_000, v1.BUCKET_MS, dtype=np.int64)
    frame = pd.DataFrame(index=index)
    frame["bn_mid"] = 100.0
    frame["bb_mid"] = 101.0
    frame["bn_spread"] = 0.2
    frame["bb_spread"] = 0.2
    frame["bn_trade_notional"] = 1.0
    frame["bb_trade_notional"] = 1.0
    frame["bn_signed_notional"] = 0.0
    frame["bb_signed_notional"] = 0.0
    frame.loc[70_000, ["bb_mid", "bb_spread"]] = np.nan
    common = signals_v5d._common(frame)
    assert np.isfinite(common["basis_median"].loc[69_900])
    assert np.isnan(common["basis_median"].loc[80_000])
    basis_v5d.prepare_basis_v5d(frame)
    assert np.isnan(frame.loc[80_000, "_v5_basis_median"])


def test_time_compressed_grid_is_rejected() -> None:
    basis_v5d.patch()
    v5d.patch_v5()
    frame = execution_frame().drop(index=61_000)
    with pytest.raises(ValueError, match="complete 100-ms"):
        v5d.simulate_fixed_day_v5({("synthetic", "BTCUSDT"): frame}, [event()], config())
