#!/usr/bin/env python3
"""Materialize the exact compression-expansion runner and one audited compatibility fix."""
from __future__ import annotations

import base64
import hashlib
import zlib
from pathlib import Path

PAYLOAD_SHA256 = "dd26ecbd64482b19de400cb793187832c14ac46da8605d99f78029fcfdba195a"
FINAL_SHA256 = "d9afb2fca7391e3e53d94d7e23f60be6629540a67a9db809783253eb4fa33085"
EXPECTED_CHUNKS = ["alpha.00", "alpha.01", "alpha.02", "alpha.03"]
OLD = b'best_route_summary["route"]["identifier"]'
NEW = b'best_route_summary["route"].identifier'


def main() -> int:
    root = Path(__file__).resolve().parent
    chunks = sorted((root / "compression_alpha_payload").glob("alpha.*"))
    names = [path.name for path in chunks]
    if names != EXPECTED_CHUNKS:
        raise RuntimeError(f"unexpected compression-alpha chunks: {names}")
    encoded = b"".join(path.read_bytes().strip() for path in chunks)
    raw = zlib.decompress(base64.b85decode(encoded))
    payload_sha = hashlib.sha256(raw).hexdigest()
    if payload_sha != PAYLOAD_SHA256:
        raise RuntimeError(f"compression-alpha payload SHA mismatch: {payload_sha}")
    if raw.count(OLD) != 1 or NEW in raw:
        raise RuntimeError("unexpected RouteConfig selector source")
    raw = raw.replace(OLD, NEW)
    final_sha = hashlib.sha256(raw).hexdigest()
    if final_sha != FINAL_SHA256:
        raise RuntimeError(f"compression-alpha final SHA mismatch: {final_sha}")
    destination = root / "run_compression_alpha.py"
    destination.write_bytes(raw)
    print(
        f"materialized {destination} payload_sha256={payload_sha} "
        f"final_sha256={final_sha} bytes={len(raw)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
