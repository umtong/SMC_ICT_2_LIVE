from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PART_SHA256 = {
    "source_bundle.tar.gz.b64.part00": "148f1f0e157061bd943026ae069fa85239fbfda447475d476273eb3e44536c35",
    "source_bundle.tar.gz.b64.part01": "c9f1507a0f371e1f31d8459e8f84eae378785c9203dfaa8c280abb0f304ab33e",
    "source_bundle.tar.gz.b64.part02": "c109380e3b1a5227bb6299002fae227716e61a2689ac601ec798ba68ea675bf6",
    "source_bundle.tar.gz.b64.part03": "0ebaafa91cf6859064c80a76a3fc28c21d072d55b49ddbf1db9cfbc798d30aa9",
    "source_bundle.tar.gz.b64.part04": "5db991511051640ba4457fa0cb90764a8534bb3cdda2f158253dd6b318eca95c"
}
B64_SHA256 = "95a4b4b43fd1be5a9951d51a69532fdc80414910b4af95a5583f38ff5331b74f"
ARCHIVE_SHA256 = "ff77f4603663898cb881c9eaa726fd7a8fe840ab01970b205ecb815e68446e95"
EXPECTED = {
    "README.md": "d8407d818bbd1f4dbe303efac0d26293831b95dc34e634dea21fe55cd0737bfc",
    "SOURCES.md": "1e670a1b419d166998eadd9065559e5c23cb6bf0c0ab2aa720f9d9ed2db54a96",
    "WORK_CLAIM.json": "83ff900702994d6c824431c94aa86b70f16d18b091853f7e900efa22a1a462b2",
    "preregistration.json": "53884030b0fb760a74e4dfe27b044f943784f442780b0aa437e0f829a9ccddaa",
    "run_screen.py": "234eb92e07f06506331c5dbb023bc695c6c7a289427b35bbb97e168d0f296bc0"
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
            if not member.isfile() or member.name != name or member.name.startswith("/") or ".." in Path(member.name).parts:
                raise SystemExit(f"unsafe source member: {member.name}")
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
