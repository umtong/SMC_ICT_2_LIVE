#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def numeric(frame: pd.DataFrame, name: str, dtype: str = "float64") -> np.ndarray:
    if name not in frame:
        return np.full(len(frame), np.nan, dtype=dtype)
    return pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=dtype)


def load_sorted(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    key = "start_time_ms" if "start_time_ms" in frame else "timestamp_ms"
    frame[key] = pd.to_numeric(frame[key], errors="raise").astype("int64")
    frame["available_at_ms"] = pd.to_numeric(frame["available_at_ms"], errors="raise").astype("int64")
    return frame.drop_duplicates(key, keep="last").sort_values(key, kind="stable").reset_index(drop=True)


def asof_add(base: pd.DataFrame, source: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    left = base.sort_values("available_at_ms", kind="stable").copy()
    right = source.sort_values("available_at_ms", kind="stable").copy()
    keep = ["available_at_ms", *[name for name in mapping if name in right]]
    right = right[keep].rename(columns=mapping)
    return pd.merge_asof(left, right, on="available_at_ms", direction="backward", allow_exact_matches=True)


def aligned_bars(shard: Path, timeframe: str) -> pd.DataFrame:
    bars = load_sorted(shard / "trade_bars" / f"{timeframe}.parquet")
    for name in ("open", "high", "low", "close", "volume", "turnover"):
        if name in bars:
            bars[name] = pd.to_numeric(bars[name], errors="coerce")
    stream_specs = (
        ("mark_price_1m", {"close": "mark_close"}),
        ("index_price_1m", {"close": "index_close"}),
        ("premium_index_1m", {"close": "premium_close"}),
        ("open_interest_5m", {"open_interest": "open_interest"}),
        ("account_ratio_5m", {"buy_ratio": "buy_ratio", "sell_ratio": "sell_ratio"}),
    )
    result = bars
    for stream, mapping in stream_specs:
        result = asof_add(result, load_sorted(shard / "streams" / f"{stream}.parquet"), mapping)
    result["long_short_ratio"] = result.get("buy_ratio") / result.get("sell_ratio").replace(0, np.nan)
    return result.sort_values("start_time_ms", kind="stable").reset_index(drop=True)


def save_frame(frame: pd.DataFrame, path: Path) -> dict[str, object]:
    arrays: dict[str, np.ndarray] = {}
    for name in (
        "start_time_ms", "available_at_ms", "open", "high", "low", "close", "volume", "turnover",
        "mark_close", "index_close", "premium_close", "open_interest", "buy_ratio", "sell_ratio", "long_short_ratio",
    ):
        dtype = "int64" if name.endswith("_ms") else "float64"
        arrays[name] = numeric(frame, name, dtype)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)
    return {"path": str(path), "rows": len(frame), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def save_funding(shard: Path, path: Path) -> dict[str, object]:
    frame = load_sorted(shard / "streams" / "funding_events.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        timestamp_ms=numeric(frame, "timestamp_ms", "int64"),
        available_at_ms=numeric(frame, "available_at_ms", "int64"),
        funding_rate=numeric(frame, "funding_rate"),
    )
    return {"path": str(path), "rows": len(frame), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segment", required=True)
    args = parser.parse_args()

    files: list[dict[str, object]] = []
    sources: list[dict[str, object]] = []
    for symbol in SYMBOLS:
        shard = args.source / args.segment / symbol
        manifest_path = shard / "DATASET_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sources.append({"symbol": symbol, "dataset_id": manifest["dataset_id"], "manifest_sha256": sha256_file(manifest_path)})
        target = args.output / args.segment / symbol
        for timeframe in ("15m", "5m"):
            row = save_frame(aligned_bars(shard, timeframe), target / f"aligned_{timeframe}.npz")
            row.update({"symbol": symbol, "timeframe": timeframe})
            files.append(row)
        row = save_funding(shard, target / "funding_events.npz")
        row.update({"symbol": symbol, "timeframe": "funding"})
        files.append(row)

    output = {"schema_version": 1, "segment": args.segment, "symbols": list(SYMBOLS), "sources": sources, "files": files}
    manifest_path = args.output / args.segment / "MANIFEST.json"
    manifest_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
