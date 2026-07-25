from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run.py.gz.b64"
TARGET = ROOT / "run.py"
EXPECTED = {
    "base64_bytes": 13968,
    "base64_sha256": "6496939712a9afa53e2cc1be362f3eff922bd3cb246b45a0ce84f509e91e1631",
    "gzip_bytes": 10474,
    "gzip_sha256": "92c8c76b15e81102d7914fdd7ce1029c9c20594911a0c4f5583dde813b8339f3",
    "raw_bytes": 38341,
    "raw_sha256": "7736ceba0a08b68d093729bee1b884dd79fc111218aa68cdb9f539f9ce701628"
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    encoded = SOURCE.read_bytes().strip()
    if len(encoded) != EXPECTED["base64_bytes"] or sha256(encoded) != EXPECTED["base64_sha256"]:
        raise SystemExit("base64 transport integrity failure")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != EXPECTED["gzip_bytes"] or sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise SystemExit("gzip transport integrity failure")
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED["raw_bytes"] or sha256(raw) != EXPECTED["raw_sha256"]:
        raise SystemExit("raw implementation integrity failure")
    TARGET.write_bytes(raw)
    print(json.dumps({"status": "PASS", "target": str(TARGET), **EXPECTED}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
