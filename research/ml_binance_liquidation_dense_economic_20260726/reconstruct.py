from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "SOURCE_MANIFEST.json"
TARGET = ROOT / "run.py"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    parts = []
    for item in manifest["parts"]:
        path = ROOT / item["name"]
        payload = path.read_bytes()
        if len(payload) != int(item["bytes"]) or digest(payload) != item["sha256"]:
            raise RuntimeError(f"part identity mismatch: {path.name}")
        parts.append(payload)
    encoded = b"".join(parts)
    if len(encoded) != int(manifest["base64_bytes"]) or digest(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("combined base64 identity mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != int(manifest["gzip_bytes"]) or digest(compressed) != manifest["gzip_sha256"]:
        raise RuntimeError("gzip identity mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != int(manifest["raw_bytes"]) or digest(raw) != manifest["raw_sha256"]:
        raise RuntimeError("raw source identity mismatch")
    compile(raw, str(TARGET), "exec")
    TARGET.write_bytes(raw)
    print(f"RECONSTRUCTED bytes={len(raw)} sha256={digest(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
