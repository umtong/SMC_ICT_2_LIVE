from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
B64 = ROOT / "source_bundle.tar.gz.b64"
ARCHIVE_SHA256 = "6cfc247ff564c852f1859443a36b34cc2d0b59e56001f3445da6bdd5bdfcae5a"
EXPECTED = {
    "run_screen.py": "43002e7aad3701e55181b6b80d0fcbe8a88b4957dc198cf3bfaf9df5d5683ec8",
    "preregistration.json": "c729cd69e30e866a14701d10592dc48c7172ce712d6859fc088144a25af726f3",
    "WORK_CLAIM.json": "22ddbd052ced962b2daca91b768ddb25b69c8c99a48ebfa2441f6b1e0663328a",
    "README.md": "f73dc33a9b6b521261a4b3eb26ea03ca51559c69c5ba9c284dc158bb1cf7f9cf",
    "SOURCES.md": "28992b136c61756b1bd989f8027eefbc856c9c2942a5a322a37a1e3cc13f7634",
    "CORRECTION_001_EMPTY_ROUTE_SCHEMA.json": "a1160b19e570ebbca3ba6d26f9ca5dc764c56a82e69f8ed592adb557c0742318",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    raw = base64.b64decode(B64.read_bytes(), validate=True)
    if digest(raw) != ARCHIVE_SHA256:
        raise SystemExit("source archive SHA-256 mismatch")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        names = sorted(member.name for member in archive.getmembers() if member.isfile())
        if names != sorted(EXPECTED):
            raise SystemExit(f"unexpected source inventory: {names}")
        for name, expected_sha in EXPECTED.items():
            member = archive.getmember(name)
            handle = archive.extractfile(member)
            if handle is None:
                raise SystemExit(f"missing source member: {name}")
            data = handle.read()
            if digest(data) != expected_sha:
                raise SystemExit(f"member SHA-256 mismatch: {name}")
            (ROOT / name).write_bytes(data)
    print("SOURCE_RECONSTRUCTION_PASS")


if __name__ == "__main__":
    main()
