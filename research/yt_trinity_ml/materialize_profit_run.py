#!/usr/bin/env python3
"""Materialize the exact reviewed profit-first runner from compact payload chunks."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import zlib

EXPECTED_SHA256 = "0435cb618882c981b526abe1e7ea28ec3c78f249051b43b9393021b3c622647f"


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
    print(f"materialized {destination} sha256={actual} bytes={len(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
