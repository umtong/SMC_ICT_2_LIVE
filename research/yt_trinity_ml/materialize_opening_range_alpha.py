#!/usr/bin/env python3
"""Materialize the exact opening-range/BPR research runner."""
from __future__ import annotations

import base64
import hashlib
import zlib
from pathlib import Path

EXPECTED_SHA256 = "f9295cf0c1b5b4a35c06ff89e267ceab4e6e827717b8387881723bb10a49c040"


def main() -> int:
    root = Path(__file__).resolve().parent
    chunk = root / "opening_range_alpha_payload" / "alpha.00"
    if not chunk.is_file():
        raise RuntimeError(f"missing opening-range payload: {chunk}")
    raw = zlib.decompress(base64.b85decode(chunk.read_bytes().strip()))
    actual = hashlib.sha256(raw).hexdigest()
    if actual != EXPECTED_SHA256:
        raise RuntimeError(f"opening-range alpha SHA mismatch: {actual}")
    destination = root / "run_opening_range_alpha.py"
    destination.write_bytes(raw)
    print(f"materialized {destination} sha256={actual} bytes={len(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
