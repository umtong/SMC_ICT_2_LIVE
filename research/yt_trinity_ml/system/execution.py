from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from .core import EventCandidate
from .policy import PolicyDecision


class OrderState(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ExitReason(str, Enum):
    TARGET = "TARGET"
    STOP = "STOP"
    STRUCTURAL_INVALIDATION = "STRUCTURAL_INVALIDATION"
    LIQUIDATION = "LIQUIDATION"
    END_MARK = "END_MARK"


@dataclass(frozen=True)
class ExecutionConfig:
    activation_latency_ms: int = 500
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.00055
    base_slippage_bps: float = 0.5
    impact_bps_per_one_percent_depth: float = 1.0
    passive_queue_multiple: float = 1.0
    passive_through_fraction_at_touch: float = 0.0
    liquidation_fee_rate: float = 0.005
    maintenance_margin_fraction: float = 0.005
    liquidation_buffer_fraction: float = 0.0025


@dataclass
class EntryOrder:
    candidate: EventCandidate
    decision: PolicyDecision
    quantity: float
    created_at: pd.Timestamp
    activated_at: pd.Timestamp
    limit_price: float | None
    state: OrderState = OrderState.PENDING
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    fees: float = 0.0
    queue_ahead: float = 0.0

    @property
    def remaining_quantity(self) -> float:
        return max(0.0, self.quantity - self.filled_quantity)


@dataclass
class Position:
    candidate: EventCandidate
    side: int
    quantity: float
    average_entry_price: float
    opened_at: pd.Timestamp
    entry_fees: float
    entry_equity: float
    realized_pnl: float = 0.0
    funding_pnl: float = 0.0
    closed_quantity: float = 0.0
    closed_at: pd.Timestamp | None = None
    exit_reason: ExitReason | None = None

    @property
    def open_quantity(self) -> float:
        return max(0.0, self.quantity - self.closed_quantity)

    @property
    def effective_leverage(self) -> float:
        return self.quantity * self.average_entry_price / max(self.entry_equity, 1e-12)


@dataclass(frozen=True)
class FillRecord:
    timestamp: pd.Timestamp
    symbol: str
    role: str
    side: int
    quantity: float
    price: float
    fee: float
    liquidity: str


@dataclass(frozen=True)
class ClosedTrade:
    symbol: str
    family: str
    side: int
    opened_at: pd.Timestamp
    closed_at: pd.Timestamp
    quantity: float
    average_entry_price: float
    exit_reason: str
    net_pnl: float
    net_return_on_entry_equity: float
    net_r: float


@dataclass(frozen=True)
class DailyNavRecord:
    day_end_utc: pd.Timestamp
    nav: float
    cash: float
    unrealized_pnl: float
    position_symbol: str | None
    position_quantity: float


@dataclass
class AccountState:
    initial_nav: float
    cash: float | None = None
    pending_entry: EntryOrder | None = None
    position: Position | None = None
    fills: list[FillRecord] = field(default_factory=list)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    daily_nav: list[DailyNavRecord] = field(default_factory=list)
    invalid: bool = False
    invalid_reason: str | None = None

    def __post_init__(self) -> None:
        if self.initial_nav <= 0:
            raise ValueError("initial_nav must be positive")
        if self.cash is None:
            self.cash = float(self.initial_nav)

    def slot_available(self) -> bool:
        return self.pending_entry is None and self.position is None and not self.invalid


REQUIRED_TAPE_COLUMNS = {"bid", "ask", "last", "mark", "trade_volume"}


def validate_tape(tape: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_TAPE_COLUMNS - set(tape.columns)
    if missing:
        raise ValueError(f"event tape missing columns: {sorted(missing)}")
    if not isinstance(tape.index, pd.DatetimeIndex) or tape.index.tz is None:
        raise ValueError("event tape index must be timezone-aware DatetimeIndex")
    if not tape.index.is_monotonic_increasing or tape.index.has_duplicates:
        raise ValueError("event tape timestamps must be unique and increasing")
    result = tape.copy()
    numeric = REQUIRED_TAPE_COLUMNS | ({"bid_size", "ask_size", "aggressor_side"} & set(tape.columns))
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if (result["ask"] < result["bid"]).any():
        raise ValueError("ask must be >= bid")
    return result


class ExecutionEngine:
    def __init__(self, config: ExecutionConfig = ExecutionConfig()) -> None:
        self.config = config

    def submit_entry(
        self,
        account: AccountState,
        candidate: EventCandidate,
        decision: PolicyDecision,
        quantity: float,
    ) -> EntryOrder:
        if not account.slot_available():
            raise RuntimeError("global pending/open entry slot is occupied")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if decision == PolicyDecision.ABSTAIN:
            raise ValueError("cannot submit an abstain decision")
        created = candidate.timestamp
        activated = created + pd.Timedelta(milliseconds=self.config.activation_latency_ms)
        order = EntryOrder(
            candidate=candidate,
            decision=decision,
            quantity=float(quantity),
            created_at=created,
            activated_at=activated,
            limit_price=candidate.entry_reference if decision == PolicyDecision.PASSIVE_RETEST else None,
        )
        account.pending_entry = order
        return order

    def _impact_bps(self, quantity: float, displayed_depth: float | None) -> float:
        if displayed_depth is None or not np.isfinite(displayed_depth) or displayed_depth <= 0:
            return self.config.base_slippage_bps
        ratio_percent = 100 * quantity / displayed_depth
        return self.config.base_slippage_bps + self.config.impact_bps_per_one_percent_depth * ratio_percent

    def _market_price(self, row: pd.Series, side: int, quantity: float) -> float:
        depth = row.get("ask_size") if side > 0 else row.get("bid_size")
        base = float(row["ask"] if side > 0 else row["bid"])
        impact = self._impact_bps(quantity, float(depth) if pd.notna(depth) else None) / 10000
        return base * (1 + side * impact)

    def _record_entry_fill(
        self,
        account: AccountState,
        order: EntryOrder,
        timestamp: pd.Timestamp,
        quantity: float,
        price: float,
        liquidity: str,
    ) -> None:
        if quantity <= 0:
            return
        pre_fill_nav = float(account.cash)
        if account.position is not None:
            position = account.position
            pre_fill_nav += position.side * position.open_quantity * (price - position.average_entry_price)
        fee_rate = self.config.maker_fee_rate if liquidity == "maker" else self.config.taker_fee_rate
        fee = quantity * price * fee_rate
        new_total = order.filled_quantity + quantity
        order.average_fill_price = (
            order.average_fill_price * order.filled_quantity + price * quantity
        ) / new_total
        order.filled_quantity = new_total
        order.fees += fee
        order.state = OrderState.FILLED if order.remaining_quantity <= 1e-12 else OrderState.PARTIALLY_FILLED
        account.cash = float(account.cash) - fee
        account.fills.append(
            FillRecord(timestamp, order.candidate.symbol, "ENTRY", order.candidate.side, quantity, price, fee, liquidity)
        )
        if account.position is None:
            account.position = Position(
                candidate=order.candidate,
                side=order.candidate.side,
                quantity=quantity,
                average_entry_price=price,
                opened_at=timestamp,
                entry_fees=fee,
                entry_equity=max(pre_fill_nav, 1e-12),
            )
        else:
            position = account.position
            total = position.quantity + quantity
            position.average_entry_price = (
                position.average_entry_price * position.quantity + price * quantity
            ) / total
            position.quantity = total
            position.entry_fees += fee
            position.entry_equity = max(position.entry_equity, pre_fill_nav)
        if order.state == OrderState.FILLED:
            account.pending_entry = None

    def process_entry_row(self, account: AccountState, timestamp: pd.Timestamp, row: pd.Series) -> None:
        order = account.pending_entry
        if order is None or timestamp < order.activated_at or order.state in {OrderState.CANCELLED, OrderState.REJECTED, OrderState.FILLED}:
            return
        side = order.candidate.side
        remaining = order.remaining_quantity
        if order.decision == PolicyDecision.MARKETABLE:
            price = self._market_price(row, side, remaining)
            self._record_entry_fill(account, order, timestamp, remaining, price, "taker")
            return

        assert order.limit_price is not None
        limit = order.limit_price
        last = float(row["last"])
        trade_volume = max(0.0, float(row.get("trade_volume", 0.0)))
        displayed = row.get("ask_size") if side > 0 else row.get("bid_size")
        if order.queue_ahead <= 0:
            displayed_value = float(displayed) if pd.notna(displayed) else remaining
            order.queue_ahead = max(remaining, displayed_value * self.config.passive_queue_multiple)

        touched = last <= limit if side > 0 else last >= limit
        crossed = last < limit if side > 0 else last > limit
        if not touched:
            return
        eligible_volume = trade_volume if crossed else trade_volume * self.config.passive_through_fraction_at_touch
        consumed = max(0.0, eligible_volume - order.queue_ahead)
        order.queue_ahead = max(0.0, order.queue_ahead - eligible_volume)
        fill_quantity = min(remaining, consumed)
        if fill_quantity > 0:
            self._record_entry_fill(account, order, timestamp, fill_quantity, limit, "maker")

    def cancel_pending(self, account: AccountState, reason: str = "strategy invalidation") -> None:
        if account.pending_entry is not None:
            account.pending_entry.state = OrderState.CANCELLED
            account.pending_entry = None

    def _close_quantity(
        self,
        account: AccountState,
        timestamp: pd.Timestamp,
        row: pd.Series,
        quantity: float,
        reason: ExitReason,
        passive_target: bool,
    ) -> None:
        position = account.position
        if position is None or quantity <= 0:
            return
        quantity = min(quantity, position.open_quantity)
        exit_side = -position.side
        if passive_target:
            price = position.candidate.target_reference
            liquidity = "maker"
            fee_rate = self.config.maker_fee_rate
        else:
            price = self._market_price(row, exit_side, quantity)
            liquidity = "taker"
            fee_rate = self.config.taker_fee_rate
        fee = quantity * price * fee_rate
        pnl = position.side * quantity * (price - position.average_entry_price) - fee
        position.realized_pnl += pnl
        position.closed_quantity += quantity
        account.cash = float(account.cash) + pnl
        account.fills.append(
            FillRecord(timestamp, position.candidate.symbol, reason.value, exit_side, quantity, price, fee, liquidity)
        )
        if position.open_quantity <= 1e-12:
            position.closed_at = timestamp
            position.exit_reason = reason
            net_pnl = position.realized_pnl + position.funding_pnl - position.entry_fees
            stop_budget = position.quantity * abs(position.average_entry_price - position.candidate.stop_reference)
            account.closed_trades.append(
                ClosedTrade(
                    symbol=position.candidate.symbol,
                    family=position.candidate.family.value,
                    side=position.side,
                    opened_at=position.opened_at,
                    closed_at=timestamp,
                    quantity=position.quantity,
                    average_entry_price=position.average_entry_price,
                    exit_reason=reason.value,
                    net_pnl=net_pnl,
                    net_return_on_entry_equity=net_pnl / max(position.entry_equity, 1e-12),
                    net_r=net_pnl / max(stop_budget, 1e-12),
                )
            )
            account.position = None

    def _liquidation_price(self, position: Position) -> float | None:
        leverage = position.effective_leverage
        if leverage <= 0:
            return None
        adverse_fraction = 1 / leverage - self.config.maintenance_margin_fraction - self.config.liquidation_buffer_fraction
        if adverse_fraction >= 1 and position.side > 0:
            return 0.0
        if adverse_fraction <= 0:
            return position.average_entry_price
        return position.average_entry_price * (1 - adverse_fraction if position.side > 0 else 1 + adverse_fraction)

    def process_position_row(
        self,
        account: AccountState,
        timestamp: pd.Timestamp,
        row: pd.Series,
        structural_invalidation: bool = False,
    ) -> None:
        position = account.position
        if position is None:
            return
        side = position.side
        mark = float(row["mark"])
        stop = position.candidate.stop_reference
        target = position.candidate.target_reference

        stop_hit = mark <= stop if side > 0 else mark >= stop
        target_hit = float(row["last"]) >= target if side > 0 else float(row["last"]) <= target
        liquidation_price = self._liquidation_price(position)
        liquidated = False
        if liquidation_price is not None:
            liquidated = mark <= liquidation_price if side > 0 else mark >= liquidation_price
        if liquidated and not stop_hit:
            open_quantity = position.open_quantity
            notional = open_quantity * mark
            self._close_quantity(account, timestamp, row, open_quantity, ExitReason.LIQUIDATION, False)
            account.cash = float(account.cash) - notional * self.config.liquidation_fee_rate
            account.invalid = True
            account.invalid_reason = "liquidation reached before strategy exit"
            return
        if stop_hit:
            self._close_quantity(account, timestamp, row, position.open_quantity, ExitReason.STOP, False)
            return
        if structural_invalidation:
            self._close_quantity(account, timestamp, row, position.open_quantity, ExitReason.STRUCTURAL_INVALIDATION, False)
            return
        if target_hit:
            self._close_quantity(account, timestamp, row, position.open_quantity, ExitReason.TARGET, True)

    def apply_funding(self, account: AccountState, timestamp: pd.Timestamp, mark_price: float, funding_rate: float) -> None:
        position = account.position
        if position is None:
            return
        funding_pnl = -position.side * position.open_quantity * mark_price * funding_rate
        position.funding_pnl += funding_pnl
        account.cash = float(account.cash) + funding_pnl
        account.fills.append(
            FillRecord(timestamp, position.candidate.symbol, "FUNDING", 0, position.open_quantity, mark_price, -funding_pnl, "funding")
        )

    def mark_nav(self, account: AccountState, mark_price: float) -> tuple[float, float]:
        unrealized = 0.0
        if account.position is not None:
            position = account.position
            unrealized = position.side * position.open_quantity * (mark_price - position.average_entry_price)
        return float(account.cash) + unrealized, unrealized

    def record_utc_day_end(self, account: AccountState, day_end: pd.Timestamp, mark_price: float) -> DailyNavRecord:
        if day_end.tz is None:
            raise ValueError("day_end must be timezone aware")
        nav, unrealized = self.mark_nav(account, mark_price)
        position = account.position
        record = DailyNavRecord(
            day_end,
            nav,
            float(account.cash),
            unrealized,
            position.candidate.symbol if position else None,
            position.open_quantity if position else 0.0,
        )
        account.daily_nav.append(record)
        return record

    def replay(
        self,
        account: AccountState,
        tape: pd.DataFrame,
        funding_by_timestamp: Mapping[pd.Timestamp, float] | None = None,
        invalidation_timestamps: Iterable[pd.Timestamp] = (),
    ) -> AccountState:
        data = validate_tape(tape)
        funding = funding_by_timestamp or {}
        invalidations = set(invalidation_timestamps)
        last_day: pd.Timestamp | None = None
        previous_mark: float | None = None
        for timestamp, row in data.iterrows():
            day = timestamp.floor("D")
            if last_day is not None and day > last_day and previous_mark is not None:
                self.record_utc_day_end(account, day, previous_mark)
            last_day = day
            self.process_entry_row(account, timestamp, row)
            if timestamp in funding:
                self.apply_funding(account, timestamp, float(row["mark"]), float(funding[timestamp]))
            self.process_position_row(account, timestamp, row, timestamp in invalidations)
            previous_mark = float(row["mark"])
            if account.invalid:
                break
        return account
