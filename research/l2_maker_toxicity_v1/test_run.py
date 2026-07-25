from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run


def test_parse_levels():
    p, q = run.parse_levels(json.dumps([["100.0", "2.0"], ["99.0", "3.0"]]))
    assert p.tolist() == [100.0, 99.0]
    assert q.tolist() == [2.0, 3.0]


def test_continuity_audit_detects_gap():
    df = pd.DataFrame({"e": ["depthUpdate"] * 3, "u": [10, 20, 30], "pu": [9, 10, 15], "T": [1000, 1100, 1200]})
    a = run.continuity_audit(df)
    assert a["updates"] == 3
    assert a["discontinuities"] == 1


def make_market():
    book = pd.DataFrame({
        "transaction_time": [0, 100, 500, 1100, 2100, 3200, 4500],
        "bid": [99, 99, 99, 99, 100, 101, 102], "bid_qty": [10] * 7,
        "ask": [100, 100, 100, 100, 101, 102, 103], "ask_qty": [10] * 7,
    })
    trades = pd.DataFrame({"time": [300, 400, 600, 700, 800], "price": [99] * 5, "qty": [3] * 5, "buyer_maker": [True] * 5})
    return book, trades


def test_queue_fill_requires_actual_opposing_volume():
    book, trades = make_market()
    no = run.order_outcome(book, trades, decision_ms=0, side=1, queue_mult=2.0, ttl_s=1, horizon_s=3)
    assert not no["filled"]
    yes = run.order_outcome(book, trades, decision_ms=0, side=1, queue_mult=1.0, ttl_s=1, horizon_s=3)
    assert yes["filled"]
    assert yes["entry_price"] == 99
    assert yes["exit_price"] == 102


def test_touch_or_cancellation_without_trade_never_fills():
    book, _ = make_market()
    empty = pd.DataFrame({"time": [], "price": [], "qty": [], "buyer_maker": []})
    out = run.order_outcome(book, empty, 0, 1, 1.0, 3, 3)
    assert not out["filled"]


def test_sealed_dates_are_prohibited():
    assert "2026-04-03" in run.SEALED_DATES
    assert not set(run.FIT_DATES + run.CALIB_DATES + run.VALID_DATES) & set(run.SEALED_DATES)


def test_portfolio_metrics_top_trade_removal():
    led = pd.DataFrame({"gross_return": [0.02] * 20 + [-0.005] * 5, "decision_ms": np.arange(25) * 1000})
    m = run.portfolio_metrics(led, 0)
    assert m["trades"] == 25
    assert m["profit_factor"] > 1
    assert m["after_top10_multiple"] > 1
