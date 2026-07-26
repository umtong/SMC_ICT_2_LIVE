from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .core import EventCandidate
from .execution import ExecutionConfig, validate_tape


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
    """Label a structural event without an elapsed-time exit.

    The label is unresolved at the available-data boundary when neither target nor
    stop is reached. A same-timestamp target/stop collision is stop-first.
    """
    data = validate_tape(tape)
    active = data.loc[data.index >= candidate.timestamp + pd.Timedelta(milliseconds=config.activation_latency_ms)]
    if active.empty:
        return EventLabel(candidate.timestamp, None, None, None, 0, "UNRESOLVED_NO_ACTIVE_TAPE")

    side = candidate.side
    entry_price: float | None = None
    entry_time: pd.Timestamp | None = None
    passive_filled = 0
    for timestamp, row in active.iterrows():
        if passive_entry:
            crossed = float(row["last"]) < candidate.entry_reference if side > 0 else float(row["last"]) > candidate.entry_reference
            if not crossed:
                continue
            entry_price = candidate.entry_reference
            passive_filled = 1
        else:
            entry_price = float(row["ask"] if side > 0 else row["bid"])
        entry_time = timestamp
        break
    if entry_price is None or entry_time is None:
        return EventLabel(candidate.timestamp, None, None, None, 0, "UNRESOLVED_NO_FILL")

    stop = candidate.stop_reference
    target = candidate.target_reference
    stop_distance = abs(entry_price - stop)
    if stop_distance <= 0:
        raise ValueError("nonpositive stop distance")
    future = active.loc[active.index >= entry_time]
    for timestamp, row in future.iterrows():
        mark = float(row["mark"])
        last = float(row["last"])
        stop_hit = mark <= stop if side > 0 else mark >= stop
        target_hit = last >= target if side > 0 else last <= target
        if stop_hit:
            exit_price = float(row["bid"] if side > 0 else row["ask"])
            gross = side * (exit_price - entry_price)
            fees = entry_price * config.taker_fee_rate + exit_price * config.taker_fee_rate
            return EventLabel(candidate.timestamp, timestamp, 0, (gross - fees) / stop_distance, passive_filled, "STOP")
        if target_hit:
            exit_price = target
            entry_fee = config.maker_fee_rate if passive_entry else config.taker_fee_rate
            fees = entry_price * entry_fee + exit_price * config.maker_fee_rate
            gross = side * (exit_price - entry_price)
            return EventLabel(candidate.timestamp, timestamp, 1, (gross - fees) / stop_distance, passive_filled, "TARGET")
    return EventLabel(candidate.timestamp, None, None, None, passive_filled, "UNRESOLVED_CENSORED")
