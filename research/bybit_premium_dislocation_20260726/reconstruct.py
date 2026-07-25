from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run_screen.py.gz.b64"
TARGET = ROOT / "run_screen.py"
EXPECTED = {
    "base64_sha256": "7d5cb47407f48d7fd97b647c62e71be7441408f762d9278dd4c5a772a62487d1",
    "gzip_sha256": "43fb4ed834242b35dcfe5249a42e180adbfb4ada9320e435aff9e884d500627e",
    "raw_sha256": "3b177232914139f4ef99259989ee7a19ad8f630778c432004ea5840cd1f80213",
    "raw_bytes": 49156,
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    # Contents-API transport may wrap base64 text. Normalize ASCII whitespace
    # before verifying the immutable base64, gzip, and raw-source hashes.
    transport = b"".join(SOURCE.read_bytes().split())
    if sha256(transport) != EXPECTED["base64_sha256"]:
        raise SystemExit("base64 transport checksum mismatch")
    compressed = base64.b64decode(transport, validate=True)
    if sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise SystemExit("gzip checksum mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED["raw_bytes"] or sha256(raw) != EXPECTED["raw_sha256"]:
        raise SystemExit("raw source checksum mismatch")
    TARGET.write_bytes(raw)
    print({"target": str(TARGET), "bytes": len(raw), "sha256": sha256(raw)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
