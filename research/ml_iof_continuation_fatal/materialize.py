from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CARRIER = ROOT / "run_fatal_screen.py.gz.b64"
OUTPUT = ROOT / "run_fatal_screen.py"
EXPECTED_SOURCE_SHA256 = "326ca2f415935167ef6f1f072ac897a625ff515d7015ba691c9f2f7e80d683eb"
EXPECTED_CARRIER_SHA256 = "c50baa6212a67c920305d4085ca6d3ae3b4a70c4bddacb69b92bb0149bd4f901"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> int:
    encoded = CARRIER.read_bytes().strip()
    if sha256_bytes(encoded) != EXPECTED_CARRIER_SHA256:
        raise AssertionError("runner carrier hash mismatch")
    source = gzip.decompress(base64.b64decode(encoded, validate=True))
    if sha256_bytes(source) != EXPECTED_SOURCE_SHA256:
        raise AssertionError("materialized runner hash mismatch")
    OUTPUT.write_bytes(source)
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
