#!/usr/bin/env python3
"""Export immutable canonical Bybit parquet shards to NumPy arrays for rapid local research."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def numeric_array(frame: pd.DataFrame, name: str, *, dtype: str = "float64") -> np.ndarray:
    if name not in frame.columns:
        raise KeyError(f"missing column {name}")
    return pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=dtype)


def save_npz(path: Path, **arrays: np.ndarray) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)
    return {
        "path": str(path),
        "rows": int(len(next(iter(arrays.values()))) if arrays else 0),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "columns": sorted(arrays),
    }


def sort_unique(frame: pd.DataFrame, timestamp: str) -> pd.DataFrame:
    result = frame.copy()
    result[timestamp] = pd.to_numeric(result[timestamp], errors="raise").astype("int64")
    result = result.drop_duplicates(timestamp, keep="last").sort_values(timestamp, kind="stable")
    return result.reset_index(drop=True)


def trade_export(shard: Path, timeframe: str, output: Path) -> dict[str, object]:
    trade_path = shard / "trade_bars" / f"{timeframe}.parquet"
    frame = sort_unique(pd.read_parquet(trade_path), "start_time_ms")
    arrays: dict[str, np.ndarray] = {
        "start_time_ms": numeric_array(frame, "start_time_ms", dtype="int64"),
        "available_at_ms": numeric_array(frame, "available_at_ms", dtype="int64"),
        "open": numeric_array(frame, "open"),
        "high": numeric_array(frame, "high"),
        "low": numeric_array(frame, "low"),
        "close": numeric_array(frame, "close"),
        "volume": numeric_array(frame, "volume"),
    }
    if "turnover" in frame.columns:
        arrays["turnover"] = numeric_array(frame, "turnover")
    complete_name = next((name for name in ("complete", "is_complete", "source_complete") if name in frame.columns), None)
    if complete_name is not None:
        arrays["complete"] = frame[complete_name].fillna(False).astype("uint8").to_numpy()
    return save_npz(output, **arrays)


def stream_export(shard: Path, stream: str, output: Path, columns: Iterable[str]) -> dict[str, object] | None:
    path = shard / "streams" / f"{stream}.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    timestamp = "start_time_ms" if "start_time_ms" in frame.columns else "timestamp_ms"
    frame = sort_unique(frame, timestamp)
    arrays: dict[str, np.ndarray] = {
        timestamp: numeric_array(frame, timestamp, dtype="int64"),
        "available_at_ms": numeric_array(frame, "available_at_ms", dtype="int64"),
    }
    for name in columns:
        if name in frame.columns:
            arrays[name] = numeric_array(frame, name)
    return save_npz(output, **arrays)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segments", nargs="+", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    args = parser.parse_args()

    records: list[dict[str, object]] = []
    source_manifests: list[dict[str, object]] = []
    for segment in args.segments:
        for symbol in args.symbols:
            shard = args.data_root / segment / symbol
            source_manifest_path = shard / "DATASET_MANIFEST.json"
            source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
            source_manifests.append(
                {
                    "segment": segment,
                    "symbol": symbol,
                    "dataset_id": source_manifest.get("dataset_id"),
                    "manifest_sha256": sha256_file(source_manifest_path),
                }
            )
            target = args.output / segment / symbol
            for timeframe in ("15m", "1m"):
                record = trade_export(shard, timeframe, target / f"trade_{timeframe}.npz")
                record.update({"segment": segment, "symbol": symbol, "kind": f"trade_{timeframe}"})
                records.append(record)
            for stream, columns in (
                ("mark_price_1m", ("open", "high", "low", "close")),
                ("index_price_1m", ("open", "high", "low", "close")),
                ("premium_index_1m", ("open", "high", "low", "close")),
                ("open_interest_5m", ("open_interest",)),
                ("account_ratio_5m", ("buy_ratio", "sell_ratio", "long_short_ratio")),
                ("funding_events", ("funding_rate",)),
            ):
                record = stream_export(shard, stream, target / f"{stream}.npz", columns)
                if record is None:
                    continue
                record.update({"segment": segment, "symbol": symbol, "kind": stream})
                records.append(record)

    manifest = {
        "schema_version": 1,
        "segments": args.segments,
        "symbols": args.symbols,
        "source_manifests": source_manifests,
        "files": records,
    }
    manifest_path = args.output / "NPZ_EXPORT_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "NPZ_EXPORT_MANIFEST.sha256").write_text(
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
