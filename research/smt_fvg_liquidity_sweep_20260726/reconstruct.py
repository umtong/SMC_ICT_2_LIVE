from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "run_screen.py.gz"
TARGET = ROOT / "run_screen.py"
ARCHIVE_SHA256 = "967cb05a46c522777bcc4341c45e0b7b082c3a2f79eced85f27797dbdbfe42bf"
TARGET_SHA256 = "60b205f8d02b2b6ec0190e0dbf49b6db4b3a7d8d29a342139571cf5b847f9fbd"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    archive = ARCHIVE.read_bytes()
    if digest(archive) != ARCHIVE_SHA256:
        raise SystemExit("compressed implementation SHA-256 mismatch")
    source = gzip.decompress(archive)
    if digest(source) != TARGET_SHA256:
        raise SystemExit("implementation SHA-256 mismatch")
    TARGET.write_bytes(source)
    print("SOURCE_RECONSTRUCTION_PASS")
    print(TARGET_SHA256)


if __name__ == "__main__":
    main()
