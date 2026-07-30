"""Run the pinned funding probe with the mirror's verified `open` rate column."""
from __future__ import annotations

import math

import pandas as pd

from . import probe_hf_bybit_funding as base


def normalize_open_rate(frame: pd.DataFrame) -> tuple[pd.DataFrame, str, str]:
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
        raise RuntimeError(f"verified funding mirror schema absent: {list(frame.columns)}")
    time_raw = frame[time_name]
    if pd.api.types.is_numeric_dtype(time_raw):
        numeric = pd.to_numeric(time_raw, errors="coerce")
        median = float(numeric.dropna().median()) if numeric.notna().any() else math.nan
        unit = "ms" if median > 1e11 else "s"
        timestamp = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    else:
        timestamp = pd.to_datetime(time_raw, utc=True, errors="coerce")
    rate_name = columns["open"]
    rate = pd.to_numeric(frame[rate_name], errors="coerce")
    normalized = pd.DataFrame({"timestamp": timestamp, "funding_rate": rate})
    normalized = (
        normalized.dropna()
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    return normalized, time_name, rate_name


base.normalize = normalize_open_rate


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
