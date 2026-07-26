from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PART_SHA256 = {
    "source_bundle.tar.gz.b64.part00": "7b8a6d9e9c62e1dc49498efa5e11ee985cf5cf0a7604e1733141111101ec6fc6",
    "source_bundle.tar.gz.b64.part01": "d7769cf754aee3514d94d758525e9b0868c4d77a5ef0ba1c2aef4b522f4df3ec",
    "source_bundle.tar.gz.b64.part02": "223037dd2b39cd3d9f215159168484373e2ccd346fb3eaaa61eb90486419d43a",
    "source_bundle.tar.gz.b64.part03": "67d535445af0b952d6e6acfc12da647cfca2ac35c33a607c14e811c966f017a1",
    "source_bundle.tar.gz.b64.part04": "e7e42f17a179514dbf5093cf869db7fd41c5b5029cd899f6dea31f7721a0cc8b",
}
B64_SHA256 = "28108e02c1bfe9e061bf641474699e5bf713da803ad0133e05dd727dfdd0d889"
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
    encoded_parts: list[bytes] = []
    for name, expected_sha in PART_SHA256.items():
        data = (ROOT / name).read_bytes()
        if digest(data) != expected_sha:
            raise SystemExit(f"source transport part SHA-256 mismatch: {name}")
        encoded_parts.append(data)
    encoded = b"".join(encoded_parts)
    if digest(encoded) != B64_SHA256:
        raise SystemExit("source base64 transport SHA-256 mismatch")
    raw = base64.b64decode(encoded, validate=True)
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
