from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import liq_base as base
import run


def synthetic_day(prices: list[float], times: list[float] | None = None) -> base.DayData:
    if times is None:
        times = [10.0 + i * 0.1 for i in range(len(prices))]
    n = base.SECONDS_PER_DAY
    mid = np.full(n, np.nan)
    high = np.full(n, np.nan)
    low = np.full(n, np.nan)
    total = np.zeros(n)
    signed = np.zeros(n)
    liq_buy = np.zeros(n)
    liq_sell = np.zeros(n)
    bid_amount = np.full(n, 100.0)
    ask_amount = np.full(n, 100.0)
    for t, price in zip(times, prices):
        sec = int(t)
        mid[sec] = price
        high[sec] = price if not np.isfinite(high[sec]) else max(high[sec], price)
        low[sec] = price if not np.isfinite(low[sec]) else min(low[sec], price)
        total[sec] += price * 10
    qts = np.array(times, dtype=float)
    px = np.array(prices, dtype=float)
    return base.DayData(
        "BTCUSDT", "1970-01-01", 0.0,
        mid, high, low, total, signed, liq_buy, liq_sell,
        bid_amount, ask_amount,
        qts, px - 0.01, px + 0.01, np.full(len(px), 100.0), np.full(len(px), 100.0),
        qts, px,
    )


def event(direction: int = 1) -> dict:
    return {
        "trade_direction": direction,
        "decision_time": 10.0,
        "liquidity_level": 99.5 if direction > 0 else 100.5,
        "sweep_extreme": 99.0 if direction > 0 else 101.0,
        "decision_mid": 100.0,
        "range_mid": 101.0 if direction > 0 else 99.0,
    }


def test_grid_and_stable_ids() -> None:
    grid = list(run.parameter_grid())
    assert len(grid) == 1024
    assert run.candidate_id(grid[0]) == run.candidate_id(dict(grid[0]))


def test_trade_through_required_and_target_before_fill_cancels() -> None:
    data = synthetic_day([100.0, 99.6, 99.49, 100.5, 101.1], [10.0, 10.2, 10.3, 10.4, 10.5])
    filled, when, reason = run.pending_resolution(data, 10.1, 1, 99.5, 98.9, 101.0, 1.0)
    assert filled is True
    assert when == 10.3
    assert reason == "FILLED_TRADETHROUGH"

    data2 = synthetic_day([100.0, 100.5, 101.1, 99.4], [10.0, 10.2, 10.3, 10.4])
    filled2, when2, reason2 = run.pending_resolution(data2, 10.1, 1, 99.5, 98.9, 101.0, 1.0)
    assert filled2 is False
    assert when2 == 10.3
    assert reason2 == "TARGET_REACHED_BEFORE_FILL"


def test_post_only_reject_and_valid_passive_fill() -> None:
    data = synthetic_day([100.0, 99.4, 101.2], [10.1, 10.3, 10.5])
    bad = dict(event(1)); bad["liquidity_level"] = 100.1
    rejected = run.make_passive_outcome(data, bad, 100, "liquidity_level", 1.0, "two_r")
    assert rejected.valid is False
    assert rejected.exit_reason == "POST_ONLY_REJECT"

    good = run.make_passive_outcome(data, event(1), 100, "liquidity_level", 1.0, "equilibrium")
    assert good.valid is True
    assert good.filled is True
    assert good.entry_price == 99.5


def test_adverse_stop_rebound_cannot_become_profit() -> None:
    data = synthetic_day([100.0, 99.4, 98.8, 101.5], [10.1, 10.2, 10.3, 10.4])
    outcome = run.make_passive_outcome(data, event(1), 100, "liquidity_level", 1.0, "two_r")
    assert outcome.valid and outcome.filled
    assert outcome.exit_reason == "STOP"
    assert outcome.gross_bps < 0


def test_unfilled_pending_order_occupies_global_slot() -> None:
    rows = [
        {"event_id": "a", "symbol": "BTCUSDT", "decision_time": 1.0, "priority": 3.0,
         "outcome": {"filled": False, "slot_release_time": 3.0}},
        {"event_id": "b", "symbol": "ETHUSDT", "decision_time": 2.0, "priority": 5.0,
         "outcome": {"filled": True, "slot_release_time": 4.0}},
        {"event_id": "c", "symbol": "ETHUSDT", "decision_time": 3.0, "priority": 1.0,
         "outcome": {"filled": True, "slot_release_time": 5.0}},
    ]
    assert [row["event_id"] for row in run.route(rows)] == ["c"]


def test_top_event_removal_is_counterfactual_keyed() -> None:
    trades = [
        {"gross_bps": 40.0, "event_id": "a"},
        {"gross_bps": 20.0, "event_id": "b"},
        {"gross_bps": -5.0, "event_id": "c"},
    ]
    assert run.top_exclusions(trades) == {"a"}
