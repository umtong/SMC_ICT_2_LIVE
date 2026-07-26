from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "BUNDLE_MANIFEST.json"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def reconstruct_one(spec: dict) -> None:
    encoded = b"".join((ROOT / part).read_bytes() for part in spec["parts"])
    if sha256_bytes(encoded) != spec["base64_sha256"]:
        raise ValueError(f"base64 hash mismatch for {spec['output']}")
    compressed = base64.b64decode(encoded, validate=True)
    if sha256_bytes(compressed) != spec["gzip_sha256"]:
        raise ValueError(f"gzip hash mismatch for {spec['output']}")
    raw = gzip.decompress(compressed)
    if sha256_bytes(raw) != spec["raw_sha256"]:
        raise ValueError(f"raw hash mismatch for {spec['output']}")
    destination = ROOT / spec["output"]
    destination.write_bytes(raw)


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for spec in manifest["bundles"]:
        reconstruct_one(spec)
    print("reconstruction PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
