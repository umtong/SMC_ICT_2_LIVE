#!/usr/bin/env python3
"""Common loaders for extracted canonical Bybit core and microbar shards."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

EVALUATION_SEGMENTS = ("2024_H1", "2024_H2", "2025_H1", "2025_H2", "2026_H1")
HALF_VALUE_COLUMNS = (
    "open", "high", "low", "close", "volume", "turnover", "trade_count",
    "buy_volume", "sell_volume", "buy_turnover", "sell_turnover",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shard_root(root: str | Path, segment: str, symbol: str) -> Path:
    return Path(root).expanduser().resolve() / segment / symbol


def load_manifest(root: str | Path, segment: str, symbol: str, *, verify_hash: bool = True) -> dict:
    shard = shard_root(root, segment, symbol)
    path = shard / "DATASET_MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["physical_segment"] != segment or manifest["symbol"] != symbol:
        raise RuntimeError(f"manifest identity mismatch: {path}")
    if verify_hash:
        expected = (shard / "DATASET_MANIFEST.sha256").read_text(encoding="utf-8").split()[0]
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"manifest hash mismatch: {path}")
    return manifest


def _load_named(root: str | Path, segment: str, symbol: str, kind: str, name: str) -> pd.DataFrame:
    manifest = load_manifest(root, segment, symbol)
    matches = [item for item in manifest["files"] if item["kind"] == kind and item["name"] == name]
    if len(matches) != 1:
        raise KeyError(f"expected one {kind}/{name} in {segment}/{symbol}; found {len(matches)}")
    path = shard_root(root, segment, symbol) / matches[0]["path"]
    if sha256_file(path) != matches[0]["sha256"]:
        raise RuntimeError(f"file hash mismatch: {path}")
    return pd.read_parquet(path)


def load_stream(root: str | Path, segment: str, symbol: str, stream: str) -> pd.DataFrame:
    return _load_named(root, segment, symbol, "stream", stream)


def load_trade_bar(root: str | Path, segment: str, symbol: str, timeframe: str) -> pd.DataFrame:
    return _load_named(root, segment, symbol, "trade_bar", timeframe)


def monthly_microbar_root(root: str | Path, segment: str, symbol: str, month: str) -> Path:
    return Path(root).expanduser().resolve() / segment / symbol / month


def load_monthly_microbar(
    root: str | Path,
    segment: str,
    symbol: str,
    month: str,
    timeframe: str = "1s",
) -> pd.DataFrame:
    shard = monthly_microbar_root(root, segment, symbol, month)
    manifest_path = shard / "DATASET_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = (shard / "DATASET_MANIFEST.sha256").read_text(encoding="utf-8").split()[0]
    if sha256_file(manifest_path) != expected:
        raise RuntimeError(f"manifest hash mismatch: {manifest_path}")
    if manifest.get("status") == "PRELISTING":
        return pd.DataFrame()
    matches = [
        item for item in manifest["files"]
        if item["kind"] == "micro_bar" and item["name"] == timeframe
    ]
    if len(matches) != 1:
        raise KeyError(f"expected one micro_bar/{timeframe} in {segment}/{symbol}/{month}")
    path = shard / matches[0]["path"]
    if sha256_file(path) != matches[0]["sha256"]:
        raise RuntimeError(f"file hash mismatch: {path}")
    return pd.read_parquet(path)


def visible_rows(frame: pd.DataFrame, decision_time_ms: int) -> pd.DataFrame:
    """Return only rows whose declared information-availability time has elapsed."""
    if "available_at_ms" not in frame.columns:
        raise ValueError("frame has no available_at_ms column")
    return frame[frame["available_at_ms"].notna() & (frame["available_at_ms"] <= decision_time_ms)].copy()


def to_500ms_bars(one_second: pd.DataFrame) -> pd.DataFrame:
    """Reshape stored one-second rows into exact UTC-aligned 500 ms bars without reacquisition."""
    required = {"start_time_ms", "source_available"}
    for half in ("h0", "h1"):
        required.update({f"{half}_observed", f"{half}_available_at_ms"})
        required.update({f"{half}_{column}" for column in HALF_VALUE_COLUMNS})
        required.update({
            f"{half}_first_offset_ms", f"{half}_high_offset_ms",
            f"{half}_low_offset_ms", f"{half}_last_offset_ms",
        })
    missing = required.difference(one_second.columns)
    if missing:
        raise ValueError(f"one-second frame lacks half-second columns: {sorted(missing)}")

    frames: list[pd.DataFrame] = []
    for half, offset in (("h0", 0), ("h1", 500)):
        part = pd.DataFrame({
            "start_time_ms": one_second["start_time_ms"].astype("int64") + offset,
            "source_available": one_second["source_available"].astype(bool),
            "observed": one_second[f"{half}_observed"].astype(bool),
            **{column: one_second[f"{half}_{column}"] for column in HALF_VALUE_COLUMNS},
            "first_offset_ms": one_second[f"{half}_first_offset_ms"].astype("int16"),
            "high_offset_ms": one_second[f"{half}_high_offset_ms"].astype("int16"),
            "low_offset_ms": one_second[f"{half}_low_offset_ms"].astype("int16"),
            "last_offset_ms": one_second[f"{half}_last_offset_ms"].astype("int16"),
            "available_at_ms": one_second[f"{half}_available_at_ms"].astype("int64"),
        })
        frames.append(part)
    out = pd.concat(frames, ignore_index=True).sort_values("start_time_ms", kind="stable")
    return out.reset_index(drop=True)


def first_executable_trade_after_aligned_500ms(
    one_second: pd.DataFrame, decision_time_ms: int
) -> dict[str, int | float] | None:
    """Return the first stored trade at or after an aligned decision plus the fixed 500 ms delay.

    This is exact for decisions aligned to whole-second boundaries, including stored
    1s/5s/15s/minute/hour bar closes.
    """
    if decision_time_ms % 1_000:
        raise ValueError("decision_time_ms must be aligned to a whole second")
    activation_ms = decision_time_ms + 500
    half = to_500ms_bars(one_second)
    eligible = half[
        half["source_available"]
        & half["observed"]
        & (half["start_time_ms"] >= activation_ms)
    ]
    if eligible.empty:
        return None
    row = eligible.iloc[0]
    first_offset = int(row["first_offset_ms"])
    if first_offset < 0:
        raise RuntimeError("observed half-second row lacks first trade offset")
    side = 1 if float(row["buy_volume"]) > 0 and float(row["sell_volume"]) == 0 else 0
    return {
        "activation_time_ms": activation_ms,
        "trade_time_ms": int(row["start_time_ms"]) + first_offset,
        "price": float(row["open"]),
        "half_start_time_ms": int(row["start_time_ms"]),
        "side_is_unambiguous_buy": side,
    }


def concatenate_segments(
    root: str | Path,
    symbol: str,
    *,
    kind: str,
    name: str,
    segments: Iterable[str] = EVALUATION_SEGMENTS,
) -> pd.DataFrame:
    """Concatenate storage partitions without resetting time or adding account semantics."""
    frames: list[pd.DataFrame] = []
    last_timestamp: int | None = None
    timestamp_column: str | None = None
    for segment in segments:
        frame = _load_named(root, segment, symbol, kind, name)
        candidate = "start_time_ms" if "start_time_ms" in frame.columns else "timestamp_ms"
        if candidate not in frame.columns:
            raise ValueError(f"no time column for {kind}/{name}")
        if timestamp_column is None:
            timestamp_column = candidate
        elif timestamp_column != candidate:
            raise ValueError("time-column mismatch across segments")
        if not frame.empty:
            first = int(frame[candidate].iloc[0])
            if last_timestamp is not None and first <= last_timestamp:
                raise RuntimeError(f"non-increasing segment boundary before {segment}")
            last_timestamp = int(frame[candidate].iloc[-1])
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
