from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "source_manifest.json"
ENCODED = ROOT / "run.py.gz.b64"
TARGET = ROOT / "run.py"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    encoded = b"".join(ENCODED.read_bytes().split())
    if len(encoded) != manifest["base64_bytes"] or digest(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("base64 source identity mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != manifest["gzip_bytes"] or digest(compressed) != manifest["gzip_sha256"]:
        raise RuntimeError("gzip source identity mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != manifest["raw_bytes"] or digest(raw) != manifest["raw_sha256"]:
        raise RuntimeError("raw source identity mismatch")
    compile(raw, str(TARGET), "exec")
    TARGET.write_bytes(raw)
    print(f"RECONSTRUCTED bytes={len(raw)} sha256={digest(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
