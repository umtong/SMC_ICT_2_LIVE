from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from system.coarse import CoarseEventReplay, CoarseExecutionConfig  # noqa: E402
from system.core import EventCandidate, EventFamily, RiskConfig  # noqa: E402
from system.model import ScoredCandidate  # noqa: E402
from system.policy import GlobalSlotPolicy  # noqa: E402


def _execution_frame(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    starts = pd.to_datetime([row[0] for row in rows])
    return pd.DataFrame(
        {
            "bar_start": starts,
            "open": [row[1] for row in rows],
            "high": [row[2] for row in rows],
            "low": [row[3] for row in rows],
            "close": [row[4] for row in rows],
            "mark_close": [row[4] for row in rows],
            "spread_bps": 0.0,
        },
        index=starts + pd.Timedelta(minutes=1),
    )


def _event() -> EventCandidate:
    return EventCandidate(
        pd.Timestamp("2023-01-01T00:00:00Z"),
        "BTCUSDT",
        EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        1,
        100.0,
        100.0,
        90.0,
        130.0,
        95.0,
        {},
    )


def _replay(frame: pd.DataFrame):
    event = _event()
    scored = ScoredCandidate(event, 0.7, 1.0, 0.1, 0.01, 0.01)
    return CoarseEventReplay(
        {"BTCUSDT": frame},
        CoarseExecutionConfig(
            maker_fee_rate=0.0,
            taker_fee_rate=0.0,
            market_slippage_bps=0.0,
            stop_slippage_bps=0.0,
            minimum_spread_bps=0.0,
        ),
    ).run(
        [scored],
        GlobalSlotPolicy(0.55),
        RiskConfig(0.01, 5.0, 0.001),
        pd.Timestamp("2023-01-01T00:00:00Z"),
        pd.Timestamp("2023-01-02T00:00:00Z"),
    )


def test_marketable_entry_guard_rejects_gap_through_stop() -> None:
    account = _replay(_execution_frame([("2023-01-01T00:01:00Z", 89.0, 90.0, 88.0, 89.0)]))
    assert account.fills == []
    assert account.closed_trades == []
    assert account.position is None


def test_position_sizing_uses_expected_actual_entry_fill() -> None:
    account = _replay(
        _execution_frame(
            [
                ("2023-01-01T00:01:00Z", 110.0, 111.0, 109.0, 110.0),
                ("2023-01-01T00:02:00Z", 110.0, 131.0, 109.0, 130.0),
            ]
        )
    )
    assert len(account.fills) == 2
    assert account.fills[0].price == 110.0
    assert account.fills[0].quantity == 5.0
