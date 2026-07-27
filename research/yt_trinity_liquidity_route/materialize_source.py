#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

EXPECTED_SOURCE_SHA256 = "7728855a94ce3ab8264605b2a8cccf76cbe0e0a153eb4dcce09a01480ad6cdca"
EXPECTED_PAYLOAD_SHA256 = "71c10acf71dde856c02b7b4f10a9f562322c3d2e0b7c255a55525025bed3f55f"


def main() -> None:
    root = Path(__file__).resolve().parent
    chunks = sorted((root / "payload").glob("route.*"))
    if [path.name for path in chunks] != ["route.00", "route.01", "route.02", "route.03"]:
        raise SystemExit(f"unexpected payload chunks: {[path.name for path in chunks]}")
    payload_text = "".join(path.read_text(encoding="utf-8") for path in chunks)
    if hashlib.sha256(payload_text.encode()).hexdigest() != EXPECTED_PAYLOAD_SHA256:
        raise SystemExit("liquidity-route payload SHA-256 mismatch")
    compressed = base64.b64decode("".join(payload_text.split()), validate=True)
    source = gzip.decompress(compressed)
    if hashlib.sha256(source).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise SystemExit("liquidity-route source SHA-256 mismatch")
    destination = root / "liquidity_route.py"
    destination.write_bytes(source)
    print(f"materialized {destination} sha256={EXPECTED_SOURCE_SHA256}")


if __name__ == "__main__":
    main()
