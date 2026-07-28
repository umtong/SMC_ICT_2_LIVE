#!/usr/bin/env python3
"""Verify V5 exact tick-index sparse 500 ms Bybit public-trade shards."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PRICE_COLUMNS = ("open", "high", "low", "close")
FLOW_COLUMNS = ("buy_volume", "sell_volume", "buy_turnover", "sell_turnover")
OFFSET_COLUMNS = ("first_offset_ms", "high_offset_ms", "low_offset_ms", "last_offset_ms")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(root: Path) -> tuple[dict[str, Any], str]:
    path = root / "DATASET_MANIFEST.json"
    expected = (root / "DATASET_MANIFEST.sha256").read_text(encoding="utf-8").split()[0]
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError("manifest hash mismatch")
    return json.loads(path.read_text(encoding="utf-8")), actual


def verify(root: Path) -> dict[str, Any]:
    manifest, manifest_hash = _manifest(root)
    if manifest.get("schema_version") != 5:
        raise RuntimeError("V5 compact manifest schema_version must be 5")
    if manifest.get("credentials_used") or manifest.get("orders_submitted"):
        raise RuntimeError("market-data shard must not use credentials or submit orders")
    if manifest.get("stored_interval") != "500ms_observed_sparse":
        raise RuntimeError("unexpected stored interval")
    if manifest.get("derived_intervals") != ["1s", "5s", "15s"]:
        raise RuntimeError("unexpected derived intervals")
    quantum = float(manifest.get("price_quantum", 0))
    if quantum <= 0:
        raise RuntimeError("V5 manifest has no positive price quantum")
    encoding = manifest.get("storage_encoding", {})
    if "tick index" not in encoding.get("price", ""):
        raise RuntimeError("V5 tick-index price encoding is not declared")

    coverage = manifest.get("coverage", {})
    if coverage.get("unexpected_missing_days"):
        raise RuntimeError("verified shard cannot contain unexpected missing source days")
    if manifest.get("status") == "PRELISTING":
        if manifest.get("files"):
            raise RuntimeError("prelisting shard must not claim material files")
        return {
            "status": "PASS", "dataset_id": manifest["dataset_id"],
            "checked_files": 0, "manifest_sha256": manifest_hash, "prelisting": True,
        }
    if manifest.get("status") != "VERIFIED":
        raise RuntimeError("listed V5 shard must have VERIFIED status")

    start_ms = int(pd.Timestamp(manifest["start"]).timestamp() * 1000)
    end_ms = int(pd.Timestamp(manifest["end_exclusive"]).timestamp() * 1000)
    max_bucket = (end_ms - start_ms) // 500
    checked: list[str] = []
    micro_rows = None
    for item in manifest.get("files", []):
        path = root / item["path"]
        if not path.is_file():
            raise RuntimeError(f"missing file: {path}")
        if sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"hash mismatch: {path}")
        if path.stat().st_size != int(item["bytes"]):
            raise RuntimeError(f"byte-size mismatch: {path}")
        if item.get("kind") == "micro_bar" and item.get("name") == "500ms_observed_v5":
            frame = pd.read_parquet(path)
            if len(frame) != int(item["rows"]):
                raise RuntimeError("V5 parquet row mismatch")
            required = {
                "bucket_index", *[f"{name}_tick" for name in PRICE_COLUMNS],
                *FLOW_COLUMNS, "trade_count", *OFFSET_COLUMNS,
            }
            missing = required.difference(frame.columns)
            if missing:
                raise RuntimeError(f"V5 columns missing: {sorted(missing)}")
            if frame.empty:
                raise RuntimeError("listed month has an empty V5 parquet")
            bucket = pd.to_numeric(frame["bucket_index"], errors="raise").astype("int64")
            if int(bucket.iloc[0]) < 0 or int(bucket.iloc[-1]) >= max_bucket:
                raise RuntimeError("V5 bucket index outside month")
            if bucket.duplicated().any() or not bucket.is_monotonic_increasing:
                raise RuntimeError("V5 bucket indexes are not unique and increasing")
            if frame[[*FLOW_COLUMNS]].isna().any().any():
                raise RuntimeError("observed V5 flow rows cannot contain null values")
            prices = pd.DataFrame({
                name: frame[f"{name}_tick"].astype("int64").astype("float64") * quantum
                for name in PRICE_COLUMNS
            })
            if not (
                (prices["low"] <= prices[["open", "close"]].min(axis=1)).all()
                and (prices["high"] >= prices[["open", "close"]].max(axis=1)).all()
            ):
                raise RuntimeError("V5 reconstructed OHLC ordering failure")
            if (frame[[*FLOW_COLUMNS, "trade_count"]] < 0).any().any():
                raise RuntimeError("V5 flow contains a negative value")
            first = frame["first_offset_ms"]
            high = frame["high_offset_ms"]
            low = frame["low_offset_ms"]
            last = frame["last_offset_ms"]
            if not ((0 <= first) & (first <= high) & (high <= last) & (last <= 499)).all():
                raise RuntimeError("V5 high-offset ordering failure")
            if not ((first <= low) & (low <= last)).all():
                raise RuntimeError("V5 low-offset ordering failure")
            starts = start_ms + bucket.to_numpy(dtype="int64") * 500
            if not np.all((starts >= start_ms) & (starts < end_ms)):
                raise RuntimeError("V5 reconstructed timestamp outside month")
            micro_rows = len(frame)
        checked.append(item["path"])

    if micro_rows is None:
        raise RuntimeError("V5 microbar file not found")
    if int(coverage.get("observed_500ms_rows", -1)) != micro_rows:
        raise RuntimeError("manifest observed_500ms_rows mismatch")
    source_items = [item for item in manifest["files"] if item.get("kind") == "source_audit"]
    if len(source_items) != 1 or int(source_items[0]["rows"]) != int(manifest.get("source_file_count", -1)):
        raise RuntimeError("source-file audit count mismatch")
    return {
        "status": "PASS", "dataset_id": manifest["dataset_id"],
        "checked_files": len(checked), "observed_500ms_rows": micro_rows,
        "manifest_sha256": manifest_hash, "prelisting": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.root.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
