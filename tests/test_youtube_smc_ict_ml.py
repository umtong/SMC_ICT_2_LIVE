from __future__ import annotations

import math

import numpy as np
import pandas as pd

from research.youtube_smc_ict_ml.system import (
    Candidate,
    FeeExecutionConfig,
    StructuralConfig,
    SymbolData,
    _confirmed_pivots,
    build_trade_plans,
    ceil_to_minute_ms,
    plans_frame,
    run_single_slot_backtest,
    simulate_candidate_plan,
)

MIN = 60_000


def make_symbol_data(symbol: str, rows: list[dict], funding: pd.DataFrame | None = None) -> SymbolData:
    minute = pd.DataFrame(rows)
    minute["observed"] = True
    minute["available_at_ms"] = minute["start_time_ms"] + MIN
    five = pd.DataFrame(
        {
            "start_time_ms": [rows[0]["start_time_ms"]],
            "open": [rows[0]["open"]],
            "high": [max(row["high"] for row in rows)],
            "low": [min(row["low"] for row in rows)],
            "close": [rows[-1]["close"]],
            "volume": [sum(row.get("volume", 1.0) for row in rows)],
            "turnover": [sum(row.get("turnover", row["close"]) for row in rows)],
            "is_complete": [True],
            "available_at_ms": [rows[0]["start_time_ms"] + 5 * MIN],
        }
    )
    return SymbolData(symbol=symbol, minute=minute, five_minute=five, funding=funding if funding is not None else pd.DataFrame())


def candidate(
    *,
    cid: str = "c1",
    symbol: str = "BTCUSDT",
    direction: int = 1,
    activation_ms: int = 30_500,
    mode: str = "confirmation_market",
    entry: float = 100.0,
    stop: float = 95.0,
    target: float = 110.0,
) -> Candidate:
    return Candidate(
        candidate_id=cid,
        setup_id=cid.split(":")[0],
        symbol=symbol,
        direction=direction,
        signal_available_ms=activation_ms - 500,
        activation_ms=activation_ms,
        entry_mode=mode,
        planned_entry=entry,
        stop_price=stop,
        target_price=target,
        liquidity_source="confirmed_swing",
        target_source="prior_day",
        feature_values={
            "symbol": symbol,
            "entry_mode": mode,
            "liquidity_source": "confirmed_swing",
            "target_source": "prior_day",
            "direction": direction,
            "rr": 2.0,
        },
    )


def test_confirmed_pivot_is_not_visible_before_right_span() -> None:
    highs = np.array([1.0, 2.0, 5.0, 3.0, 2.0, 1.0])
    lows = np.array([0.0, 0.5, 1.0, 0.6, 0.4, 0.3])
    atr = np.ones_like(highs)
    swing_high, _, _, _ = _confirmed_pivots(
        highs, lows, atr, left=2, right=2, equal_tolerance_atr=0.1
    )
    assert np.isnan(swing_high[3])
    assert swing_high[4] == 5.0


def test_latency_uses_first_full_minute_after_500ms() -> None:
    assert ceil_to_minute_ms(300_000 + 500) == 360_000
    assert ceil_to_minute_ms(300_000) == 300_000


def test_same_minute_stop_and_target_resolves_stop_first() -> None:
    rows = [
        {"start_time_ms": 60_000, "open": 100.0, "high": 111.0, "low": 94.0, "close": 105.0, "volume": 1.0, "turnover": 1000.0},
        {"start_time_ms": 120_000, "open": 105.0, "high": 106.0, "low": 104.0, "close": 105.0, "volume": 1.0, "turnover": 1000.0},
    ]
    data = make_symbol_data("BTCUSDT", rows)
    plan = simulate_candidate_plan(candidate(), data, FeeExecutionConfig(), end_exclusive_ms=180_000)
    assert plan.executed
    assert plan.exit_reason == "stop"
    assert plan.net_r is not None and plan.net_r < 0


def test_limit_order_cancels_when_structure_invalidates_before_fill() -> None:
    rows = [
        {"start_time_ms": 60_000, "open": 101.0, "high": 102.0, "low": 94.0, "close": 95.0, "volume": 1.0, "turnover": 1000.0},
        {"start_time_ms": 120_000, "open": 95.0, "high": 96.0, "low": 93.0, "close": 94.0, "volume": 1.0, "turnover": 1000.0},
    ]
    data = make_symbol_data("BTCUSDT", rows)
    plan = simulate_candidate_plan(
        candidate(mode="fvg_ob_limit", entry=98.0, stop=95.0, target=110.0),
        data,
        FeeExecutionConfig(),
        end_exclusive_ms=180_000,
    )
    assert not plan.executed
    assert plan.resolved
    assert plan.order_status == "canceled_structure_invalidated"


def test_global_slot_selects_highest_score_and_blocks_overlap() -> None:
    rows = [
        {"start_time_ms": 60_000, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 2.0, "turnover": 10000.0},
        {"start_time_ms": 120_000, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 2.0, "turnover": 10000.0},
        {"start_time_ms": 180_000, "open": 100.0, "high": 111.0, "low": 99.0, "close": 110.0, "volume": 2.0, "turnover": 10000.0},
        {"start_time_ms": 240_000, "open": 110.0, "high": 111.0, "low": 109.0, "close": 110.0, "volume": 2.0, "turnover": 10000.0},
    ]
    btc = make_symbol_data("BTCUSDT", rows)
    c1 = candidate(cid="lower", activation_ms=30_500, target=110.0)
    c2 = candidate(cid="higher", activation_ms=30_500, target=110.0)
    plans = build_trade_plans([c1, c2], {"BTCUSDT": btc}, FeeExecutionConfig(), end_exclusive_ms=300_000)
    frame = plans_frame(plans)
    frame["score"] = frame["candidate_id"].map({"lower": 0.1, "higher": 0.9})
    result = run_single_slot_backtest(
        frame,
        {plan.candidate.candidate_id: plan for plan in plans},
        {"BTCUSDT": btc},
        FeeExecutionConfig(impact_coefficient_bps=0.0),
        start_ms=0,
        end_exclusive_ms=300_000,
        risk_fraction=0.01,
        score_threshold=0.0,
        initial_nav=10_000.0,
    )
    assert result.selected_orders == 1
    assert result.trades.iloc[0]["candidate_id"] == "higher"
    assert result.executed_trades == 1


def test_daily_geometric_growth_counts_no_trade_days() -> None:
    rows = [
        {"start_time_ms": day * 86_400_000, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0, "turnover": 10000.0}
        for day in range(3)
    ]
    btc = make_symbol_data("BTCUSDT", rows)
    empty = pd.DataFrame(columns=["activation_ms", "score", "candidate_id"])
    result = run_single_slot_backtest(
        empty,
        {},
        {"BTCUSDT": btc},
        FeeExecutionConfig(),
        start_ms=0,
        end_exclusive_ms=3 * 86_400_000,
        risk_fraction=0.01,
        score_threshold=0.0,
        initial_nav=10_000.0,
    )
    assert len(result.daily_nav) == 3
    assert result.terminal_nav == 10_000.0
    assert math.isclose(result.daily_geometric_growth, 0.0, abs_tol=1e-12)
