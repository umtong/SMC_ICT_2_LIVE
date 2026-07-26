from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "source_manifest.json"
TARGET = ROOT / "run.py"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    names = sorted(manifest["parts"])
    if len(names) != manifest["part_count"]:
        raise RuntimeError("part-count mismatch")
    pieces: list[bytes] = []
    for name in names:
        payload = b"".join((ROOT / name).read_bytes().split())
        expected = manifest["parts"][name]
        if len(payload) != expected["bytes"] or sha256(payload) != expected["sha256"]:
            raise RuntimeError(f"part identity mismatch: {name}")
        pieces.append(payload)
    encoded = b"".join(pieces)
    if len(encoded) != manifest["base64_bytes"] or sha256(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("combined Base64 identity mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != manifest["gzip_bytes"] or sha256(compressed) != manifest["gzip_sha256"]:
        raise RuntimeError("GZIP identity mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != manifest["raw_bytes"] or sha256(raw) != manifest["raw_sha256"]:
        raise RuntimeError("raw-source identity mismatch")
    compile(raw, str(TARGET), "exec")
    TARGET.write_bytes(raw)
    print(f"reconstructed {TARGET} bytes={len(raw)} sha256={sha256(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
