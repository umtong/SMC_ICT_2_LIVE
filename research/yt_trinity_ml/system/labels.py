from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .core import EventCandidate
from .execution import AccountState, ExecutionConfig, ExecutionEngine, ExitReason, validate_tape
from .policy import PolicyDecision


@dataclass(frozen=True)
class EventLabel:
    event_start: pd.Timestamp
    event_end: pd.Timestamp | None
    target_before_stop: int | None
    net_r: float | None
    passive_filled: int
    status: str


def label_first_passage(
    candidate: EventCandidate,
    tape: pd.DataFrame,
    passive_entry: bool,
    config: ExecutionConfig = ExecutionConfig(),
) -> EventLabel:
    """Replay one action on the event tape without an elapsed-time exit.

    Passive labels use the same resting-side queue, aggressor direction, partial
    fill, fee and target/stop logic as account replay. A target/stop reached before
    any passive fill is an observed no-fill cancellation; an order still pending at
    the data boundary is censored rather than converted to a zero-return sample.
    """
    data = validate_tape(tape)
    active = data.loc[
        data.index >= candidate.timestamp + pd.Timedelta(milliseconds=config.activation_latency_ms)
    ]
    if active.empty:
        return EventLabel(candidate.timestamp, None, None, None, 0, "UNRESOLVED_NO_ACTIVE_TAPE")

    account = AccountState(1_000_000.0)
    engine = ExecutionEngine(config)
    action = PolicyDecision.PASSIVE_RETEST if passive_entry else PolicyDecision.MARKETABLE
    engine.submit_entry(account, candidate, action, 1.0)
    ever_filled = 0

    for timestamp, row in active.iterrows():
        engine.process_entry_row(account, timestamp, row)
        if account.position is not None:
            ever_filled = 1
            engine.process_position_row(account, timestamp, row)
            if account.closed_trades:
                trade = account.closed_trades[-1]
                target = int(trade.exit_reason == ExitReason.TARGET.value)
                return EventLabel(
                    candidate.timestamp,
                    trade.closed_at,
                    target,
                    trade.net_r,
                    ever_filled,
                    trade.exit_reason,
                )
            continue

        if account.pending_entry is not None:
            side = candidate.side
            invalidated = float(row["mark"]) <= candidate.stop_reference if side > 0 else float(row["mark"]) >= candidate.stop_reference
            target_passed = float(row["last"]) >= candidate.target_reference if side > 0 else float(row["last"]) <= candidate.target_reference
            if invalidated or target_passed:
                engine.cancel_pending(account, "barrier reached before passive fill")
                return EventLabel(candidate.timestamp, timestamp, None, None, ever_filled, "CANCELLED_BEFORE_FILL")

    status = "UNRESOLVED_CENSORED" if ever_filled else "UNRESOLVED_NO_FILL"
    return EventLabel(candidate.timestamp, None, None, None, ever_filled, status)
