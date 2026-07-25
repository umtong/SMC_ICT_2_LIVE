from __future__ import annotations

import numpy as np
import pandas as pd

import tardis_development_v2 as dev


def test_exit_liquidity_shortfall_is_punitive() -> None:
    row = pd.Series({
        "um_bid": 99.9,
        "um_ask": 100.1,
        "um_bid_amount": 0.01,
        "um_ask_amount": 100.0,
    })
    price, overrun = dev.forced_exit(row, 1, 1.0)
    assert overrun is True
    assert price < row.um_bid


def test_invalid_exit_quote_fails_closed() -> None:
    row = pd.Series({
        "um_bid": float("nan"),
        "um_ask": 100.1,
        "um_bid_amount": 0.0,
        "um_ask_amount": 100.0,
    })
    try:
        dev.forced_exit(row, 1, 1.0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid actual exit quote did not fail closed")


def test_risk_size_respects_nav_leverage_and_quote_capacity() -> None:
    row = pd.Series({
        "um_bid": 99.9,
        "um_ask": 100.1,
        "um_bid_amount": 10.0,
        "um_ask_amount": 10.0,
    })
    stop = 99.0
    sized = dev.size_position(row, 1, stop, 10_000.0, 5.0)
    assert sized is not None
    quantity, entry, leverage = sized
    assert quantity <= 0.05 * row.um_ask_amount + 1e-12
    assert leverage <= dev.MAX_LEVERAGE + 1e-12
    risk = quantity * (abs(entry - stop) + (entry + abs(stop)) * 5.0 / 10_000.0 + (row.um_ask - row.um_bid))
    assert risk <= 10_000.0 * dev.RISK_FRACTION * 1.05 + 1e-8


def test_removed_path_return_removes_largest_positive_account_returns() -> None:
    frame = pd.DataFrame({"account_return": [0.10, 0.02, -0.01, 0.01, -0.005]})
    value = dev.removed_path_return(frame, 0.20)
    expected = np.prod(1.0 + np.array([0.02, -0.01, 0.01, -0.005])) - 1.0
    assert abs(value - expected) < 1e-12
