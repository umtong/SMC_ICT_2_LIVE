"""Immutable period, grid, hashing and bar-derivation rules for canonical Bybit data."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

MS_MINUTE = 60_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
TRADE_BAR_RULES = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}
TRADE_BAR_INTERVAL_MS = {
    "1min": MS_MINUTE,
    "5min": 5 * MS_MINUTE,
    "15min": 15 * MS_MINUTE,
    "1h": 60 * MS_MINUTE,
    "4h": 4 * 60 * MS_MINUTE,
    "1D": 24 * 60 * MS_MINUTE,
}
SEGMENTS: dict[str, tuple[str, str, str]] = {
    "PRE_2024_2020": ("2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z", "PRE_2024"),
    "PRE_2024_2021": ("2021-01-01T00:00:00Z", "2022-01-01T00:00:00Z", "PRE_2024"),
    "PRE_2024_2022": ("2022-01-01T00:00:00Z", "2023-01-01T00:00:00Z", "PRE_2024"),
    "PRE_2024_2023": ("2023-01-01T00:00:00Z", "2024-01-01T00:00:00Z", "PRE_2024"),
    "2024_H1": ("2024-01-01T00:00:00Z", "2024-07-01T00:00:00Z", "2024_H1"),
    "2024_H2": ("2024-07-01T00:00:00Z", "2025-01-01T00:00:00Z", "2024_H2"),
    "2025_H1": ("2025-01-01T00:00:00Z", "2025-07-01T00:00:00Z", "2025_H1"),
    "2025_H2": ("2025-07-01T00:00:00Z", "2026-01-01T00:00:00Z", "2025_H2"),
    "2026_H1": ("2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z", "2026_H1"),
}


def utc_ms(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1000)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonicalize_grid(
    frame: pd.DataFrame,
    *,
    timestamp_col: str,
    start_ms: int,
    end_exclusive_ms: int,
    step_ms: int,
    available_delay_ms: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Align to the exact UTC grid and preserve every absence as an explicit row."""
    expected = pd.Index(range(start_ms, end_exclusive_ms, step_ms), dtype="int64", name=timestamp_col)
    if timestamp_col not in frame.columns:
        frame = frame.copy()
        frame[timestamp_col] = pd.Series(dtype="int64")
    indexed = frame.set_index(timestamp_col).reindex(expected)
    value_columns = list(indexed.columns)
    observed = (
        indexed[value_columns].notna().any(axis=1)
        if value_columns
        else pd.Series(False, index=indexed.index)
    )
    indexed.insert(0, "observed", observed.astype(bool))
    indexed["available_at_ms"] = indexed.index.to_numpy(dtype="int64") + available_delay_ms
    indexed = indexed.reset_index()

    observed_rows = int(indexed["observed"].sum())
    expected_rows = int(len(indexed))
    observed_timestamps = indexed.loc[indexed["observed"], timestamp_col].to_numpy(dtype="int64")
    if len(observed_timestamps):
        first_observed_ms: int | None = int(observed_timestamps[0])
        last_observed_ms: int | None = int(observed_timestamps[-1])
        expected_after_first = int((end_exclusive_ms - first_observed_ms + step_ms - 1) // step_ms)
        coverage_after_first = observed_rows / expected_after_first
    else:
        first_observed_ms = None
        last_observed_ms = None
        expected_after_first = 0
        coverage_after_first = 0.0
    return indexed, {
        "expected_rows": expected_rows,
        "observed_rows": observed_rows,
        "missing_rows": expected_rows - observed_rows,
        "coverage": 0.0 if expected_rows == 0 else observed_rows / expected_rows,
        "first_observed_ms": first_observed_ms,
        "last_observed_ms": last_observed_ms,
        "expected_rows_after_first_observed": expected_after_first,
        "coverage_after_first_observed": coverage_after_first,
    }


def derive_trade_bars(base_1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Derive UTC-anchored bars; any absent source minute invalidates the whole bar."""
    required = {"start_time_ms", "open", "high", "low", "close", "volume", "turnover", "observed"}
    missing = required.difference(base_1m.columns)
    if missing:
        raise ValueError(f"base 1m columns missing: {sorted(missing)}")
    if rule not in TRADE_BAR_INTERVAL_MS:
        raise ValueError(f"unsupported fixed trade-bar rule: {rule}")
    temp = base_1m.copy()
    temp.index = pd.to_datetime(temp["start_time_ms"], unit="ms", utc=True)
    grouped = temp.resample(rule, label="left", closed="left", origin="epoch")
    out = pd.DataFrame({
        "start_time_ms": grouped["start_time_ms"].first(),
        "open": grouped["open"].first(),
        "high": grouped["high"].max(),
        "low": grouped["low"].min(),
        "close": grouped["close"].last(),
        "volume": grouped["volume"].sum(min_count=1),
        "turnover": grouped["turnover"].sum(min_count=1),
        "source_rows_observed": grouped["observed"].sum(),
        "source_rows_total": grouped["observed"].size(),
    })
    out["is_complete"] = out["source_rows_observed"] == out["source_rows_total"]
    value_columns = ["open", "high", "low", "close", "volume", "turnover"]
    out.loc[~out["is_complete"], value_columns] = float("nan")
    out["available_at_ms"] = out["start_time_ms"].astype("Int64") + TRADE_BAR_INTERVAL_MS[rule]
    return out.reset_index(drop=True)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd")
