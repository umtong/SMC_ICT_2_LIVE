from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import numpy as np
import pandas as pd

class ResearchError(RuntimeError):
    """Raised when a source or causal-contract invariant is violated."""


@dataclass(frozen=True)
class SourceRecord:
    source_type: str
    exchange: str
    symbol: str
    data_date: str
    url: str
    path: str
    bytes: int
    sha256: str
    checksum_verified: bool
    row_count: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "data_date": self.data_date,
            "url": self.url,
            "path": self.path,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "checksum_verified": self.checksum_verified,
            "row_count": self.row_count,
        }


@dataclass(frozen=True)
class TradeOutcome:
    symbol: str
    family: str
    signal_id: str
    event_time: pd.Timestamp
    entry_time: pd.Timestamp
    direction: int
    entry_price: float
    stop_price: float
    target_price: float
    exit_time: pd.Timestamp | None
    exit_price: float | None
    exit_reason: str
    resolved: bool


@dataclass
class PriceSeries:
    timestamps: np.ndarray
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> "PriceSeries":
        ordered = frame.sort_values("minute").drop_duplicates("minute", keep="last")
        return cls(
            timestamps=ordered["minute"].to_numpy(dtype="datetime64[ns]"),
            opens=ordered["open"].to_numpy(float),
            highs=ordered["high"].to_numpy(float),
            lows=ordered["low"].to_numpy(float),
            closes=ordered["close"].to_numpy(float),
        )

    def open_at(self, ts: pd.Timestamp) -> float | None:
        needle = np.datetime64(ts.tz_convert("UTC").tz_localize(None), "ns")
        idx = int(np.searchsorted(self.timestamps, needle, side="left"))
        if idx >= len(self.timestamps) or self.timestamps[idx] != needle:
            return None
        return float(self.opens[idx])

    def resolve_oco(
        self,
        *,
        entry_time: pd.Timestamp,
        path_end: pd.Timestamp,
        direction: int,
        stop_price: float,
        target_price: float,
    ) -> tuple[pd.Timestamp | None, float | None, str]:
        start = np.datetime64(entry_time.tz_convert("UTC").tz_localize(None), "ns")
        end = np.datetime64(path_end.tz_convert("UTC").tz_localize(None), "ns")
        i0 = int(np.searchsorted(self.timestamps, start, side="left"))
        i1 = int(np.searchsorted(self.timestamps, end, side="left"))
        if i0 >= i1:
            return None, None, "unresolved_missing_path"
        timestamps = self.timestamps[i0:i1]
        opens = self.opens[i0:i1]
        highs = self.highs[i0:i1]
        lows = self.lows[i0:i1]
        if direction > 0:
            stop_hits = lows <= stop_price
            target_hits = highs >= target_price
        else:
            stop_hits = highs >= stop_price
            target_hits = lows <= target_price

        # Never bridge an unavailable minute. A barrier reached after the first
        # source gap is unknowable and therefore cannot resolve the position.
        usable = len(timestamps)
        if len(timestamps) > 1:
            discontinuities = np.flatnonzero(np.diff(timestamps) != np.timedelta64(1, "m"))
            if len(discontinuities):
                usable = int(discontinuities[0]) + 1
        any_hits = (stop_hits | target_hits)[:usable]
        if not bool(np.any(any_hits)):
            if usable < len(timestamps):
                return None, None, "unresolved_source_gap"
            return None, None, "unresolved_no_barrier"
        rel = int(np.flatnonzero(any_hits)[0])
        idx = i0 + rel
        # Conservative convention: if both barriers are touched in one minute, stop first.
        # A protective stop that gaps through its trigger fills at the adverse observed open.
        if bool(stop_hits[rel]):
            reason = "stop"
            if direction > 0:
                price = min(stop_price, float(opens[rel]))
            else:
                price = max(stop_price, float(opens[rel]))
        else:
            reason = "target"
            price = target_price
        ts = pd.Timestamp(self.timestamps[idx]).tz_localize("UTC")
        return ts, float(price), reason


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def month_starts(start: str, end: str) -> list[date]:
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    current = date(first.year, first.month, 1)
    out: list[date] = []
    while current <= last:
        out.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return out


def inclusive_calendar_days(period: Mapping[str, Any]) -> int:
    start = date.fromisoformat(str(period["from"]))
    last_month = date.fromisoformat(str(period["to"]))
    if last_month.month == 12:
        next_month = date(last_month.year + 1, 1, 1)
    else:
        next_month = date(last_month.year, last_month.month + 1, 1)
    return (next_month - start).days


def maximum_drawdown(nav_values: Sequence[float]) -> float:
    if not nav_values:
        return 0.0
    values = np.asarray(nav_values, dtype=float)
    peaks = np.maximum.accumulate(values)
    drawdowns = 1.0 - values / peaks
    return float(np.max(drawdowns))


def top_removed_return(returns: Sequence[float], fraction: float) -> float:
    values = np.asarray(returns, dtype=float)
    if len(values) == 0:
        return 0.0
    positive_idx = np.flatnonzero(values > 0)
    if len(positive_idx) == 0:
        return float(np.prod(1.0 + values) - 1.0)
    remove_count = max(1, int(math.ceil(len(values) * fraction)))
    ranked = positive_idx[np.argsort(values[positive_idx])[::-1]]
    adjusted = values.copy()
    adjusted[ranked[: min(remove_count, len(ranked))]] = 0.0
    return float(np.prod(1.0 + adjusted) - 1.0)


def product_grid(values: Mapping[str, Sequence[Any]]) -> Iterator[dict[str, Any]]:
    keys = list(values)
    if not keys:
        yield {}
        return

    def walk(i: int, current: dict[str, Any]) -> Iterator[dict[str, Any]]:
        if i == len(keys):
            yield dict(current)
            return
        key = keys[i]
        for value in values[key]:
            current[key] = value
            yield from walk(i + 1, current)
        current.pop(key, None)

    yield from walk(0, {})


def candidate_id(params: Mapping[str, Any]) -> str:
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
