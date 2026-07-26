from __future__ import annotations

import csv
import gzip
import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

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
    """Reproduce the removed metadata-only source inspection helper.

    The scientific aggregation remains in the frozen shared base_probe module.
    This streaming pass records source identity and timestamp monotonicity only.
    """
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
engine.rolling_realized_volatility = corrected_rolling_realized_volatility


if __name__ == "__main__":
    raise SystemExit(engine.main())
