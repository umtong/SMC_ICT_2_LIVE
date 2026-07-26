from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from .core import RiskConfig, size_position_from_nav
from .execution import AccountState, DailyNavRecord, ExecutionConfig, ExecutionEngine, Position, validate_tape
from .model import ScoredCandidate
from .policy import GlobalSlotPolicy, PolicyDecision


@dataclass(frozen=True)
class PositionSnapshot:
    timestamp: pd.Timestamp
    symbol: str
    side: int
    quantity: float
    average_entry_price: float
    closed_at: pd.Timestamp | None = None


class EventTapeGlobalReplay:
    """One-slot chronological replay over sub-minute event tapes.

    Only the tape for the currently pending/open symbol is traversed. Candidate
    decisions are processed after all tape rows visible at the same timestamp, and
    every new order still activates after ``ExecutionConfig.activation_latency_ms``.
    """

    def __init__(
        self,
        tape_by_symbol: Mapping[str, pd.DataFrame],
        config: ExecutionConfig = ExecutionConfig(),
    ) -> None:
        self.config = config
        self.engine = ExecutionEngine(config)
        self.tapes = {symbol: validate_tape(frame) for symbol, frame in tape_by_symbol.items()}
        self.time_ns = {symbol: frame.index.asi8 for symbol, frame in self.tapes.items()}
        self.cursors = {symbol: 0 for symbol in self.tapes}

    def _rows_until(self, symbol: str, end_inclusive: pd.Timestamp):
        frame = self.tapes[symbol]
        start = self.cursors[symbol]
        end = int(np.searchsorted(self.time_ns[symbol], end_inclusive.value, side="right"))
        self.cursors[symbol] = max(start, end)
        return frame.iloc[start:end].iterrows()

    def _mark_asof(self, symbol: str, timestamp: pd.Timestamp) -> float:
        values = self.time_ns[symbol]
        position = int(np.searchsorted(values, timestamp.value, side="right")) - 1
        if position < 0:
            position = 0
        return float(self.tapes[symbol].iloc[min(position, len(self.tapes[symbol]) - 1)]["mark"])

    def run(
        self,
        scored_candidates: Sequence[ScoredCandidate],
        policy: GlobalSlotPolicy,
        risk: RiskConfig,
        evaluation_start: pd.Timestamp,
        evaluation_end_exclusive: pd.Timestamp,
        initial_nav: float = 10000.0,
        funding: Mapping[tuple[str, pd.Timestamp], float] | None = None,
        instrument_rules: Mapping[str, tuple[float, float]] | None = None,
    ) -> AccountState:
        account = AccountState(initial_nav)
        funding = funding or {}
        instrument_rules = instrument_rules or {}
        groups: dict[pd.Timestamp, list[ScoredCandidate]] = {}
        for scored in scored_candidates:
            if evaluation_start <= scored.candidate.timestamp < evaluation_end_exclusive:
                groups.setdefault(scored.candidate.timestamp, []).append(scored)
        for symbol in self.tapes:
            self.cursors[symbol] = int(np.searchsorted(self.time_ns[symbol], evaluation_start.value, side="left"))
        cash_history: list[tuple[pd.Timestamp, float]] = [(evaluation_start, float(initial_nav))]
        snapshots: list[PositionSnapshot] = []
        active_symbol: str | None = None

        def process_active(end_inclusive: pd.Timestamp) -> None:
            nonlocal active_symbol
            if active_symbol is None:
                return
            for timestamp, row in self._rows_until(active_symbol, end_inclusive):
                before_cash = float(account.cash)
                before = account.position
                before_state = (before.quantity, before.average_entry_price) if before is not None else None
                self.engine.process_entry_row(account, timestamp, row)
                if (active_symbol, timestamp) in funding:
                    self.engine.apply_funding(account, timestamp, float(row["mark"]), float(funding[(active_symbol, timestamp)]))
                self.engine.process_position_row(account, timestamp, row)
                if account.pending_entry is not None:
                    candidate = account.pending_entry.candidate
                    side = candidate.side
                    invalidated = float(row["mark"]) <= candidate.stop_reference if side > 0 else float(row["mark"]) >= candidate.stop_reference
                    target_passed = float(row["last"]) >= candidate.target_reference if side > 0 else float(row["last"]) <= candidate.target_reference
                    if invalidated or target_passed:
                        self.engine.cancel_pending(account, "structural invalidation before fill")
                after = account.position
                if float(account.cash) != before_cash:
                    cash_history.append((timestamp, float(account.cash)))
                if after is not None and (
                    before_state is None
                    or after.quantity != before_state[0]
                    or after.average_entry_price != before_state[1]
                ):
                    snapshots.append(PositionSnapshot(timestamp, active_symbol, after.side, after.open_quantity, after.average_entry_price))
                if before is not None and after is None:
                    snapshots.append(PositionSnapshot(timestamp, active_symbol, before.side, 0.0, before.average_entry_price, timestamp))
                if account.slot_available():
                    active_symbol = None
                    break
                if account.invalid:
                    break

        for decision_time in sorted(groups):
            if active_symbol is not None:
                process_active(decision_time)
            if account.invalid:
                break
            selected = policy.choose(groups[decision_time], account.slot_available())
            if selected.scored is None or selected.action == PolicyDecision.ABSTAIN:
                continue
            candidate = selected.scored.candidate
            if candidate.symbol not in self.tapes:
                continue
            step, minimum = instrument_rules.get(candidate.symbol, (risk.quantity_step, risk.minimum_quantity))
            symbol_risk = replace(risk, quantity_step=float(step), minimum_quantity=float(minimum))
            entry_fee_rate = self.config.maker_fee_rate if selected.action == PolicyDecision.PASSIVE_RETEST else self.config.taker_fee_rate
            quantity = size_position_from_nav(
                float(account.cash),
                candidate,
                symbol_risk,
                entry_fee_rate,
                self.config.taker_fee_rate,
                self.config.base_slippage_bps / 10000 if selected.action == PolicyDecision.MARKETABLE else 0.0,
                self.config.base_slippage_bps / 10000,
            )
            if quantity <= 0:
                continue
            self.engine.submit_entry(account, candidate, selected.action, quantity)
            self.cursors[candidate.symbol] = max(
                self.cursors[candidate.symbol],
                int(np.searchsorted(self.time_ns[candidate.symbol], decision_time.value, side="right")),
            )
            active_symbol = candidate.symbol

        if active_symbol is not None and not account.invalid:
            process_active(evaluation_end_exclusive - pd.Timedelta(nanoseconds=1))

        cash_history.sort(key=lambda item: item[0])
        snapshots.sort(key=lambda item: item.timestamp)
        cash_index = 0
        snapshot_index = 0
        cash = float(initial_nav)
        active_snapshot: PositionSnapshot | None = None
        for day_end in pd.date_range(
            evaluation_start.floor("D") + pd.Timedelta(days=1),
            evaluation_end_exclusive,
            freq="1D",
            tz="UTC",
        ):
            while cash_index < len(cash_history) and cash_history[cash_index][0] <= day_end:
                cash = cash_history[cash_index][1]
                cash_index += 1
            while snapshot_index < len(snapshots) and snapshots[snapshot_index].timestamp <= day_end:
                snapshot = snapshots[snapshot_index]
                active_snapshot = None if snapshot.quantity <= 0 else snapshot
                snapshot_index += 1
            unrealized = 0.0
            symbol = None
            quantity = 0.0
            if active_snapshot is not None:
                symbol = active_snapshot.symbol
                quantity = active_snapshot.quantity
                mark = self._mark_asof(symbol, day_end)
                unrealized = active_snapshot.side * quantity * (mark - active_snapshot.average_entry_price)
            account.daily_nav.append(DailyNavRecord(day_end, cash + unrealized, cash, unrealized, symbol, quantity))
        return account
