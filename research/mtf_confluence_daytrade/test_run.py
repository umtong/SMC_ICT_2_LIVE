from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MODULE = Path(__file__).with_name("run.py")
spec = importlib.util.spec_from_file_location("mtf_confluence_core", MODULE)
core = importlib.util.module_from_spec(spec)
sys.modules["mtf_confluence_core"] = core
assert spec.loader is not None
spec.loader.exec_module(core)


def candidate(**overrides):
    row = dict(
        candidate_id="c0", symbol="BTCUSDT", side=1,
        decision_ms=core.START_MS + 300_000,
        activation_ms=core.START_MS + 300_500,
        entry_ms=core.START_MS + 360_000,
        entry=100.0, stop=90.0, target1=110.0, target2=120.0,
        target1_level_id="t1", target2_level_id="t2",
        zone_1h_kind="FVG", zone_15m_kind="ENGULF_OB",
        overlap_lower=95.0, overlap_upper=100.0,
        touch_ms=core.START_MS + 300_000,
        response_kind="ENGULF", bias_1h=1, bias_4h=1, bias_1d=0,
        bias_strength=2, risk_per_unit_before_cost=10.0, raw_rr=1.0,
        confluence_score=7.0,
    )
    row.update(overrides)
    return core.Candidate(**row)


def outcome(cid: str, *, pnl: float, exit_offset: int = 600_000):
    return core.Outcome(
        candidate_id=cid, management="FULL_TARGET", status="TARGET1",
        entry_ms=core.START_MS + 360_000, exit_ms=core.START_MS + exit_offset,
        entry=100.0, stop=90.0, target1=110.0, target2=120.0,
        gross_pnl_per_unit=pnl, funding_pnl_per_unit=0.0,
        fee_slippage_per_unit=0.0, net_pnl_per_unit=pnl,
        planned_loss_per_unit=10.0, net_r=pnl / 10.0,
        hold_minutes=(exit_offset - 360_000) / 60_000,
        legs=((core.START_MS + exit_offset, 1.0, 110.0, "TARGET1"),),
    )


def test_engulfing_requires_opposite_previous_body_and_full_coverage():
    frame = pd.DataFrame({
        "open": [10.0, 9.0, 9.5], "high": [11.0, 12.0, 11.0],
        "low": [8.0, 8.0, 9.0], "close": [9.0, 11.0, 10.5],
    })
    assert core._engulfing(frame, 1).tolist() == [False, True, False]


def test_confirmed_pivot_is_not_available_at_pivot_bar():
    frame = pd.DataFrame({"high": [1, 2, 5, 2, 1], "low": [0, -1, -2, -1, 0]})
    high, low = core.confirmed_pivots(frame, 2, 2)
    assert np.isnan(high[2]) and high[4] == 5
    assert np.isnan(low[2]) and low[4] == -2


def test_fixed_500ms_uses_first_later_minute():
    times = np.asarray([60_000, 120_000, 180_000], dtype=np.int64)
    assert int(np.searchsorted(times, 120_500, side="right")) == 2


def test_consumed_target_is_timestamped_at_first_trade_through():
    created = np.asarray([100], dtype=np.int64)
    price = np.asarray([105.0])
    side = np.asarray([1], dtype=np.int8)
    times = np.asarray([100, 200, 300], dtype=np.int64)
    high = np.asarray([104.0, 104.5, 106.0])
    low = np.asarray([99.0, 100.0, 103.0])
    consumed = core._first_level_consumption(created, price, side, times, high, low)
    assert consumed.tolist() == [300]


def test_same_minute_stop_and_target_is_stop_first():
    c = candidate()
    bars = pd.DataFrame({
        "start_time_ms": [c.entry_ms], "open": [100.0], "high": [115.0],
        "low": [85.0], "close": [100.0],
    })
    funding = pd.DataFrame(columns=["timestamp_ms", "funding_rate"])
    result = core.simulate_outcome(c, bars, funding, np.asarray([], dtype=np.int64), "FULL_TARGET", 0.0, c.entry_ms + 60_000)
    assert result.status == "STOP"
    assert result.gross_pnl_per_unit == -10.0


def test_global_slot_chooses_one_same_time_candidate():
    first = candidate(candidate_id="high", confluence_score=9.0)
    second = candidate(candidate_id="low", symbol="ETHUSDT", confluence_score=5.0)
    outcomes = {"high": outcome("high", pnl=10.0), "low": outcome("low", pnl=10.0)}
    summary, trades, _ = core.route_account([second, first], outcomes, {}, core.Config())
    assert summary["completed_trades"] == 1
    assert trades["candidate_id"].tolist() == ["high"]
