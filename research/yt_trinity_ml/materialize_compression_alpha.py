#!/usr/bin/env python3
"""Materialize the exact compression-expansion research runner from compact chunks."""
from __future__ import annotations

import base64
import hashlib
import zlib
from pathlib import Path

EXPECTED_SHA256 = "dd26ecbd64482b19de400cb793187832c14ac46da8605d99f78029fcfdba195a"
EXPECTED_CHUNKS = ["alpha.00", "alpha.01", "alpha.02", "alpha.03"]


def main() -> int:
    root = Path(__file__).resolve().parent
    chunks = sorted((root / "compression_alpha_payload").glob("alpha.*"))
    names = [path.name for path in chunks]
    if names != EXPECTED_CHUNKS:
        raise RuntimeError(f"unexpected compression-alpha chunks: {names}")
    encoded = b"".join(path.read_bytes().strip() for path in chunks)
    raw = zlib.decompress(base64.b85decode(encoded))
    actual = hashlib.sha256(raw).hexdigest()
    if actual != EXPECTED_SHA256:
        raise RuntimeError(f"compression-alpha SHA mismatch: {actual}")
    destination = root / "run_compression_alpha.py"
    destination.write_bytes(raw)
    print(f"materialized {destination} sha256={actual} bytes={len(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
