from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
B64 = ROOT / "source_bundle.tar.gz.b64"
ARCHIVE_SHA256 = "8d6cdbd05e6152774a5b53cad5ac9355d26ce9e332d16919c962e7ca6bae0b14"
EXPECTED = {
    "run_screen.py": "f2aa95e6cf6c0cf8b5b9de0e9569d6af2294c4ba3b8fc88a973836a45fc733e8",
    "preregistration.json": "c729cd69e30e866a14701d10592dc48c7172ce712d6859fc088144a25af726f3",
    "WORK_CLAIM.json": "22ddbd052ced962b2daca91b768ddb25b69c8c99a48ebfa2441f6b1e0663328a",
    "README.md": "a56fe8d9503d2ad48a72f815b43ef78225f059a941770c74d7f8b70f8831e904",
    "SOURCES.md": "28992b136c61756b1bd989f8027eefbc856c9c2942a5a322a37a1e3cc13f7634",
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
