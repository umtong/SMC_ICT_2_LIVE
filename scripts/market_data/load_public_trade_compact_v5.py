#!/usr/bin/env python3
"""Load V5 exact tick-index sparse 500 ms shards and derive completed bars."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PRICE_COLUMNS = ("open", "high", "low", "close")
FLOW_COLUMNS = ("buy_volume", "sell_volume", "buy_turnover", "sell_turnover")
OFFSET_COLUMNS = ("first_offset_ms", "high_offset_ms", "low_offset_ms", "last_offset_ms")
OCI_REPOSITORY = "ghcr.io/umtong/smc-ict-2-live/bybit-microbar"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def oci_reference(symbol: str, month: str) -> str:
    return f"{OCI_REPOSITORY}:{symbol.lower()}-{month}-v5"


def pull_oci_shard(symbol: str, month: str, output: str | Path, *, oras: str = "oras") -> Path:
    destination = Path(output).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run([oras, "pull", oci_reference(symbol, month), "-o", str(destination)], check=True)
    return destination


def load_manifest(shard: str | Path, *, verify_hash: bool = True) -> dict:
    root = Path(shard).expanduser().resolve()
    path = root / "DATASET_MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 5:
        raise RuntimeError("V5 compact loader requires schema_version 5")
    if verify_hash:
        expected = (root / "DATASET_MANIFEST.sha256").read_text(encoding="utf-8").split()[0]
        if sha256_file(path) != expected:
            raise RuntimeError(f"manifest hash mismatch: {path}")
    return manifest


def load_observed_500ms(shard: str | Path, *, verify_hash: bool = True) -> pd.DataFrame:
    root = Path(shard).expanduser().resolve()
    manifest = load_manifest(root, verify_hash=verify_hash)
    if manifest.get("status") == "PRELISTING":
        return pd.DataFrame()
    matches = [
        item for item in manifest.get("files", [])
        if item.get("kind") == "micro_bar" and item.get("name") == "500ms_observed_v5"
    ]
    if len(matches) != 1:
        raise KeyError(f"expected one 500ms_observed_v5 file in {root}")
    path = root / matches[0]["path"]
    if verify_hash and sha256_file(path) != matches[0]["sha256"]:
        raise RuntimeError(f"file hash mismatch: {path}")
    packed = pd.read_parquet(path)
    month_start_ms = int(pd.Timestamp(manifest["start"]).timestamp() * 1000)
    quantum = float(manifest["price_quantum"])
    frame = pd.DataFrame({
        "start_time_ms": month_start_ms + packed["bucket_index"].astype("int64") * 500,
    })
    for column in PRICE_COLUMNS:
        frame[column] = packed[f"{column}_tick"].astype("int64").astype("float64") * quantum
    for column in (*FLOW_COLUMNS, "trade_count", *OFFSET_COLUMNS):
        frame[column] = packed[column]
    frame["available_at_ms"] = frame["start_time_ms"] + 500
    return frame


def _utc_ms(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1000)


def _day_start_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def materialize_500ms(
    shard: str | Path,
    *,
    start_ms: int | None = None,
    end_exclusive_ms: int | None = None,
    max_rows: int = 20_000_000,
) -> pd.DataFrame:
    root = Path(shard).expanduser().resolve()
    manifest = load_manifest(root)
    month_start = _utc_ms(manifest["start"])
    month_end = _utc_ms(manifest["end_exclusive"])
    start = month_start if start_ms is None else int(start_ms)
    end = month_end if end_exclusive_ms is None else int(end_exclusive_ms)
    if start < month_start or end > month_end or start >= end:
        raise ValueError("requested interval is outside the monthly shard")
    if start % 500 or end % 500:
        raise ValueError("requested interval must be aligned to 500 ms")
    row_count = (end - start) // 500
    if row_count > max_rows:
        raise ValueError(f"requested grid has {row_count} rows; max_rows={max_rows}")

    starts = np.arange(start, end, 500, dtype="int64")
    grid = pd.DataFrame({"start_time_ms": starts})
    unavailable = np.zeros(len(grid), dtype=bool)
    coverage = manifest.get("coverage", {})
    unavailable_days = set(coverage.get("leading_prelisting_days", []))
    unavailable_days.update(coverage.get("unexpected_missing_days", []))
    if manifest.get("status") == "PRELISTING":
        unavailable[:] = True
    else:
        for day in unavailable_days:
            day_start = _day_start_ms(day)
            unavailable |= (starts >= day_start) & (starts < day_start + 86_400_000)
    grid["source_available"] = ~unavailable

    observed = load_observed_500ms(root)
    if not observed.empty:
        observed = observed[(observed["start_time_ms"] >= start) & (observed["start_time_ms"] < end)]
        observed = observed.drop(columns=["available_at_ms"], errors="ignore")
        grid = grid.merge(observed, on="start_time_ms", how="left", sort=False, validate="one_to_one")
    else:
        for column in (*PRICE_COLUMNS, *FLOW_COLUMNS):
            grid[column] = np.nan
        grid["trade_count"] = np.nan
        for column in OFFSET_COLUMNS:
            grid[column] = np.nan

    grid["observed"] = grid["open"].notna()
    if (grid["observed"] & ~grid["source_available"]).any():
        raise RuntimeError("V5 shard contains observations on an unavailable day")
    for column in FLOW_COLUMNS:
        grid.loc[grid["source_available"] & ~grid["observed"], column] = 0.0
        grid.loc[~grid["source_available"], column] = np.nan
        grid[column] = grid[column].astype("float64")
    for column in PRICE_COLUMNS:
        grid[column] = grid[column].astype("float64")
    grid["volume"] = grid["buy_volume"] + grid["sell_volume"]
    grid["turnover"] = grid["buy_turnover"] + grid["sell_turnover"]
    grid.loc[grid["source_available"] & ~grid["observed"], "trade_count"] = 0
    grid.loc[~grid["source_available"], "trade_count"] = -1
    grid["trade_count"] = grid["trade_count"].astype("int32")
    for column in OFFSET_COLUMNS:
        grid[column] = grid[column].fillna(-1).astype("int16")
    grid["available_at_ms"] = grid["start_time_ms"] + 500
    return grid[[
        "start_time_ms", "source_available", "observed", *PRICE_COLUMNS,
        "volume", "turnover", "trade_count", *FLOW_COLUMNS,
        *OFFSET_COLUMNS, "available_at_ms",
    ]]


def visible_rows(frame: pd.DataFrame, decision_time_ms: int) -> pd.DataFrame:
    if "available_at_ms" not in frame.columns:
        raise ValueError("frame has no available_at_ms column")
    return frame[frame["available_at_ms"] <= int(decision_time_ms)].copy()


def derive_seconds(frame_500ms: pd.DataFrame, interval_seconds: int) -> pd.DataFrame:
    if interval_seconds not in {1, 5, 15}:
        raise ValueError("interval_seconds must be 1, 5 or 15")
    if frame_500ms.empty:
        return pd.DataFrame()
    interval_ms = interval_seconds * 1_000
    expected_rows = interval_seconds * 2
    starts = frame_500ms["start_time_ms"].to_numpy(dtype="int64")
    if starts[0] % interval_ms or (len(starts) > 1 and not np.all(np.diff(starts) == 500)):
        raise ValueError("500 ms input must be exact, consecutive and aligned")
    if len(starts) % expected_rows:
        raise ValueError("500 ms input must contain complete derived intervals")
    temp = frame_500ms.copy()
    temp["bucket_ms"] = (temp["start_time_ms"] // interval_ms) * interval_ms
    grouped = temp.groupby("bucket_ms", sort=True, observed=True)
    out = pd.DataFrame({
        "start_time_ms": grouped["start_time_ms"].first(),
        "source_available": grouped["source_available"].all(),
        "observed": grouped["observed"].any(),
        "open": grouped["open"].first(), "high": grouped["high"].max(),
        "low": grouped["low"].min(), "close": grouped["close"].last(),
        "volume": grouped["volume"].sum(min_count=1),
        "turnover": grouped["turnover"].sum(min_count=1),
        "trade_count": grouped["trade_count"].sum(min_count=1),
        "buy_volume": grouped["buy_volume"].sum(min_count=1),
        "sell_volume": grouped["sell_volume"].sum(min_count=1),
        "buy_turnover": grouped["buy_turnover"].sum(min_count=1),
        "sell_turnover": grouped["sell_turnover"].sum(min_count=1),
        "source_rows_available": grouped["source_available"].sum(),
        "source_rows_total": grouped["source_available"].size(),
        "observed_500ms_rows": grouped["observed"].sum(),
    }).reset_index(drop=True)
    if not (out["source_rows_total"] == expected_rows).all():
        raise RuntimeError("derived interval contains an incomplete group")
    unavailable = ~out["source_available"]
    out.loc[unavailable, [*PRICE_COLUMNS, "volume", "turnover", *FLOW_COLUMNS]] = np.nan
    out.loc[unavailable, "trade_count"] = -1
    out["trade_count"] = out["trade_count"].astype("int32")
    out["source_rows_available"] = out["source_rows_available"].astype("int16")
    out["source_rows_total"] = out["source_rows_total"].astype("int16")
    out["observed_500ms_rows"] = out["observed_500ms_rows"].astype("int16")
    out["available_at_ms"] = out["start_time_ms"] + interval_ms
    return out


def first_executable_trade_after(
    observed_500ms: pd.DataFrame,
    decision_time_ms: int,
    *,
    activation_delay_ms: int = 500,
) -> dict[str, int | float] | None:
    activation = int(decision_time_ms) + int(activation_delay_ms)
    if activation % 500:
        raise ValueError("decision plus activation delay must align to 500 ms")
    eligible = observed_500ms[observed_500ms["start_time_ms"] >= activation]
    if eligible.empty:
        return None
    row = eligible.iloc[0]
    offset = int(row["first_offset_ms"])
    if not 0 <= offset <= 499:
        raise RuntimeError("invalid first trade offset")
    return {
        "activation_time_ms": activation,
        "trade_time_ms": int(row["start_time_ms"]) + offset,
        "price": float(row["open"]),
        "bucket_start_time_ms": int(row["start_time_ms"]),
    }
