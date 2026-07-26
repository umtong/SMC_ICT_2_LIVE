from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import run


def synthetic_day(hit_target: bool = True) -> run.DayData:
    n = run.SECONDS_PER_DAY
    mid = np.full(n, 100.0)
    high = np.full(n, 100.10)
    low = np.full(n, 99.90)
    total = np.full(n, 1_000_000.0)
    signed = np.zeros(n)
    liq_buy = np.zeros(n)
    liq_sell = np.zeros(n)
    bid_amount = np.full(n, 100.0)
    ask_amount = np.full(n, 100.0)

    mid[400] = 99.75
    low[400] = 99.70
    high[400] = 99.95
    signed[400] = -700_000.0
    liq_sell[400] = 2_000_000.0
    mid[401] = 100.02
    low[401] = 99.80
    high[401] = 100.20
    signed[401] = 800_000.0
    liq_sell[401] = 500_000.0
    bid_amount[401] = 160.0
    if hit_target:
        high[403] = 101.0
        mid[403] = 100.8
        mid[404] = 100.8

    quote_ts = np.arange(n, dtype=float) + 0.10
    quote_bid = mid - 0.01
    quote_ask = mid + 0.01
    quote_bid_amount = bid_amount.copy()
    quote_ask_amount = ask_amount.copy()
    trade_ts = np.arange(n, dtype=float) + 0.50
    trade_price = mid.copy()
    return run.DayData(
        "BTCUSDT", "1970-01-01", 0.0,
        mid, high, low, total, signed, liq_buy, liq_sell,
        bid_amount, ask_amount,
        quote_ts, quote_bid, quote_ask, quote_bid_amount, quote_ask_amount,
        trade_ts, trade_price,
    )


def test_parameter_grid_and_stable_ids() -> None:
    grid = list(run.parameter_grid())
    assert len(grid) == 768
    assert run.candidate_id(grid[0]) == run.candidate_id(dict(grid[0]))


def test_timestamp_normalization_and_funding_boundaries() -> None:
    values = pd.Series([1_700_000_000_000_000, 1_700_000_001_000_000])
    seconds = run.normalize_seconds(values)
    assert abs(seconds[1] - seconds[0] - 1.0) < 1e-9
    assert run.funding_boundaries(1.0, 28_801.0) == 1


def test_liquidation_sweep_reclaim_mss_is_causal() -> None:
    day = synthetic_day()
    events = run.extract_events(day)
    candidates = [e for e in events if e["sweep_second"] == 400 and e["sweep_direction"] == -1]
    assert candidates
    event = candidates[0]
    assert event["decision_second"] == 401
    assert event["trade_direction"] == 1
    assert math.isclose(event["sweep_extreme"], 99.70)
    assert event["liq_notional"] == 2_500_000.0
    assert event["flow_flip"] > 0
    assert event["refill_ratio"] > 1

    future_changed = synthetic_day()
    future_changed.low[900] = 50.0
    future_changed.high[900] = 150.0
    event2 = [e for e in run.extract_events(future_changed) if e["event_id"] == event["event_id"]][0]
    for key in ("decision_second", "sweep_extreme", "liq_notional", "flow_flip", "refill_ratio"):
        assert event2[key] == event[key]


def test_outcome_uses_post_decision_quote_and_structural_exit() -> None:
    day = synthetic_day()
    event = [e for e in run.extract_events(day) if e["sweep_second"] == 400 and e["sweep_direction"] == -1][0]
    outcome = run.make_outcome(day, event, 100, "two_r")
    assert outcome.valid
    assert outcome.entry_time >= event["decision_time"] + 0.1
    assert outcome.exit_reason == "TARGET"
    assert outcome.gross_bps > 0


def test_terminal_boundary_is_full_stop_not_disappearing_trade() -> None:
    day = synthetic_day(hit_target=False)
    event = [e for e in run.extract_events(day) if e["sweep_second"] == 400 and e["sweep_direction"] == -1][0]
    outcome = run.make_outcome(day, event, 100, "two_r")
    assert outcome.valid
    assert outcome.unresolved
    assert outcome.exit_reason == "TERMINAL_FULL_STOP"
    assert outcome.gross_bps < 0


def test_global_slot_and_counterfactual_exclusion() -> None:
    fake = [
        {"event_id": "a", "decision_time": 1.0, "priority": 2.0, "symbol": "BTCUSDT", "outcome": {"exit_time": 3.0}},
        {"event_id": "b", "decision_time": 1.0, "priority": 1.0, "symbol": "ETHUSDT", "outcome": {"exit_time": 2.0}},
        {"event_id": "c", "decision_time": 2.0, "priority": 3.0, "symbol": "ETHUSDT", "outcome": {"exit_time": 4.0}},
    ]
    assert [row["event_id"] for row in run.route(fake)] == ["a"]
