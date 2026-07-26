from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run.py.gz.b64"
TARGET = ROOT / "run.py"
DIAGNOSTICS = ROOT / "RECONSTRUCTED_SOURCE.json"
EXPECTED = {
    "base64_bytes": 15681,
    "base64_sha256": "72d0026311a47047a14fc12ed53527358bdbeda497582116d85d3d77090ba9d6",
    "gzip_bytes": 11760,
    "gzip_sha256": "4588ee6597ceb8566607eaddbd7f14ff429ed79197b13a6a9bddc228e4ad4824",
    "raw_bytes": 48557,
    "raw_sha256": "8a9f925e82e8e69971dfe8dd1360e83e039be972c41b0164638f0c1f1431ef8c"
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    encoded = SOURCE.read_bytes()
    if sha256(encoded) != EXPECTED["base64_sha256"]:
        raise RuntimeError("base64 transport SHA-256 mismatch")
    normalized = b"".join(encoded.split())
    compressed = base64.b64decode(normalized, validate=True)
    if sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise RuntimeError("gzip payload SHA-256 mismatch")
    raw = gzip.decompress(compressed)
    if sha256(raw) != EXPECTED["raw_sha256"]:
        raise RuntimeError("scientific source SHA-256 mismatch")
    if len(raw) != EXPECTED["raw_bytes"]:
        raise RuntimeError("scientific source length mismatch")
    TARGET.write_bytes(raw)
    DIAGNOSTICS.write_text(json.dumps(EXPECTED, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(EXPECTED, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
