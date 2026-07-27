#!/usr/bin/env python3
"""Materialize the exact opening-range/BPR runner and one audited compatibility fix."""
from __future__ import annotations

import base64
import hashlib
import zlib
from pathlib import Path

PAYLOAD_SHA256 = "f9295cf0c1b5b4a35c06ff89e267ceab4e6e827717b8387881723bb10a49c040"
FINAL_SHA256 = "2122602ec3f81bd845b881c345a40932a2b7834cddc5a46477066aeeb6302ed4"
OLD = b'best_route_summary["route"]["identifier"]'
NEW = b'best_route_summary["route"].identifier'


def main() -> int:
    root = Path(__file__).resolve().parent
    chunk = root / "opening_range_alpha_payload" / "alpha.00"
    if not chunk.is_file():
        raise RuntimeError(f"missing opening-range payload: {chunk}")
    raw = zlib.decompress(base64.b85decode(chunk.read_bytes().strip()))
    payload_sha = hashlib.sha256(raw).hexdigest()
    if payload_sha != PAYLOAD_SHA256:
        raise RuntimeError(f"opening-range payload SHA mismatch: {payload_sha}")
    if raw.count(OLD) != 1 or NEW in raw:
        raise RuntimeError("unexpected RouteConfig selector source")
    raw = raw.replace(OLD, NEW)
    final_sha = hashlib.sha256(raw).hexdigest()
    if final_sha != FINAL_SHA256:
        raise RuntimeError(f"opening-range final SHA mismatch: {final_sha}")
    destination = root / "run_opening_range_alpha.py"
    destination.write_bytes(raw)
    print(
        f"materialized {destination} payload_sha256={payload_sha} "
        f"final_sha256={final_sha} bytes={len(raw)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
