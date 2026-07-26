#!/usr/bin/env python3
"""Common loader for extracted canonical Bybit half-year shards."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

EVALUATION_SEGMENTS = ("2024_H1", "2024_H2", "2025_H1", "2025_H2", "2026_H1")


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


def visible_rows(frame: pd.DataFrame, decision_time_ms: int) -> pd.DataFrame:
    """Return only rows whose declared information-availability time has elapsed."""
    if "available_at_ms" not in frame.columns:
        raise ValueError("frame has no available_at_ms column")
    return frame[frame["available_at_ms"].notna() & (frame["available_at_ms"] <= decision_time_ms)].copy()


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
