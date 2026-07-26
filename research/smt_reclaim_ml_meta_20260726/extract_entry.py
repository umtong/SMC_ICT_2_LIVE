from __future__ import annotations

import csv
import gzip
import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import extract as engine


@dataclass(frozen=True, slots=True)
class SourceRecordCompat:
    symbol: str
    date: str
    url: str
    bytes: int
    sha256: str
    rows: int
    columns: list[str]
    first_timestamp: float
    last_timestamp: float
    timestamp_monotonic: bool


def inspect_source_compat(
    target: Path,
    symbol: str,
    date: str,
    url: str,
    payload: bytes,
) -> SourceRecordCompat:
    """Record source identity without changing the frozen aggregation."""
    row_count = 0
    first_timestamp = float("nan")
    last_timestamp = float("nan")
    previous_timestamp: float | None = None
    monotonic = True

    with gzip.open(target, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        try:
            columns = next(reader)
        except StopIteration as exc:
            raise RuntimeError(f"empty gzip CSV source: {url}") from exc
        try:
            timestamp_index = columns.index("timestamp")
        except ValueError as exc:
            raise RuntimeError(f"timestamp column missing: {url}") from exc

        for row in reader:
            if not row:
                continue
            timestamp = float(row[timestamp_index])
            if row_count == 0:
                first_timestamp = timestamp
            if previous_timestamp is not None and timestamp < previous_timestamp:
                monotonic = False
            previous_timestamp = timestamp
            last_timestamp = timestamp
            row_count += 1

    if row_count == 0:
        raise RuntimeError(f"source has header but no rows: {url}")

    return SourceRecordCompat(
        symbol=symbol,
        date=date,
        url=url,
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        rows=row_count,
        columns=columns,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        timestamp_monotonic=monotonic,
    )


_ORIGINAL_AGGREGATE = engine.base.aggregate
_DAY_ARRAY_FIELDS = (
    "symbol",
    "date",
    "mark",
    "total_notional",
    "signed_notional",
    "trade_count",
)
_NUMERIC_ARRAY_FIELDS = (
    "mark",
    "total_notional",
    "signed_notional",
    "trade_count",
)
_EXPECTED_BINS = 24 * 60 * 60 * 10


def _day_arrays_getitem(self, key: str):
    if key not in _DAY_ARRAY_FIELDS:
        raise KeyError(key)
    return getattr(self, key)


def aggregate_compat(target: Path, date: str):
    """Call the audited shared API and retain its original DayArrays object."""
    path = Path(target)
    symbol = path.name.split(date, 1)[0]
    if not symbol:
        raise ValueError(f"cannot derive symbol from source path: {path}")

    arrays, record = _ORIGINAL_AGGREGATE(path, symbol, date)
    if record.symbol != symbol or record.date != date:
        raise AssertionError(
            f"aggregate source identity mismatch: {record.symbol}/{record.date} "
            f"!= {symbol}/{date}"
        )
    for field in _DAY_ARRAY_FIELDS:
        if not hasattr(arrays, field):
            raise TypeError(f"audited DayArrays field missing: {field}")
    for field in _NUMERIC_ARRAY_FIELDS:
        value = getattr(arrays, field)
        if not isinstance(value, np.ndarray):
            raise TypeError(f"DayArrays.{field} is not numpy.ndarray")
        if value.shape != (_EXPECTED_BINS,):
            raise AssertionError(
                f"DayArrays.{field} shape {value.shape} != ({_EXPECTED_BINS},)"
            )
    return arrays


def utc_start_compat(date: str) -> float:
    """Return the Unix timestamp of 00:00 UTC for an ISO calendar date."""
    return float(pd.Timestamp(date, tz="UTC").timestamp())


def corrected_rolling_realized_volatility(mark: np.ndarray, window: int = 100) -> np.ndarray:
    price = np.asarray(mark, dtype=np.float64)
    returns = np.full(len(price), np.nan, dtype=np.float64)
    valid = (
        np.isfinite(price[1:])
        & np.isfinite(price[:-1])
        & (price[1:] > 0)
        & (price[:-1] > 0)
    )
    valid_positions = np.flatnonzero(valid) + 1
    returns[valid_positions] = np.log(
        price[valid_positions] / price[valid_positions - 1]
    )
    squared = np.nan_to_num(returns * returns, nan=0.0)
    cumulative = np.concatenate(([0.0], np.cumsum(squared, dtype=np.float64)))
    end = np.arange(1, len(squared) + 1)
    start = np.maximum(0, end - window)
    return np.sqrt(np.maximum(0.0, cumulative[end] - cumulative[start]))


if not hasattr(engine.base, "inspect_source"):
    engine.base.inspect_source = inspect_source_compat
if not hasattr(engine.base.DayArrays, "__getitem__"):
    engine.base.DayArrays.__getitem__ = _day_arrays_getitem
engine.base.aggregate = aggregate_compat
if not hasattr(engine.base, "utc_start"):
    engine.base.utc_start = utc_start_compat
engine.rolling_realized_volatility = corrected_rolling_realized_volatility


if __name__ == "__main__":
    raise SystemExit(engine.main())
