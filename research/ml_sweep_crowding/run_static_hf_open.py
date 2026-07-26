"""Execute correction 003 with official static prices and pinned actual funding."""
from __future__ import annotations

import math

import pandas as pd

from . import run as sealed_run
from . import source_static_hf as source


def normalize_open_rate(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {str(column).lower(): str(column) for column in frame.columns}
    time_name = next(
        (
            columns[name]
            for name in ("date", "timestamp", "time", "datetime", "funding_time")
            if name in columns
        ),
        None,
    )
    if time_name is None or "open" not in columns:
        raise source.SourceGateError(
            f"verified pinned Bybit funding schema absent: {list(frame.columns)}"
        )
    raw_time = frame[time_name]
    if pd.api.types.is_numeric_dtype(raw_time):
        numeric = pd.to_numeric(raw_time, errors="coerce")
        median = float(numeric.dropna().median()) if numeric.notna().any() else math.nan
        unit = "ms" if median > 1e11 else "s"
        timestamp = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    else:
        timestamp = pd.to_datetime(raw_time, utc=True, errors="coerce")
    rate = pd.to_numeric(frame[columns["open"]], errors="coerce")
    normalized = pd.DataFrame({"timestamp": timestamp, "funding_rate": rate})
    normalized = (
        normalized.dropna()
        .drop_duplicates("timestamp", keep="last")
        .set_index("timestamp")
        .sort_index()
    )
    if normalized["funding_rate"].nunique() < 10:
        raise source.SourceGateError("pinned Bybit funding open column is degenerate")
    return normalized


source._normalize_funding = normalize_open_rate
sealed_run.download_bybit_months = source.download_bybit_months_static
sealed_run.load_market = source.load_market_static_hf


def main() -> int:
    return sealed_run.main()


if __name__ == "__main__":
    raise SystemExit(main())
