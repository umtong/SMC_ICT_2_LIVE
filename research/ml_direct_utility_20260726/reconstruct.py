from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "source_manifest.json"
TARGET = ROOT / "run.py"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    parts = manifest.get("source_parts", [])
    if len(parts) != manifest.get("part_count"):
        raise RuntimeError("source part count mismatch")
    encoded_parts: list[bytes] = []
    for record in parts:
        path = ROOT / record["name"]
        payload = b"".join(path.read_bytes().split())
        if len(payload) != record["bytes"] or digest(payload) != record["sha256"]:
            raise RuntimeError(f"source part identity mismatch: {path.name}")
        encoded_parts.append(payload)
    encoded = b"".join(encoded_parts)
    if len(encoded) != manifest["base64_bytes"] or digest(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("combined base64 source identity mismatch")
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
