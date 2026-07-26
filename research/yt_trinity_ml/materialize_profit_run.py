#!/usr/bin/env python3
"""Materialize the exact reviewed profit runner and deterministic compatibility fixes."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import zlib

EXPECTED_SHA256 = "0435cb618882c981b526abe1e7ea28ec3c78f249051b43b9393021b3c622647f"

ASOF_OLD = '''    left = base.reset_index(drop=True).sort_values("available_at_ms", kind="stable")
    index_column = auxiliary.index.name or "index"
    right = auxiliary.reset_index(drop=False).rename(columns={index_column: "source_timestamp"})
    right = right.sort_values("available_at_ms", kind="stable")
'''

ASOF_NEW = '''    left = base.reset_index(drop=True).sort_values("available_at_ms", kind="stable")
    left["available_at_ms"] = pd.to_numeric(
        left["available_at_ms"], errors="raise"
    ).astype("int64")
    index_column = auxiliary.index.name or "index"
    right = auxiliary.reset_index(drop=False).rename(columns={index_column: "source_timestamp"})
    right["available_at_ms"] = pd.to_numeric(
        right["available_at_ms"], errors="raise"
    ).astype("int64")
    right = right.sort_values("available_at_ms", kind="stable")
'''

SOURCE_TIMESTAMP_OLD = '''    joined.index = pd.to_datetime(joined["available_at_ms"], unit="ms", utc=True)
    joined.index.name = "decision_time"
    return joined.sort_index()
'''

SOURCE_TIMESTAMP_NEW = '''    joined = joined.drop(columns=["source_timestamp"])
    joined.index = pd.to_datetime(joined["available_at_ms"], unit="ms", utc=True)
    joined.index.name = "decision_time"
    return joined.sort_index()
'''


def normalize_canonical_joins(root: Path) -> tuple[bool, bool]:
    path = root / "system" / "canonical_adapter.py"
    text = path.read_text(encoding="utf-8")
    dtype_changed = False
    timestamp_changed = False

    if ASOF_NEW not in text:
        if text.count(ASOF_OLD) != 1:
            raise RuntimeError("unexpected canonical as-of join key source")
        text = text.replace(ASOF_OLD, ASOF_NEW)
        dtype_changed = True

    if SOURCE_TIMESTAMP_NEW not in text:
        if text.count(SOURCE_TIMESTAMP_OLD) != 1:
            raise RuntimeError("unexpected canonical source-timestamp cleanup source")
        text = text.replace(SOURCE_TIMESTAMP_OLD, SOURCE_TIMESTAMP_NEW)
        timestamp_changed = True

    if dtype_changed or timestamp_changed:
        path.write_text(text, encoding="utf-8", newline="\n")
    return dtype_changed, timestamp_changed


def main() -> int:
    root = Path(__file__).resolve().parent
    chunks = sorted((root / "profit_run_payload").glob("profit.*"))
    if [path.name for path in chunks] != ["profit.00", "profit.01"]:
        raise RuntimeError(f"unexpected profit runner chunks: {[path.name for path in chunks]}")
    encoded = b"".join(path.read_bytes().strip() for path in chunks)
    raw = zlib.decompress(base64.b85decode(encoded))
    actual = hashlib.sha256(raw).hexdigest()
    if actual != EXPECTED_SHA256:
        raise RuntimeError(f"profit runner SHA mismatch: {actual}")
    destination = root / "run_profit_first.py"
    destination.write_bytes(raw)
    dtype_changed, timestamp_changed = normalize_canonical_joins(root)
    print(
        f"materialized {destination} sha256={actual} bytes={len(raw)} "
        f"asof_dtype_fix={dtype_changed} source_timestamp_cleanup={timestamp_changed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
