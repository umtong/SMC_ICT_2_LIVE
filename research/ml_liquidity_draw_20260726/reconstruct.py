from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "run.py"
PARTS = sorted(ROOT.glob("run_py.gz.b64.part*"))
EXPECTED = {
    "part_count": 2,
    "base64_sha256": "bb70a8324f9ab98db7215402b158916e473e300e3da2201d36c44c29866bdfc6",
    "gzip_sha256": "7b7f79a9672ce5d7c7f0d4a2e31f5d5d1e0c2ec7b8edf8d6a32386c33707f54c",
    "raw_sha256": "87957a81a70cc9c777f555bb23ccbeb2ecae50c50ff0d730ce72de974b30c741",
    "raw_bytes": 51394,
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    if len(PARTS) != EXPECTED["part_count"]:
        raise RuntimeError(f"expected {EXPECTED['part_count']} parts, found {len(PARTS)}")
    encoded = "".join(path.read_text(encoding="ascii").strip() for path in PARTS).encode("ascii")
    if sha256(encoded) != EXPECTED["base64_sha256"]:
        raise RuntimeError("base64 checksum mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise RuntimeError("gzip checksum mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED["raw_bytes"] or sha256(raw) != EXPECTED["raw_sha256"]:
        raise RuntimeError("raw source checksum mismatch")
    TARGET.write_bytes(raw)
    print(f"reconstructed {TARGET} ({len(raw)} bytes, {sha256(raw)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
