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
    "base64_bytes": 16085,
    "base64_sha256": "72d0026311a47047a14fc12ed53527358bdbeda497582116d85d3d77090ba9d6",
    "gzip_bytes": 12063,
    "gzip_sha256": "c842630e89cbc661f7e6200e7069c7e1fdc1bb17c597e2c92e6342f76fcaad51",
    "raw_bytes": 49951,
    "raw_sha256": "8cc765ecc379da4808599d95f91a5c44d3672483141d34d7781cf9c336fdc3c9"
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    encoded = SOURCE.read_bytes()
    if len(encoded) != EXPECTED["base64_bytes"]:
        raise RuntimeError(
            f"base64 transport length mismatch: {len(encoded)} != {EXPECTED['base64_bytes']}"
        )
    if sha256(encoded) != EXPECTED["base64_sha256"]:
        raise RuntimeError("base64 transport SHA-256 mismatch")
    normalized = b"".join(encoded.split())
    compressed = base64.b64decode(normalized, validate=True)
    if len(compressed) != EXPECTED["gzip_bytes"]:
        raise RuntimeError(
            f"gzip payload length mismatch: {len(compressed)} != {EXPECTED['gzip_bytes']}"
        )
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
