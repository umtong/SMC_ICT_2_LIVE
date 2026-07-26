from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = (
    ("run.py.gz.b64.part00", 4000, "5effca1cf6d38cc57c9a804eddb53cda720acc373eb8a6d5e6e853c162a1aad3"),
    ("run.py.gz.b64.part01", 4000, "52c4df5f821824d121dd714a340d2ae171f42786b5dcf7b620c84f23a81f69cc"),
    ("run.py.gz.b64.part02", 4000, "0c5d31e80dade2e249834d7d61efb01044423181f0ec393c2a205df6eb765095"),
    ("run.py.gz.b64.part03", 3092, "492d15b28b0151137cb41a9ebb28de05573a0af16c0ed18f95c9126e79e6cecd"),
)
EXPECTED = {
    "base64_bytes": 15092,
    "base64_sha256": "457b4e55dc5cfc564ee3055ed5b7b87313b0d7ae5544685a255d0dda2d5fd1e1",
    "gzip_bytes": 11317,
    "gzip_sha256": "327da831fe816b55462c556b1393a1b43aaebcb9039c4766e1906d707adc4f99",
    "raw_bytes": 41582,
    "raw_sha256": "1aa1f4d93ec4d5500491a923812ed210997b2fb026129ecbb2d3a44af4e21339",
}
TARGET = ROOT / "run.py"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    fragments: list[bytes] = []
    observed: list[dict[str, object]] = []
    for name, expected_bytes, expected_hash in PARTS:
        path = ROOT / name
        if not path.is_file():
            raise SystemExit(f"missing source transport part: {path}")
        payload = path.read_bytes().strip()
        record = {"name": name, "bytes": len(payload), "sha256": sha256(payload)}
        observed.append(record)
        if len(payload) != expected_bytes or sha256(payload) != expected_hash:
            raise SystemExit(f"source transport part integrity failure: {record}")
        fragments.append(payload)

    encoded = b"".join(fragments)
    if len(encoded) != EXPECTED["base64_bytes"] or sha256(encoded) != EXPECTED["base64_sha256"]:
        raise SystemExit("combined base64 transport integrity failure")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != EXPECTED["gzip_bytes"] or sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise SystemExit("gzip transport integrity failure")
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED["raw_bytes"] or sha256(raw) != EXPECTED["raw_sha256"]:
        raise SystemExit("raw implementation integrity failure")
    TARGET.write_bytes(raw)
    print(json.dumps({"status": "PASS", "target": str(TARGET), "parts": observed, **EXPECTED}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
