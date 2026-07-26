from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from .core import EventCandidate, RiskConfig, size_position_from_nav
from .execution import AccountState, ClosedTrade, DailyNavRecord, ExitReason, FillRecord
from .model import ScoredCandidate
from .policy import GlobalSlotPolicy, PolicyDecision


@dataclass(frozen=True)
class CoarseExecutionConfig:
    activation_latency_ms: int = 500
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.00055
    market_slippage_bps: float = 2.0
    stop_slippage_bps: float = 4.0
    passive_requires_trade_through: bool = True
    minimum_spread_bps: float = 0.5


@dataclass(frozen=True)
class CoarseLabel:
    event_start: pd.Timestamp
    entry_time: pd.Timestamp | None
    event_end: pd.Timestamp | None
    target_before_stop: int | None
    net_r: float | None
    passive_filled: int
    status: str


def _basis_time(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if "bar_start" in frame.columns:
        return pd.DatetimeIndex(pd.to_datetime(frame["bar_start"], utc=True))
    return frame.index


def validate_execution_bars(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"execution bars missing: {sorted(missing)}")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("execution bar index must be timezone-aware")
    result = frame.copy().sort_index()
    for column in required | ({"mark_close", "spread_bps"} & set(result.columns)):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["bar_start"] = _basis_time(result)
    if result["bar_start"].duplicated().any():
        raise ValueError("duplicate execution bar starts")
    return result.sort_values("bar_start", kind="stable")


def _spread_fraction(row: pd.Series, config: CoarseExecutionConfig) -> float:
    spread_bps = row.get("spread_bps")
    if pd.isna(spread_bps):
        spread_bps = config.minimum_spread_bps
    return max(float(spread_bps), config.minimum_spread_bps) / 10000


def _market_fill(open_price: float, side: int, row: pd.Series, slippage_bps: float, config: CoarseExecutionConfig) -> float:
    cost = _spread_fraction(row, config) / 2 + slippage_bps / 10000
    return open_price * (1 + side * cost)


class CoarseLabeler:
    """Array-backed conservative first-passage labeler for one symbol."""

    def __init__(self, bars: pd.DataFrame, config: CoarseExecutionConfig = CoarseExecutionConfig()) -> None:
        self.config = config
        self.data = validate_execution_bars(bars)
        self.times = pd.DatetimeIndex(self.data["bar_start"])
        self.available_times = pd.DatetimeIndex(self.data.index)
        self.time_ns = self.times.as_unit("ns").asi8
        self.open = self.data["open"].to_numpy(dtype=float)
        self.high = self.data["high"].to_numpy(dtype=float)
        self.low = self.data["low"].to_numpy(dtype=float)
        self.close = self.data["close"].to_numpy(dtype=float)

    @staticmethod
    def _first_true(values: np.ndarray) -> int | None:
        positions = np.flatnonzero(values)
        return int(positions[0]) if positions.size else None

    def label(self, candidate: EventCandidate, passive: bool) -> CoarseLabel:
        activation = candidate.timestamp + pd.Timedelta(milliseconds=self.config.activation_latency_ms)
        start_position = int(np.searchsorted(self.time_ns, activation.value, side="right"))
        if start_position >= len(self.data):
            return CoarseLabel(candidate.timestamp, None, None, None, None, 0, "UNRESOLVED_NO_EXECUTION_BAR")

        side = candidate.side
        entry_fee_rate = self.config.taker_fee_rate
        passive_filled = 0
        if passive:
            if side > 0:
                invalidated = self.low[start_position:] <= candidate.stop_reference
                reached_target = self.high[start_position:] >= candidate.target_reference
                crossed = self.low[start_position:] < candidate.entry_reference
            else:
                invalidated = self.high[start_position:] >= candidate.stop_reference
                reached_target = self.low[start_position:] <= candidate.target_reference
                crossed = self.high[start_position:] > candidate.entry_reference
            first_event = self._first_true(invalidated | reached_target | crossed)
            if first_event is None:
                return CoarseLabel(candidate.timestamp, None, None, None, None, 0, "UNRESOLVED_NO_FILL")
            entry_position = start_position + first_event
            if invalidated[first_event] or reached_target[first_event]:
                return CoarseLabel(candidate.timestamp, None, self.available_times[entry_position], None, None, 0, "CANCELLED_BEFORE_FILL")
            entry_price = candidate.entry_reference
            entry_fee_rate = self.config.maker_fee_rate
            passive_filled = 1
        else:
            entry_position = start_position
            entry_price = _market_fill(
                self.open[entry_position],
                side,
                self.data.iloc[entry_position],
                self.config.market_slippage_bps,
                self.config,
            )

        entry_time = self.available_times[entry_position] if passive else self.times[entry_position]
        stop_distance = abs(entry_price - candidate.stop_reference)
        if stop_distance <= 0:
            return CoarseLabel(candidate.timestamp, entry_time, entry_time, 0, -1.0, passive_filled, "INVALID_STOP")

        if side > 0:
            stop_hit = self.low[entry_position:] <= candidate.stop_reference
            target_hit = self.high[entry_position:] >= candidate.target_reference
        else:
            stop_hit = self.high[entry_position:] >= candidate.stop_reference
            target_hit = self.low[entry_position:] <= candidate.target_reference
        first_barrier = self._first_true(stop_hit | target_hit)
        if first_barrier is None:
            return CoarseLabel(candidate.timestamp, entry_time, None, None, None, passive_filled, "UNRESOLVED_CENSORED")
        exit_position = entry_position + first_barrier
        exit_time = self.available_times[exit_position]
        if stop_hit[first_barrier]:
            stop_price = candidate.stop_reference * (
                1 - self.config.stop_slippage_bps / 10000
                if side > 0
                else 1 + self.config.stop_slippage_bps / 10000
            )
            gross = side * (stop_price - entry_price)
            fees = entry_price * entry_fee_rate + stop_price * self.config.taker_fee_rate
            return CoarseLabel(candidate.timestamp, entry_time, exit_time, 0, (gross - fees) / stop_distance, passive_filled, "STOP")
        target_price = candidate.target_reference
        gross = side * (target_price - entry_price)
        fees = entry_price * entry_fee_rate + target_price * self.config.maker_fee_rate
        return CoarseLabel(candidate.timestamp, entry_time, exit_time, 1, (gross - fees) / stop_distance, passive_filled, "TARGET")


def label_candidate_on_bars(
    candidate: EventCandidate,
    bars: pd.DataFrame,
    passive: bool,
    config: CoarseExecutionConfig = CoarseExecutionConfig(),
) -> CoarseLabel:
    return CoarseLabeler(bars, config).label(candidate, passive)


@dataclass
class _CoarseOpenPosition:
    candidate: EventCandidate
    quantity: float
    entry_price: float
    entry_time: pd.Timestamp
    entry_fee: float
    entry_equity: float
    funding_pnl: float = 0.0


@dataclass
class _CoarsePending:
    scored: ScoredCandidate
    action: PolicyDecision
    quantity: float
    activation: pd.Timestamp


class CoarseGlobalReplay:
    """Conservative 1-minute global-slot account screen."""

    def __init__(self, config: CoarseExecutionConfig = CoarseExecutionConfig()) -> None:
        self.config = config

    def run(
        self,
        bars_by_symbol: Mapping[str, pd.DataFrame],
        scored_candidates: Sequence[ScoredCandidate],
        policy: GlobalSlotPolicy,
        risk: RiskConfig,
        initial_nav: float = 10000.0,
        funding: Mapping[tuple[str, pd.Timestamp], float] | None = None,
        instrument_rules: Mapping[str, tuple[float, float]] | None = None,
    ) -> AccountState:
        prepared = {symbol: validate_execution_bars(frame) for symbol, frame in bars_by_symbol.items()}
        account = AccountState(initial_nav)
        candidates_by_time: dict[pd.Timestamp, list[ScoredCandidate]] = {}
        for candidate in scored_candidates:
            candidates_by_time.setdefault(candidate.candidate.timestamp, []).append(candidate)
        decision_times = sorted(candidates_by_time)
        bars_by_start: dict[pd.Timestamp, list[tuple[str, pd.Series]]] = {}
        for symbol, frame in prepared.items():
            for _, row in frame.iterrows():
                bars_by_start.setdefault(pd.Timestamp(row["bar_start"]), []).append((symbol, row))
        timeline = sorted(set(decision_times) | set(bars_by_start))
        pending: _CoarsePending | None = None
        position: _CoarseOpenPosition | None = None
        funding = funding or {}
        instrument_rules = instrument_rules or {}
        last_mark: dict[str, float] = {}
        last_day: pd.Timestamp | None = None

        def account_nav(mark: float | None = None) -> float:
            if position is None:
                return float(account.cash)
            use_mark = mark if mark is not None else last_mark.get(position.candidate.symbol, position.entry_price)
            return float(account.cash) + position.candidate.side * position.quantity * (use_mark - position.entry_price)

        for timestamp in timeline:
            day = timestamp.floor("D")
            if last_day is not None and day > last_day:
                mark = last_mark.get(position.candidate.symbol, position.entry_price) if position else 0.0
                unrealized = account_nav(mark) - float(account.cash)
                account.daily_nav.append(
                    DailyNavRecord(day, account_nav(mark), float(account.cash), unrealized, position.candidate.symbol if position else None, position.quantity if position else 0.0)
                )
            last_day = day

            for symbol, row in bars_by_start.get(timestamp, []):
                mark = float(row.get("mark_close", row["close"]))
                last_mark[symbol] = mark

                if pending is not None and pending.scored.candidate.symbol == symbol and timestamp > pending.activation:
                    candidate = pending.scored.candidate
                    side = candidate.side
                    if pending.action == PolicyDecision.MARKETABLE:
                        entry = _market_fill(float(row["open"]), side, row, self.config.market_slippage_bps, self.config)
                        fee = pending.quantity * entry * self.config.taker_fee_rate
                        account.cash = float(account.cash) - fee
                        account.fills.append(FillRecord(timestamp, symbol, "ENTRY", side, pending.quantity, entry, fee, "taker"))
                        position = _CoarseOpenPosition(candidate, pending.quantity, entry, timestamp, fee, account_nav())
                        pending = None
                    else:
                        invalidated = row["low"] <= candidate.stop_reference if side > 0 else row["high"] >= candidate.stop_reference
                        reached_target = row["high"] >= candidate.target_reference if side > 0 else row["low"] <= candidate.target_reference
                        crossed = row["low"] < candidate.entry_reference if side > 0 else row["high"] > candidate.entry_reference
                        if invalidated or reached_target:
                            pending = None
                        elif crossed:
                            entry = candidate.entry_reference
                            fee = pending.quantity * entry * self.config.maker_fee_rate
                            account.cash = float(account.cash) - fee
                            account.fills.append(FillRecord(timestamp, symbol, "ENTRY", side, pending.quantity, entry, fee, "maker"))
                            position = _CoarseOpenPosition(candidate, pending.quantity, entry, timestamp, fee, account_nav())
                            pending = None

                if position is not None and position.candidate.symbol == symbol:
                    candidate = position.candidate
                    side = candidate.side
                    rate = funding.get((symbol, timestamp))
                    if rate is not None:
                        funding_pnl = -side * position.quantity * mark * float(rate)
                        position.funding_pnl += funding_pnl
                        account.cash = float(account.cash) + funding_pnl
                    stop_hit = row["low"] <= candidate.stop_reference if side > 0 else row["high"] >= candidate.stop_reference
                    target_hit = row["high"] >= candidate.target_reference if side > 0 else row["low"] <= candidate.target_reference
                    reason: ExitReason | None = None
                    liquidity = "taker"
                    if stop_hit:
                        exit_price = candidate.stop_reference * (1 - self.config.stop_slippage_bps / 10000 if side > 0 else 1 + self.config.stop_slippage_bps / 10000)
                        fee_rate = self.config.taker_fee_rate
                        reason = ExitReason.STOP
                    elif target_hit:
                        exit_price = candidate.target_reference
                        fee_rate = self.config.maker_fee_rate
                        liquidity = "maker"
                        reason = ExitReason.TARGET
                    if reason is not None:
                        fee = position.quantity * exit_price * fee_rate
                        exit_pnl = side * position.quantity * (exit_price - position.entry_price) - fee
                        account.cash = float(account.cash) + exit_pnl
                        account.fills.append(FillRecord(timestamp, symbol, reason.value, -side, position.quantity, exit_price, fee, liquidity))
                        net_pnl = exit_pnl + position.funding_pnl - position.entry_fee
                        stop_budget = position.quantity * abs(position.entry_price - candidate.stop_reference)
                        account.closed_trades.append(
                            ClosedTrade(
                                symbol,
                                candidate.family.value,
                                side,
                                position.entry_time,
                                timestamp,
                                position.quantity,
                                position.entry_price,
                                reason.value,
                                net_pnl,
                                net_pnl / max(position.entry_equity, 1e-12),
                                net_pnl / max(stop_budget, 1e-12),
                            )
                        )
                        position = None

            if timestamp in candidates_by_time:
                slot_available = pending is None and position is None and not account.invalid
                selected = policy.choose(candidates_by_time[timestamp], slot_available=slot_available)
                if selected.scored is not None and selected.action != PolicyDecision.ABSTAIN:
                    candidate = selected.scored.candidate
                    current_mark = last_mark.get(candidate.symbol, candidate.decision_price)
                    nav = account_nav(current_mark)
                    step, minimum = instrument_rules.get(candidate.symbol, (risk.quantity_step, risk.minimum_quantity))
                    symbol_risk = replace(risk, quantity_step=float(step), minimum_quantity=float(minimum))
                    quantity = size_position_from_nav(
                        nav,
                        candidate,
                        symbol_risk,
                        self.config.taker_fee_rate if selected.action == PolicyDecision.MARKETABLE else self.config.maker_fee_rate,
                        self.config.taker_fee_rate,
                        self.config.market_slippage_bps / 10000,
                        self.config.stop_slippage_bps / 10000,
                    )
                    if quantity > 0:
                        pending = _CoarsePending(selected.scored, selected.action, quantity, timestamp + pd.Timedelta(milliseconds=self.config.activation_latency_ms))

        if position is not None:
            from .execution import Position

            account.position = Position(position.candidate, position.candidate.side, position.quantity, position.entry_price, position.entry_time, position.entry_fee, position.entry_equity, funding_pnl=position.funding_pnl)
        return account


@dataclass(frozen=True)
class CoarseOutcome:
    decision_time: pd.Timestamp
    entry_time: pd.Timestamp | None
    end_time: pd.Timestamp | None
    status: str
    entry_price: float | None
    exit_price: float | None
    entry_fee_rate: float
    exit_fee_rate: float | None
    entry_liquidity: str | None
    exit_liquidity: str | None


@dataclass(frozen=True)
class CoarsePositionInterval:
    candidate: EventCandidate
    quantity: float
    entry_time: pd.Timestamp
    end_time: pd.Timestamp | None
    entry_price: float
    entry_fee: float
    entry_equity: float
    funding_pnl: float


def _outcome_from_labeler(labeler: CoarseLabeler, candidate: EventCandidate, passive: bool) -> CoarseOutcome:
    config = labeler.config
    activation = candidate.timestamp + pd.Timedelta(milliseconds=config.activation_latency_ms)
    start_position = int(np.searchsorted(labeler.time_ns, activation.value, side="right"))
    if start_position >= len(labeler.data):
        return CoarseOutcome(candidate.timestamp, None, None, "UNRESOLVED_NO_EXECUTION_BAR", None, None, 0.0, None, None, None)
    side = candidate.side
    if passive:
        if side > 0:
            invalidated = labeler.low[start_position:] <= candidate.stop_reference
            reached_target = labeler.high[start_position:] >= candidate.target_reference
            crossed = labeler.low[start_position:] < candidate.entry_reference
        else:
            invalidated = labeler.high[start_position:] >= candidate.stop_reference
            reached_target = labeler.low[start_position:] <= candidate.target_reference
            crossed = labeler.high[start_position:] > candidate.entry_reference
        first_event = labeler._first_true(invalidated | reached_target | crossed)
        if first_event is None:
            return CoarseOutcome(candidate.timestamp, None, None, "UNRESOLVED_NO_FILL", None, None, 0.0, None, None, None)
        entry_position = start_position + first_event
        if invalidated[first_event] or reached_target[first_event]:
            return CoarseOutcome(candidate.timestamp, None, labeler.available_times[entry_position], "CANCELLED_BEFORE_FILL", None, None, 0.0, None, None, None)
        entry_price = candidate.entry_reference
        entry_fee_rate = config.maker_fee_rate
        entry_liquidity = "maker"
    else:
        entry_position = start_position
        entry_price = _market_fill(labeler.open[entry_position], side, labeler.data.iloc[entry_position], config.market_slippage_bps, config)
        entry_fee_rate = config.taker_fee_rate
        entry_liquidity = "taker"
    entry_time = labeler.available_times[entry_position] if passive else labeler.times[entry_position]
    if side > 0:
        stop_hit = labeler.low[entry_position:] <= candidate.stop_reference
        target_hit = labeler.high[entry_position:] >= candidate.target_reference
    else:
        stop_hit = labeler.high[entry_position:] >= candidate.stop_reference
        target_hit = labeler.low[entry_position:] <= candidate.target_reference
    first_barrier = labeler._first_true(stop_hit | target_hit)
    if first_barrier is None:
        return CoarseOutcome(candidate.timestamp, entry_time, None, "UNRESOLVED_CENSORED", entry_price, None, entry_fee_rate, None, entry_liquidity, None)
    exit_position = entry_position + first_barrier
    end_time = labeler.available_times[exit_position]
    if stop_hit[first_barrier]:
        exit_price = candidate.stop_reference * (1 - config.stop_slippage_bps / 10000 if side > 0 else 1 + config.stop_slippage_bps / 10000)
        return CoarseOutcome(candidate.timestamp, entry_time, end_time, "STOP", entry_price, exit_price, entry_fee_rate, config.taker_fee_rate, entry_liquidity, "taker")
    return CoarseOutcome(candidate.timestamp, entry_time, end_time, "TARGET", entry_price, candidate.target_reference, entry_fee_rate, config.maker_fee_rate, entry_liquidity, "maker")


def _mark_at(labeler: CoarseLabeler, timestamp: pd.Timestamp) -> float:
    position = int(np.searchsorted(labeler.time_ns, timestamp.value, side="left")) - 1
    if position < 0:
        position = 0
    row = labeler.data.iloc[min(position, len(labeler.data) - 1)]
    return float(row.get("mark_close", row["close"]))


class CoarseEventReplay:
    """Fast event-level global-slot account replay for coarse economic screening."""

    def __init__(
        self,
        bars_by_symbol: Mapping[str, pd.DataFrame],
        config: CoarseExecutionConfig = CoarseExecutionConfig(),
    ) -> None:
        self.config = config
        self.labelers = {symbol: CoarseLabeler(frame, config) for symbol, frame in bars_by_symbol.items()}
        self._outcome_cache: dict[tuple[tuple[object, ...], bool], CoarseOutcome] = {}

    @staticmethod
    def _identity(candidate: EventCandidate) -> tuple[object, ...]:
        return (
            candidate.timestamp,
            candidate.symbol,
            candidate.family.value,
            candidate.side,
            candidate.entry_reference,
            candidate.stop_reference,
            candidate.target_reference,
        )

    def outcome(self, candidate: EventCandidate, passive: bool) -> CoarseOutcome:
        key = (self._identity(candidate), passive)
        if key not in self._outcome_cache:
            self._outcome_cache[key] = _outcome_from_labeler(self.labelers[candidate.symbol], candidate, passive)
        return self._outcome_cache[key]

    def _funding_events(
        self,
        funding: Mapping[tuple[str, pd.Timestamp], float],
        symbol: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> list[tuple[pd.Timestamp, float]]:
        return sorted(
            (timestamp, float(rate))
            for (event_symbol, timestamp), rate in funding.items()
            if event_symbol == symbol and start <= timestamp < end
        )

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
        grouped: dict[pd.Timestamp, list[ScoredCandidate]] = {}
        for scored in scored_candidates:
            if evaluation_start <= scored.candidate.timestamp < evaluation_end_exclusive:
                grouped.setdefault(scored.candidate.timestamp, []).append(scored)
        cash = float(initial_nav)
        cash_events: list[tuple[pd.Timestamp, float]] = []
        intervals: list[CoarsePositionInterval] = []
        slot_release = evaluation_start
        open_interval: CoarsePositionInterval | None = None

        for decision_time in sorted(grouped):
            if decision_time < slot_release or open_interval is not None:
                continue
            selected = policy.choose(grouped[decision_time], slot_available=True)
            if selected.scored is None or selected.action == PolicyDecision.ABSTAIN:
                continue
            candidate = selected.scored.candidate
            passive = selected.action == PolicyDecision.PASSIVE_RETEST
            outcome = self.outcome(candidate, passive)
            if outcome.entry_time is None:
                if outcome.end_time is None:
                    slot_release = evaluation_end_exclusive
                else:
                    slot_release = min(outcome.end_time, evaluation_end_exclusive)
                continue
            assert outcome.entry_price is not None
            step, minimum = instrument_rules.get(candidate.symbol, (risk.quantity_step, risk.minimum_quantity))
            symbol_risk = replace(risk, quantity_step=float(step), minimum_quantity=float(minimum))
            quantity = size_position_from_nav(
                cash,
                candidate,
                symbol_risk,
                outcome.entry_fee_rate,
                self.config.taker_fee_rate,
                self.config.market_slippage_bps / 10000 if not passive else 0.0,
                self.config.stop_slippage_bps / 10000,
            )
            if quantity <= 0:
                slot_release = decision_time
                continue
            entry_equity = cash
            entry_fee = quantity * outcome.entry_price * outcome.entry_fee_rate
            cash -= entry_fee
            cash_events.append((outcome.entry_time, -entry_fee))
            account.fills.append(FillRecord(outcome.entry_time, candidate.symbol, "ENTRY", candidate.side, quantity, outcome.entry_price, entry_fee, outcome.entry_liquidity or "unknown"))
            interval_end = outcome.end_time if outcome.end_time is not None else evaluation_end_exclusive
            funding_pnl = 0.0
            for timestamp, rate in self._funding_events(funding, candidate.symbol, outcome.entry_time, interval_end):
                payment = -candidate.side * quantity * _mark_at(self.labelers[candidate.symbol], timestamp) * rate
                funding_pnl += payment
                cash += payment
                cash_events.append((timestamp, payment))
            interval = CoarsePositionInterval(candidate, quantity, outcome.entry_time, outcome.end_time, outcome.entry_price, entry_fee, entry_equity, funding_pnl)
            intervals.append(interval)
            if outcome.end_time is None or outcome.exit_price is None or outcome.exit_fee_rate is None:
                open_interval = interval
                slot_release = evaluation_end_exclusive
                break
            exit_fee = quantity * outcome.exit_price * outcome.exit_fee_rate
            gross = candidate.side * quantity * (outcome.exit_price - outcome.entry_price)
            exit_delta = gross - exit_fee
            cash += exit_delta
            cash_events.append((outcome.end_time, exit_delta))
            account.fills.append(FillRecord(outcome.end_time, candidate.symbol, outcome.status, -candidate.side, quantity, outcome.exit_price, exit_fee, outcome.exit_liquidity or "unknown"))
            net_pnl = gross - entry_fee - exit_fee + funding_pnl
            stop_budget = quantity * abs(outcome.entry_price - candidate.stop_reference)
            account.closed_trades.append(
                ClosedTrade(
                    candidate.symbol,
                    candidate.family.value,
                    candidate.side,
                    outcome.entry_time,
                    outcome.end_time,
                    quantity,
                    outcome.entry_price,
                    outcome.status,
                    net_pnl,
                    net_pnl / max(entry_equity, 1e-12),
                    net_pnl / max(stop_budget, 1e-12),
                )
            )
            slot_release = outcome.end_time

        account.cash = cash
        if open_interval is not None:
            from .execution import Position

            account.position = Position(
                open_interval.candidate,
                open_interval.candidate.side,
                open_interval.quantity,
                open_interval.entry_price,
                open_interval.entry_time,
                open_interval.entry_fee,
                open_interval.entry_equity,
                funding_pnl=open_interval.funding_pnl,
            )

        cash_events.sort(key=lambda item: item[0])
        day_ends = pd.date_range(
            evaluation_start.floor("D") + pd.Timedelta(days=1),
            evaluation_end_exclusive,
            freq="1D",
            tz="UTC",
        )
        running_cash = float(initial_nav)
        cash_index = 0
        for day_end in day_ends:
            while cash_index < len(cash_events) and cash_events[cash_index][0] <= day_end:
                running_cash += cash_events[cash_index][1]
                cash_index += 1
            active = next(
                (
                    interval
                    for interval in intervals
                    if interval.entry_time <= day_end and (interval.end_time is None or day_end < interval.end_time)
                ),
                None,
            )
            unrealized = 0.0
            symbol = None
            quantity = 0.0
            if active is not None:
                mark = _mark_at(self.labelers[active.candidate.symbol], day_end)
                unrealized = active.candidate.side * active.quantity * (mark - active.entry_price)
                symbol = active.candidate.symbol
                quantity = active.quantity
            account.daily_nav.append(DailyNavRecord(day_end, running_cash + unrealized, running_cash, unrealized, symbol, quantity))
        return account
