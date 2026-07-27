#!/usr/bin/env python3
"""Verify immutable sparse 500 ms Bybit public-trade shards."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PRICE_COLUMNS = ("open", "high", "low", "close")
SIDE_FLOW_COLUMNS = ("buy_volume", "sell_volume", "buy_turnover", "sell_turnover")
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
    if manifest.get("schema_version") != 3:
        raise RuntimeError("compact manifest schema_version must be 3")
    if manifest.get("credentials_used") or manifest.get("orders_submitted"):
        raise RuntimeError("market-data shard must not use credentials or submit orders")
    if manifest.get("stored_interval") != "500ms_observed_sparse":
        raise RuntimeError("unexpected compact stored interval")
    if manifest.get("derived_intervals") != ["1s", "5s", "15s"]:
        raise RuntimeError("unexpected compact derived intervals")

    coverage = manifest.get("coverage", {})
    if coverage.get("unexpected_missing_days"):
        raise RuntimeError("verified shard cannot contain unexpected missing source days")
    if manifest.get("status") == "PRELISTING":
        if manifest.get("files"):
            raise RuntimeError("prelisting shard must not claim material files")
        return {
            "status": "PASS",
            "dataset_id": manifest["dataset_id"],
            "checked_files": 0,
            "manifest_sha256": manifest_hash,
            "prelisting": True,
        }
    if manifest.get("status") != "VERIFIED":
        raise RuntimeError("listed compact shard must have VERIFIED status")

    start_ms = int(pd.Timestamp(manifest["start"]).timestamp() * 1000)
    end_ms = int(pd.Timestamp(manifest["end_exclusive"]).timestamp() * 1000)
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
        if item.get("kind") == "micro_bar" and item.get("name") == "500ms_observed":
            frame = pd.read_parquet(path)
            if len(frame) != int(item["rows"]):
                raise RuntimeError("compact parquet row mismatch")
            required = {
                "start_time_ms", *PRICE_COLUMNS, *SIDE_FLOW_COLUMNS, "trade_count",
                *OFFSET_COLUMNS, "available_at_ms",
            }
            missing = required.difference(frame.columns)
            if missing:
                raise RuntimeError(f"compact columns missing: {sorted(missing)}")
            starts = pd.to_numeric(frame["start_time_ms"], errors="raise").astype("int64")
            if frame.empty:
                raise RuntimeError("listed month has an empty compact parquet")
            if int(starts.iloc[0]) < start_ms or int(starts.iloc[-1]) >= end_ms:
                raise RuntimeError("compact timestamp outside month")
            if starts.duplicated().any() or not starts.is_monotonic_increasing or (starts % 500 != 0).any():
                raise RuntimeError("compact timestamps are not unique, increasing and 500 ms aligned")
            available = pd.to_numeric(frame["available_at_ms"], errors="raise").astype("int64")
            if not np.array_equal(available.to_numpy(), starts.to_numpy() + 500):
                raise RuntimeError("compact availability timestamp mismatch")
            if frame[[*PRICE_COLUMNS, *SIDE_FLOW_COLUMNS]].isna().any().any():
                raise RuntimeError("observed compact rows cannot contain null values")
            if not (
                (frame["low"] <= frame[["open", "close"]].min(axis=1)).all()
                and (frame["high"] >= frame[["open", "close"]].max(axis=1)).all()
            ):
                raise RuntimeError("compact OHLC ordering failure")
            if (frame[[*SIDE_FLOW_COLUMNS, "trade_count"]] < 0).any().any():
                raise RuntimeError("compact flow contains a negative value")
            first = frame["first_offset_ms"]
            high = frame["high_offset_ms"]
            low = frame["low_offset_ms"]
            last = frame["last_offset_ms"]
            if not ((0 <= first) & (first <= high) & (high <= last) & (last <= 499)).all():
                raise RuntimeError("compact high-offset ordering failure")
            if not ((first <= low) & (low <= last)).all():
                raise RuntimeError("compact low-offset ordering failure")
            micro_rows = len(frame)
        checked.append(item["path"])

    if micro_rows is None:
        raise RuntimeError("compact microbar file not found")
    if int(coverage.get("observed_500ms_rows", -1)) != micro_rows:
        raise RuntimeError("manifest observed_500ms_rows mismatch")
    source_items = [item for item in manifest["files"] if item.get("kind") == "source_audit"]
    if len(source_items) != 1 or int(source_items[0]["rows"]) != int(manifest.get("source_file_count", -1)):
        raise RuntimeError("source-file audit count mismatch")

    return {
        "status": "PASS",
        "dataset_id": manifest["dataset_id"],
        "checked_files": len(checked),
        "observed_500ms_rows": micro_rows,
        "manifest_sha256": manifest_hash,
        "prelisting": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.root.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
