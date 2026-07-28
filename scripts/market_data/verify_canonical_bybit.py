#!/usr/bin/env python3
"""Verify hashes, time bounds, causality metadata and microbar invariants."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PRICE_COLUMNS = ("open", "high", "low", "close")
FLOW_COLUMNS = (
    "volume", "turnover", "trade_count", "buy_volume", "sell_volume",
    "buy_turnover", "sell_turnover",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_manifest_hash(root: Path) -> tuple[dict[str, Any], str]:
    manifest_path = root / "DATASET_MANIFEST.json"
    hash_path = root / "DATASET_MANIFEST.sha256"
    expected = hash_path.read_text(encoding="utf-8").split()[0]
    actual = sha256_file(manifest_path)
    if actual != expected:
        raise RuntimeError("manifest hash mismatch")
    return json.loads(manifest_path.read_text(encoding="utf-8")), actual


def _check_common_frame(
    frame: pd.DataFrame,
    *,
    path: Path,
    start_ms: int,
    end_ms: int,
    expected_interval_ms: int | None,
) -> None:
    timestamp_col = "start_time_ms" if "start_time_ms" in frame.columns else "timestamp_ms"
    if timestamp_col not in frame.columns or frame.empty:
        return
    timestamps = pd.to_numeric(frame[timestamp_col], errors="raise").astype("int64")
    if int(timestamps.min()) < start_ms or int(timestamps.max()) >= end_ms:
        raise RuntimeError(f"timestamp outside segment: {path}")
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise RuntimeError(f"timestamps not unique and increasing: {path}")
    if expected_interval_ms is not None and len(timestamps) > 1:
        delta = np.diff(timestamps.to_numpy(dtype="int64"))
        if not np.all(delta == expected_interval_ms):
            raise RuntimeError(f"non-exact interval grid: {path}")
    if "available_at_ms" in frame.columns:
        available = pd.to_numeric(frame["available_at_ms"], errors="raise").astype("int64")
        if expected_interval_ms is not None:
            if not np.array_equal(
                available.to_numpy(dtype="int64"),
                timestamps.to_numpy(dtype="int64") + expected_interval_ms,
            ):
                raise RuntimeError(f"incorrect availability timestamp: {path}")
        elif (available < timestamps).any():
            raise RuntimeError(f"availability precedes observation: {path}")


def _verify_micro_1s(frame: pd.DataFrame, path: Path) -> None:
    required = {
        "start_time_ms", "source_available", "observed", "available_at_ms",
        *PRICE_COLUMNS, *FLOW_COLUMNS,
    }
    for half in ("h0", "h1"):
        required.update({
            f"{half}_observed", f"{half}_available_at_ms",
            f"{half}_first_offset_ms", f"{half}_high_offset_ms",
            f"{half}_low_offset_ms", f"{half}_last_offset_ms",
        })
        required.update({f"{half}_{name}" for name in (*PRICE_COLUMNS, *FLOW_COLUMNS)})
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"microbar columns missing in {path}: {sorted(missing)}")
    if (frame["observed"] & ~frame["source_available"]).any():
        raise RuntimeError(f"observed second without source coverage: {path}")
    if not (frame["observed"] == (frame["h0_observed"] | frame["h1_observed"])).all():
        raise RuntimeError(f"one-second observed flag does not reconcile: {path}")
    starts = frame["start_time_ms"].to_numpy(dtype="int64")
    if not np.array_equal(frame["h0_available_at_ms"].to_numpy(dtype="int64"), starts + 500):
        raise RuntimeError(f"h0 availability mismatch: {path}")
    if not np.array_equal(frame["h1_available_at_ms"].to_numpy(dtype="int64"), starts + 1_000):
        raise RuntimeError(f"h1 availability mismatch: {path}")

    unavailable = ~frame["source_available"]
    if unavailable.any():
        if not (frame.loc[unavailable, "trade_count"] == -1).all():
            raise RuntimeError(f"unavailable seconds must use trade_count=-1: {path}")
        if frame.loc[unavailable, list(PRICE_COLUMNS)].notna().any().any():
            raise RuntimeError(f"unavailable seconds contain prices: {path}")
    available = frame["source_available"]
    no_trade = available & ~frame["observed"]
    if no_trade.any():
        if not (frame.loc[no_trade, "trade_count"] == 0).all():
            raise RuntimeError(f"covered no-trade seconds must use trade_count=0: {path}")
        if frame.loc[no_trade, list(PRICE_COLUMNS)].notna().any().any():
            raise RuntimeError(f"covered no-trade seconds contain prices: {path}")

    observed = frame[frame["observed"]]
    if not observed.empty:
        if not (
            (observed["low"] <= observed[["open", "close"]].min(axis=1)).all()
            and (observed["high"] >= observed[["open", "close"]].max(axis=1)).all()
        ):
            raise RuntimeError(f"one-second OHLC order failure: {path}")
    covered = frame[available]
    if not covered.empty:
        diff = (covered["buy_volume"] + covered["sell_volume"] - covered["volume"]).abs()
        tolerance = 1e-9 + covered["volume"].abs() * 1e-10
        if not (diff <= tolerance).all():
            raise RuntimeError(f"one-second side volume reconciliation failure: {path}")

    for half in ("h0", "h1"):
        active = frame[frame[f"{half}_observed"]]
        if active.empty:
            continue
        first = active[f"{half}_first_offset_ms"]
        high = active[f"{half}_high_offset_ms"]
        low = active[f"{half}_low_offset_ms"]
        last = active[f"{half}_last_offset_ms"]
        if not ((0 <= first) & (first <= high) & (high <= last) & (last <= 499)).all():
            raise RuntimeError(f"{half} high-offset order failure: {path}")
        if not ((first <= low) & (low <= last)).all():
            raise RuntimeError(f"{half} low-offset order failure: {path}")


def verify(root: Path) -> dict[str, Any]:
    manifest, manifest_hash = _verify_manifest_hash(root)
    if manifest.get("credentials_used") or manifest.get("orders_submitted"):
        raise RuntimeError("market-data shard must not use credentials or submit orders")
    if manifest.get("status") == "PRELISTING":
        if manifest.get("files"):
            raise RuntimeError("prelisting manifest must not claim data files")
        return {
            "status": "PASS",
            "dataset_id": manifest["dataset_id"],
            "logical_segment": manifest["logical_segment"],
            "checked_files": 0,
            "manifest_sha256": manifest_hash,
            "prelisting": True,
        }

    start_ms = int(pd.Timestamp(manifest["start"]).timestamp() * 1000)
    end_ms = int(pd.Timestamp(manifest["end_exclusive"]).timestamp() * 1000)
    checked: list[str] = []
    for item in manifest["files"]:
        path = root / item["path"]
        if not path.is_file():
            raise RuntimeError(f"missing file: {path}")
        if sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"hash mismatch: {path}")
        if path.suffix == ".parquet":
            frame = pd.read_parquet(path)
            if len(frame) != int(item["rows"]):
                raise RuntimeError(f"row mismatch: {path}")
            interval = None
            if item.get("kind") == "micro_bar":
                interval = {"1s": 1_000, "5s": 5_000, "15s": 15_000}[item["name"]]
            _check_common_frame(
                frame,
                path=path,
                start_ms=start_ms,
                end_ms=end_ms,
                expected_interval_ms=interval,
            )
            if item.get("kind") == "micro_bar" and item.get("name") == "1s":
                _verify_micro_1s(frame, path)
        checked.append(item["path"])

    return {
        "status": "PASS",
        "dataset_id": manifest["dataset_id"],
        "logical_segment": manifest["logical_segment"],
        "checked_files": len(checked),
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
