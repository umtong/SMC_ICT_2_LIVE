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
    "base64_bytes": 14444,
    "base64_sha256": "7a288e93a58e8fba41de928208c966a61132c72206d152b714e9ec5b0ebdde7b",
    "gzip_bytes": 10832,
    "gzip_sha256": "99ca27b53a771d00d89a2a289e9c10ec96a75c5ca714ab3195856e4f71a4ad46",
    "raw_bytes": 39343,
    "raw_sha256": "366aa871dcff28a49e64782560737d0a7bc54c0ad97effe40b72d24f1b0f4bf8"
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
