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
    "normalized_base64_bytes": 16084,
    "gzip_bytes": 12063,
    "gzip_sha256": "c842630e89cbc661f7e6200e7069c7e1fdc1bb17c597e2c92e6342f76fcaad51",
    "raw_bytes": 49951,
    "raw_sha256": "8cc765ecc379da4808599d95f91a5c44d3672483141d34d7781cf9c336fdc3c9",
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    encoded = SOURCE.read_bytes()
    normalized = b"".join(encoded.split())
    if len(normalized) != EXPECTED["normalized_base64_bytes"]:
        raise RuntimeError(
            "normalized base64 length mismatch: "
            f"{len(normalized)} != {EXPECTED['normalized_base64_bytes']}"
        )
    compressed = base64.b64decode(normalized, validate=True)
    if len(compressed) != EXPECTED["gzip_bytes"]:
        raise RuntimeError(
            f"gzip payload length mismatch: {len(compressed)} != {EXPECTED['gzip_bytes']}"
        )
    if sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise RuntimeError("gzip payload SHA-256 mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED["raw_bytes"]:
        raise RuntimeError("scientific source length mismatch")
    if sha256(raw) != EXPECTED["raw_sha256"]:
        raise RuntimeError("scientific source SHA-256 mismatch")
    TARGET.write_bytes(raw)
    diagnostics = {
        **EXPECTED,
        "observed_envelope_bytes": len(encoded),
        "observed_envelope_sha256": sha256(encoded),
        "observed_normalized_base64_sha256": sha256(normalized),
    }
    DIAGNOSTICS.write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(diagnostics, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
