from __future__ import annotations

from dataclasses import replace

import pandas as pd

import cross_venue_development_v2 as d2
import cross_venue_development_v3 as d3
import cross_venue_development_v4b as d4b


def make_trade(symbol: str, net: float, before: float, after: float, intraday_dd: float) -> d3.AccountTradeV3:
    return d3.AccountTradeV3(
        config_id="c",
        day="2022-02-01",
        symbol=symbol,
        family="f",
        decision_ms=1,
        entry_ms=2,
        exit_ms=3,
        side=1,
        entry_price=100.0,
        exit_price=101.0,
        stop_price=99.0,
        quantity=1.0,
        notional=100.0,
        leverage=0.01,
        gross_pnl=net + 0.1,
        fees=0.1,
        net_pnl=net,
        account_return=net / before,
        nav_before=before,
        nav_after=after,
        exit_reason="horizon",
        score=1.0,
        exit_liquidity_overrun=False,
        maximum_intratrade_drawdown=intraday_dd,
    )


def test_patch_is_idempotent_and_invalid_exit_fails_closed() -> None:
    d4b.patch_once()
    first = d3.mandatory_exit_price
    d4b.patch_once()
    assert d3.mandatory_exit_price is first
    invalid = pd.Series({
        "bn_bid": float("nan"),
        "bn_ask": 100.1,
        "bn_bid_amount": 0.0,
        "bn_ask_amount": 100.0,
    })
    try:
        d4b.strict_exit(invalid, 1, 1.0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid exit quote did not fail closed")


def test_exit_liquidity_shortfall_is_punitive_not_omitted() -> None:
    row = pd.Series({
        "bn_bid": 99.9,
        "bn_ask": 100.1,
        "bn_bid_amount": 0.01,
        "bn_ask_amount": 100.0,
    })
    price, overrun = d4b.strict_exit(row, 1, 1.0)
    assert overrun is True
    assert price < row.bn_bid


def test_positive_symbol_concentration_uses_positive_trade_pnl() -> None:
    d4b.patch_once()
    trades = [
        make_trade("BTCUSDT", 100.0, 10_000.0, 10_100.0, 0.01),
        make_trade("BTCUSDT", -90.0, 10_100.0, 10_010.0, 0.02),
        make_trade("ETHUSDT", 50.0, 10_010.0, 10_060.0, 0.01),
    ]
    metrics = d4b.d4.account_metrics_v4(trades, {"ending_nav": 10_060.0, "maximum_drawdown": 0.02})
    # Positive contribution is BTC 100 / total positive 150, not net BTC 10 / 60.
    assert abs(metrics["maximum_single_symbol_positive_pnl_share"] - 2.0 / 3.0) < 1e-12


def test_conservative_drawdown_combines_closed_and_intratrade_components() -> None:
    d4b.patch_once()
    trades = [
        make_trade("BTCUSDT", 100.0, 10_000.0, 10_100.0, 0.01),
        make_trade("ETHUSDT", -200.0, 10_100.0, 9_900.0, 0.03),
    ]
    metrics = d4b.d4.account_metrics_v4(trades, {"ending_nav": 9_900.0, "maximum_drawdown": 0.0})
    closed = 1.0 - 9_900.0 / 10_100.0
    assert metrics["closed_path_drawdown"] >= closed - 1e-12
    assert metrics["conservative_combined_drawdown"] >= closed + 0.03 - 1e-12
    assert metrics["maximum_drawdown"] == metrics["conservative_combined_drawdown"]
