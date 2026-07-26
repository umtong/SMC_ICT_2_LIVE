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


def normalize_asof_join_keys(root: Path) -> bool:
    path = root / "system" / "canonical_adapter.py"
    text = path.read_text(encoding="utf-8")
    if ASOF_NEW in text:
        return False
    if text.count(ASOF_OLD) != 1:
        raise RuntimeError("unexpected canonical as-of join source")
    path.write_text(text.replace(ASOF_OLD, ASOF_NEW), encoding="utf-8", newline="\n")
    return True


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
    changed = normalize_asof_join_keys(root)
    print(
        f"materialized {destination} sha256={actual} bytes={len(raw)} "
        f"asof_dtype_fix={changed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
