#!/usr/bin/env python3
"""Verify hashes, segment boundaries, schemas and causality metadata of one shard."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(root: Path) -> dict[str, Any]:
    manifest_path = root / "DATASET_MANIFEST.json"
    hash_path = root / "DATASET_MANIFEST.sha256"
    expected_manifest_hash = hash_path.read_text(encoding="utf-8").split()[0]
    actual_manifest_hash = sha256_file(manifest_path)
    if actual_manifest_hash != expected_manifest_hash:
        raise RuntimeError("manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    start_ms = int(pd.Timestamp(manifest["start"]).timestamp() * 1000)
    end_ms = int(pd.Timestamp(manifest["end_exclusive"]).timestamp() * 1000)
    checked: list[str] = []

    for item in manifest["files"]:
        path = root / item["path"]
        if not path.is_file():
            raise RuntimeError(f"missing file: {path}")
        actual = sha256_file(path)
        if actual != item["sha256"]:
            raise RuntimeError(f"hash mismatch: {path}")
        if path.suffix == ".parquet":
            frame = pd.read_parquet(path)
            if len(frame) != int(item["rows"]):
                raise RuntimeError(f"row mismatch: {path}")
            timestamp_col = "start_time_ms" if "start_time_ms" in frame.columns else "timestamp_ms"
            if timestamp_col in frame.columns and not frame.empty:
                timestamps = pd.to_numeric(frame[timestamp_col], errors="raise").dropna().astype("int64")
                if not timestamps.empty:
                    if int(timestamps.min()) < start_ms or int(timestamps.max()) >= end_ms:
                        raise RuntimeError(f"timestamp outside segment: {path}")
                    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
                        raise RuntimeError(f"timestamps not unique and increasing: {path}")
            if "available_at_ms" in frame.columns and timestamp_col in frame.columns:
                valid = frame[[timestamp_col, "available_at_ms"]].dropna()
                if (valid["available_at_ms"] < valid[timestamp_col]).any():
                    raise RuntimeError(f"availability precedes observation: {path}")
        checked.append(item["path"])

    if manifest.get("credentials_used") or manifest.get("orders_submitted"):
        raise RuntimeError("market-data shard must not use credentials or submit orders")
    return {
        "status": "PASS",
        "dataset_id": manifest["dataset_id"],
        "logical_segment": manifest["logical_segment"],
        "checked_files": len(checked),
        "manifest_sha256": actual_manifest_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.root.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
