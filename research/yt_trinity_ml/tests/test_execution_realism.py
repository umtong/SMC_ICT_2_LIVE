from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from system.core import EventCandidate, EventFamily  # noqa: E402
from system.execution import AccountState, ExecutionConfig, ExecutionEngine  # noqa: E402
from system.policy import PolicyDecision  # noqa: E402


def _candidate(*, entry: float = 100.0, stop: float = 90.0, target: float = 110.0) -> EventCandidate:
    return EventCandidate(
        timestamp=pd.Timestamp("2023-01-01T00:00:00Z"),
        symbol="BTCUSDT",
        family=EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        side=1,
        decision_price=entry,
        entry_reference=entry,
        stop_reference=stop,
        target_reference=target,
        structural_level=95.0,
        feature_row={},
    )


def test_long_passive_queue_uses_bid_depth_not_ask_depth() -> None:
    engine = ExecutionEngine(
        ExecutionConfig(
            activation_latency_ms=500,
            maker_fee_rate=0.0,
            taker_fee_rate=0.0,
            base_slippage_bps=0.0,
            passive_queue_multiple=1.0,
            passive_through_fraction_at_touch=0.0,
        )
    )
    account = AccountState(1000.0)
    engine.submit_entry(account, _candidate(), PolicyDecision.PASSIVE_RETEST, 1.0)
    row = pd.Series(
        {
            "bid": 99.9,
            "ask": 100.1,
            "last": 99.9,
            "mark": 100.0,
            "trade_volume": 11.0,
            "bid_size": 10.0,
            "ask_size": 1000.0,
        }
    )
    engine.process_entry_row(account, pd.Timestamp("2023-01-01T00:00:01Z"), row)
    assert account.position is not None
    assert account.position.quantity == 1.0
    assert account.fills[-1].liquidity == "maker"


def test_target_touch_exits_marketable_instead_of_assuming_full_maker_fill() -> None:
    engine = ExecutionEngine(
        ExecutionConfig(
            activation_latency_ms=500,
            maker_fee_rate=0.0,
            taker_fee_rate=0.0,
            base_slippage_bps=0.0,
        )
    )
    account = AccountState(1000.0)
    engine.submit_entry(account, _candidate(), PolicyDecision.MARKETABLE, 1.0)
    entry_row = pd.Series(
        {
            "bid": 99.0,
            "ask": 100.0,
            "last": 100.0,
            "mark": 100.0,
            "trade_volume": 10.0,
            "bid_size": 100.0,
            "ask_size": 100.0,
        }
    )
    engine.process_entry_row(account, pd.Timestamp("2023-01-01T00:00:01Z"), entry_row)
    assert account.position is not None

    target_row = pd.Series(
        {
            "bid": 109.0,
            "ask": 110.0,
            "last": 110.0,
            "mark": 110.0,
            "trade_volume": 10.0,
            "bid_size": 100.0,
            "ask_size": 100.0,
        }
    )
    engine.process_position_row(account, pd.Timestamp("2023-01-01T00:00:02Z"), target_row)
    assert account.position is None
    assert account.fills[-1].role == "TARGET"
    assert account.fills[-1].liquidity == "taker"
    assert account.fills[-1].price == 109.0
