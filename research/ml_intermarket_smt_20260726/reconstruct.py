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
    "base64_sha256": "4539626562ad4cb0207f586d287aa7c773325b20a0f2e8e269aa7b6bc30ec2a5",
    "gzip_sha256": "6e809514a2d2d7fa04cd23f0d5fada80586e59bb7b6c6578adb01730ece2d0cb",
    "raw_sha256": "12a03ca81fe5ff4d85524832804b0600062081b2e69fcb8458e2e1bc77428bfe",
    "raw_bytes": 63690,
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
