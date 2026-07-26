from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "parent_order_ml_source_manifest.json"
TARGET = ROOT / "run_parent_order_ml.py"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    parts = manifest.get("parts")
    if not isinstance(parts, dict) or len(parts) != int(manifest["part_count"]):
        raise RuntimeError("source part manifest mismatch")

    payloads: list[bytes] = []
    for name in sorted(parts):
        path = ROOT / name
        payload = b"".join(path.read_bytes().split())
        expected = parts[name]
        if len(payload) != int(expected["bytes"]) or sha256(payload) != expected["sha256"]:
            raise RuntimeError(f"source part identity mismatch: {name}")
        payloads.append(payload)

    encoded = b"".join(payloads)
    if len(encoded) != int(manifest["base64_bytes"]) or sha256(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("combined base64 identity mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != int(manifest["gzip_bytes"]) or sha256(compressed) != manifest["gzip_sha256"]:
        raise RuntimeError("gzip source identity mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != int(manifest["raw_bytes"]) or sha256(raw) != manifest["raw_sha256"]:
        raise RuntimeError("raw source identity mismatch")

    compile(raw, str(TARGET), "exec")
    TARGET.write_bytes(raw)
    print(
        f"RECONSTRUCTED {TARGET} parts={len(payloads)} bytes={len(raw)} "
        f"sha256={sha256(raw)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
