#!/usr/bin/env python3
"""Repack a verified V3 sparse 500 ms shard into exact tick-index V5 storage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

try:
    from .canonical_spec import sha256_file
except ImportError:
    from canonical_spec import sha256_file

PRICE_QUANTUM = {
    "BTCUSDT": 0.1,
    "ETHUSDT": 0.01,
    "SOLUSDT": 0.001,
    "XRPUSDT": 0.0001,
}
PRICE_COLUMNS = ("open", "high", "low", "close")
FLOW_COLUMNS = ("buy_volume", "sell_volume", "buy_turnover", "sell_turnover")
OFFSET_COLUMNS = ("first_offset_ms", "high_offset_ms", "low_offset_ms", "last_offset_ms")


def price_to_ticks(values: pd.Series, quantum: float) -> np.ndarray:
    raw = pd.to_numeric(values, errors="raise").to_numpy(dtype="float64")
    ticks64 = np.rint(raw / quantum).astype("int64")
    reconstructed = ticks64.astype("float64") * quantum
    tolerance = max(1e-10, quantum * 1e-6)
    if np.max(np.abs(reconstructed - raw), initial=0.0) > tolerance:
        raise ValueError(f"source price is not aligned to declared quantum {quantum}")
    info = np.iinfo(np.int32)
    if ticks64.size and (ticks64.min() < info.min or ticks64.max() > info.max):
        raise OverflowError("price tick index does not fit int32")
    return ticks64.astype("int32")


def repack(root: Path) -> Path:
    root = root.resolve()
    manifest_path = root / "DATASET_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 3:
        raise ValueError("input shard must use compact schema_version 3")
    symbol = manifest.get("symbol")
    if symbol not in PRICE_QUANTUM:
        raise ValueError(f"unsupported symbol for V5 price encoding: {symbol}")
    quantum = PRICE_QUANTUM[symbol]

    upstream_dataset_id = manifest["dataset_id"]
    manifest["schema_version"] = 5
    manifest["upstream_dataset_id"] = upstream_dataset_id
    manifest["dataset_id"] = upstream_dataset_id.replace("SPARSE500-V3", "SPARSE500-V5")
    manifest["dataset_family_id"] = "DSF-BYBIT-LINEAR-4ASSET-MONTHLY-SPARSE500-V5"
    manifest["storage_encoding"] = {
        "time": "int32 bucket_index relative to month start; one unit equals 500 ms",
        "price": f"int32 exact tick index; one unit equals {quantum:g} USDT for {symbol}",
        "availability": "available_at_ms = month_start_ms + bucket_index*500 + 500",
        "coverage": "absent rows are covered no-trade buckets except on manifest unavailable days",
    }
    manifest["price_quantum"] = quantum

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
        for column in PRICE_COLUMNS:
            packed[f"{column}_tick"] = price_to_ticks(frame[column], quantum)
        for column in FLOW_COLUMNS:
            packed[column] = frame[column].astype("float64")
        packed["trade_count"] = frame["trade_count"].astype("int32")
        for column in OFFSET_COLUMNS:
            packed[column] = frame[column].astype("int16")

        new_path = root / "micro_bars" / "500ms_observed_v5.parquet"
        table = pa.Table.from_pandas(packed, preserve_index=False)
        pq.write_table(
            table,
            new_path,
            compression="zstd",
            compression_level=19,
            use_dictionary=[
                "trade_count", "first_offset_ms", "high_offset_ms",
                "low_offset_ms", "last_offset_ms",
            ],
            write_statistics=True,
            version="2.6",
            row_group_size=500_000,
        )
        old_path.unlink()
        old_item.update({
            "name": "500ms_observed_v5",
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
