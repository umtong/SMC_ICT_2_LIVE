from __future__ import annotations

import csv
import gzip
import hashlib
import inspect
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


_ORIGINAL_AGGREGATE = engine.base.aggregate


def _source_symbol(target: Path, date: str) -> str:
    name = target.name
    if date in name:
        candidate = name.split(date, 1)[0]
        if candidate:
            return candidate
    if target.parent.name:
        return target.parent.name
    raise ValueError(f"cannot derive source symbol from {target}")


def aggregate_compat(target: Path, date: str):
    """Bind path, symbol and date to the shared aggregate function once.

    The upstream helper changed its call signature, not its scientific
    implementation. Argument binding is decided from the function signature
    before invoking it, so no data path is executed speculatively or twice.
    """
    path = Path(target)
    symbol = _source_symbol(path, date)
    signature = inspect.signature(_ORIGINAL_AGGREGATE)

    semantic_values: dict[str, object] = {}
    unresolved_required: list[str] = []
    for name, parameter in signature.parameters.items():
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        lowered = name.lower()
        if any(token in lowered for token in ("path", "file", "target", "archive", "source")):
            semantic_values[name] = path
        elif any(token in lowered for token in ("symbol", "instrument", "market", "contract")):
            semantic_values[name] = symbol
        elif "date" in lowered or lowered in {"day", "session"}:
            semantic_values[name] = date
        elif parameter.default is inspect.Parameter.empty:
            unresolved_required.append(name)

    if not unresolved_required:
        signature.bind(**semantic_values)
        return _ORIGINAL_AGGREGATE(**semantic_values)

    candidates = (
        (path, symbol, date),
        (path, date, symbol),
        (symbol, path, date),
        (symbol, date, path),
        (date, path, symbol),
        (date, symbol, path),
        (path, date),
    )
    for arguments in candidates:
        try:
            signature.bind(*arguments)
        except TypeError:
            continue
        return _ORIGINAL_AGGREGATE(*arguments)

    raise TypeError(
        "unsupported shared aggregate signature: "
        f"{signature}; available values are path={path}, symbol={symbol}, date={date}"
    )


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
engine.base.aggregate = aggregate_compat
if not hasattr(engine.base, "utc_start"):
    engine.base.utc_start = utc_start_compat
engine.rolling_realized_volatility = corrected_rolling_realized_volatility


if __name__ == "__main__":
    raise SystemExit(engine.main())
