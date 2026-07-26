from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = sorted(ROOT.glob("source_bundle.tar.gz.b64.part*"))
EXPECTED = {
    "part_count": 2,
    "part_sha256": {
        "source_bundle.tar.gz.b64.part00": "a3cbb8c64f1f7b850305e7961427c0bc826e5baf11906980f9e85a24c32e647e",
        "source_bundle.tar.gz.b64.part01": "e10b6c22a74d00a0cfb07be670cfb63a22d3e6f386f6c7352cb43ebba397c2f3",
    },
    "base64_sha256": "5f2e5f8e50b0b3c4acb6f3286beb4838543b23f6dc109137fe2b638156d01942",
    "gzip_sha256": "8c7d5f5d186bbb4116404bfe4cea7ae0b458a74d242c5efe411f36582d66689a",
    "files": {
        "run.py": "444d0a8158bb3c61e80f658f213005f88ae88b41f0958c354971aded50e8a54d",
        "test_run.py": "7345d60190aa400acbc9a42dd67cbc1fd5a59922c7d7843dba18c2526423cc18",
    },
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    if len(PARTS) != EXPECTED["part_count"]:
        raise RuntimeError(f"expected {EXPECTED['part_count']} parts, found {len(PARTS)}")
    encoded_parts: list[bytes] = []
    for path in PARTS:
        payload = path.read_bytes()
        observed = sha256(payload)
        expected = EXPECTED["part_sha256"][path.name]
        if observed != expected:
            raise RuntimeError(f"part checksum mismatch: {path.name}")
        encoded_parts.append(payload)
    encoded = b"".join(encoded_parts)
    if sha256(encoded) != EXPECTED["base64_sha256"]:
        raise RuntimeError("combined base64 checksum mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise RuntimeError("gzip checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(compressed), mode="r:gz") as archive:
        members = archive.getmembers()
        allowed = set(EXPECTED["files"])
        if {member.name for member in members} != allowed:
            raise RuntimeError("bundle member inventory mismatch")
        for member in members:
            if not member.isfile() or Path(member.name).name != member.name:
                raise RuntimeError(f"unsafe member: {member.name}")
            payload = archive.extractfile(member).read()  # type: ignore[union-attr]
            if sha256(payload) != EXPECTED["files"][member.name]:
                raise RuntimeError(f"source checksum mismatch: {member.name}")
            (ROOT / member.name).write_bytes(payload)
    print("reconstructed", ", ".join(sorted(EXPECTED["files"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
