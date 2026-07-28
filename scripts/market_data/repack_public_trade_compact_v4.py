#!/usr/bin/env python3
"""Repack a verified V3 sparse 500 ms shard into the smaller V4 encoding."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

try:
    from .canonical_spec import sha256_file
except ImportError:
    from canonical_spec import sha256_file

FLOAT_COLUMNS = (
    "open", "high", "low", "close",
    "buy_volume", "sell_volume", "buy_turnover", "sell_turnover",
)
INT_COLUMNS = (
    "trade_count", "first_offset_ms", "high_offset_ms", "low_offset_ms", "last_offset_ms",
)


def repack(root: Path) -> Path:
    root = root.resolve()
    manifest_path = root / "DATASET_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 3:
        raise ValueError("input shard must use compact schema_version 3")

    upstream_dataset_id = manifest["dataset_id"]
    manifest["schema_version"] = 4
    manifest["upstream_dataset_id"] = upstream_dataset_id
    manifest["dataset_id"] = upstream_dataset_id.replace("SPARSE500-V3", "SPARSE500-V4")
    manifest["dataset_family_id"] = "DSF-BYBIT-LINEAR-4ASSET-MONTHLY-SPARSE500-V4"
    manifest["storage_encoding"] = {
        "time": "int32 bucket_index relative to month start, one unit equals 500 ms",
        "availability": "available_at_ms is derived as month_start_ms + bucket_index*500 + 500",
        "coverage": "absent rows are covered no-trade buckets except on manifest unavailable days",
    }

    if manifest.get("status") == "PRELISTING":
        manifest["files"] = []
    else:
        matches = [
            item for item in manifest.get("files", [])
            if item.get("kind") == "micro_bar" and item.get("name") == "500ms_observed"
        ]
        if len(matches) != 1:
            raise RuntimeError("expected one V3 compact parquet")
        old_item = matches[0]
        old_path = root / old_item["path"]
        if sha256_file(old_path) != old_item["sha256"]:
            raise RuntimeError("input compact parquet hash mismatch")
        frame = pd.read_parquet(old_path)
        month_start_ms = int(pd.Timestamp(manifest["start"]).timestamp() * 1000)
        delta = pd.to_numeric(frame["start_time_ms"], errors="raise").astype("int64") - month_start_ms
        if (delta < 0).any() or (delta % 500 != 0).any():
            raise RuntimeError("input timestamps cannot be represented as 500 ms bucket indexes")
        bucket_index = (delta // 500).astype("int32")
        packed = pd.DataFrame({"bucket_index": bucket_index})
        for column in FLOAT_COLUMNS:
            packed[column] = frame[column].astype("float64")
        packed["trade_count"] = frame["trade_count"].astype("int32")
        for column in ("first_offset_ms", "high_offset_ms", "low_offset_ms", "last_offset_ms"):
            packed[column] = frame[column].astype("int16")

        new_path = root / "micro_bars" / "500ms_observed_v4.parquet"
        table = pa.Table.from_pandas(packed, preserve_index=False)
        pq.write_table(
            table,
            new_path,
            compression="zstd",
            compression_level=15,
            use_dictionary=[
                "trade_count", "first_offset_ms", "high_offset_ms",
                "low_offset_ms", "last_offset_ms",
            ],
            use_byte_stream_split=list(FLOAT_COLUMNS),
            write_statistics=True,
            version="2.6",
            row_group_size=500_000,
        )
        old_path.unlink()
        old_item.update({
            "name": "500ms_observed_v4",
            "path": str(new_path.relative_to(root)),
            "rows": len(packed),
            "bytes": new_path.stat().st_size,
            "sha256": sha256_file(new_path),
        })

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "DATASET_MANIFEST.sha256").write_text(
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n", encoding="utf-8"
    )
    return root


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    output = repack(args.root)
    print(json.dumps({"status": "REPACKED", "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
