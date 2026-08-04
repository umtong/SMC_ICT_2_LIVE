from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

import pandas as pd

from scripts.market_data import load_canonical_bybit as canonical
from scripts.market_data import load_public_trade_compact_v5 as compact_v5

from .contracts import Bar


class CanonicalDataContractError(RuntimeError):
    """Raised when canonical market data cannot support a causal LRDS decision."""


_REQUIRED_BAR_COLUMNS = (
    "start_time_ms",
    "available_at_ms",
    "open",
    "high",
    "low",
    "close",
)


@dataclass(frozen=True, slots=True)
class CanonicalBarAudit:
    total_rows: int
    emitted_rows: int
    future_rows: int
    missing_rows: int
    incomplete_rows: int


@dataclass(frozen=True, slots=True)
class ExactExecutionObservation:
    activation_time_ms: int
    trade_time_ms: int
    price: float
    half_start_time_ms: int
    side_is_unambiguous_buy: bool

    def __post_init__(self) -> None:
        if self.trade_time_ms < self.activation_time_ms:
            raise CanonicalDataContractError("execution precedes fixed-latency activation")
        if not math.isfinite(self.price) or self.price <= 0.0:
            raise CanonicalDataContractError("execution price must be finite and positive")


class CanonicalDecisionStream:
    """Causal completed-bar view over one canonical trade-bar frame.

    The canonical grid keeps missing periods explicit. LRDS preserves their original
    positional indices but never turns an unobserved, incomplete or not-yet-available
    row into market evidence.
    """

    def __init__(self, frame: pd.DataFrame) -> None:
        missing = set(_REQUIRED_BAR_COLUMNS).difference(frame.columns)
        if missing:
            raise CanonicalDataContractError(
                f"canonical trade bars lack required columns: {sorted(missing)}"
            )
        ordered = frame.sort_values("start_time_ms", kind="stable").reset_index(drop=True)
        if ordered["start_time_ms"].duplicated().any():
            raise CanonicalDataContractError("canonical trade bars contain duplicate starts")
        starts = ordered["start_time_ms"].astype("int64")
        available = ordered["available_at_ms"].astype("int64")
        if not starts.is_monotonic_increasing:
            raise CanonicalDataContractError("canonical trade-bar starts are not monotonic")
        if (available < starts).any():
            raise CanonicalDataContractError("information availability precedes bar start")
        self._frame = ordered

    @classmethod
    def load(
        cls,
        root: str | Path,
        segment: str,
        symbol: str,
        timeframe: str,
    ) -> "CanonicalDecisionStream":
        return cls(canonical.load_trade_bar(root, segment, symbol, timeframe))

    @property
    def total_rows(self) -> int:
        return len(self._frame)

    def visible(self, decision_time_ms: int) -> tuple[tuple[Bar, ...], CanonicalBarAudit]:
        if decision_time_ms < 0:
            raise ValueError("decision time cannot be negative")
        emitted: list[Bar] = []
        future = missing = incomplete = 0
        for index, row in self._frame.iterrows():
            if int(row["available_at_ms"]) > int(decision_time_ms):
                future += 1
                continue
            if "observed" in self._frame.columns and not bool(row["observed"]):
                missing += 1
                continue
            if "source_available" in self._frame.columns and not bool(row["source_available"]):
                missing += 1
                continue
            if "is_complete" in self._frame.columns and not bool(row["is_complete"]):
                incomplete += 1
                continue
            prices = tuple(float(row[column]) for column in ("open", "high", "low", "close"))
            if not all(math.isfinite(value) for value in prices):
                missing += 1
                continue
            emitted.append(
                Bar(
                    index=int(index),
                    available_at_ms=int(row["available_at_ms"]),
                    open=prices[0],
                    high=prices[1],
                    low=prices[2],
                    close=prices[3],
                )
            )
        return (
            tuple(emitted),
            CanonicalBarAudit(
                total_rows=len(self._frame),
                emitted_rows=len(emitted),
                future_rows=future,
                missing_rows=missing,
                incomplete_rows=incomplete,
            ),
        )

    def cursor(self) -> "CanonicalBarCursor":
        return CanonicalBarCursor(self)


class CanonicalBarCursor:
    """Emit each newly available completed canonical bar exactly once."""

    def __init__(self, stream: CanonicalDecisionStream) -> None:
        self._stream = stream
        self._next_index = 0
        self._last_decision_time_ms = -1

    def advance(self, decision_time_ms: int) -> tuple[Bar, ...]:
        if decision_time_ms < self._last_decision_time_ms:
            raise CanonicalDataContractError("decision clock cannot move backward")
        self._last_decision_time_ms = int(decision_time_ms)
        rows = self._stream._frame
        emitted: list[Bar] = []
        while self._next_index < len(rows):
            index = self._next_index
            row = rows.iloc[index]
            if int(row["available_at_ms"]) > decision_time_ms:
                break
            self._next_index += 1
            if "observed" in rows.columns and not bool(row["observed"]):
                continue
            if "source_available" in rows.columns and not bool(row["source_available"]):
                continue
            if "is_complete" in rows.columns and not bool(row["is_complete"]):
                continue
            prices = tuple(float(row[column]) for column in ("open", "high", "low", "close"))
            if not all(math.isfinite(value) for value in prices):
                continue
            emitted.append(
                Bar(
                    index=index,
                    available_at_ms=int(row["available_at_ms"]),
                    open=prices[0],
                    high=prices[1],
                    low=prices[2],
                    close=prices[3],
                )
            )
        return tuple(emitted)


def first_exact_execution(
    one_second: pd.DataFrame,
    decision_time_ms: int,
) -> ExactExecutionObservation | None:
    """Resolve the first stored trade after the project-wide aligned 500ms delay."""

    raw = canonical.first_executable_trade_after_aligned_500ms(
        one_second,
        decision_time_ms,
    )
    if raw is None:
        return None
    return ExactExecutionObservation(
        activation_time_ms=int(raw["activation_time_ms"]),
        trade_time_ms=int(raw["trade_time_ms"]),
        price=float(raw["price"]),
        half_start_time_ms=int(raw["half_start_time_ms"]),
        side_is_unambiguous_buy=bool(raw["side_is_unambiguous_buy"]),
    )


def first_exact_execution_v5(
    observed_500ms: pd.DataFrame,
    decision_time_ms: int,
) -> ExactExecutionObservation | None:
    """Resolve exact execution from the canonical sparse tick-index V5 shard."""

    raw = compact_v5.first_executable_trade_after(
        observed_500ms,
        decision_time_ms,
        activation_delay_ms=500,
    )
    if raw is None:
        return None
    return ExactExecutionObservation(
        activation_time_ms=int(raw["activation_time_ms"]),
        trade_time_ms=int(raw["trade_time_ms"]),
        price=float(raw["price"]),
        half_start_time_ms=int(raw["bucket_start_time_ms"]),
        side_is_unambiguous_buy=False,
    )


def load_first_exact_execution_v5(
    shard: str | Path,
    decision_time_ms: int,
) -> ExactExecutionObservation | None:
    observed = compact_v5.load_observed_500ms(shard)
    if observed.empty:
        return None
    return first_exact_execution_v5(observed, decision_time_ms)


def load_first_exact_execution(
    root: str | Path,
    segment: str,
    symbol: str,
    month: str,
    decision_time_ms: int,
) -> ExactExecutionObservation | None:
    one_second = canonical.load_monthly_microbar(
        root,
        segment,
        symbol,
        month,
        timeframe="1s",
    )
    if one_second.empty:
        return None
    return first_exact_execution(one_second, decision_time_ms)
