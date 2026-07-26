#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "bundle_manifest.json").read_text(encoding="utf-8"))
    pieces: list[bytes] = []
    for index in range(int(manifest["part_count"])):
        name = f"source_bundle.tar.gz.b64.part{index:02d}"
        payload = b"".join((root / name).read_bytes().split())
        expected = manifest["parts"][name]
        if len(payload) != int(expected["bytes"]) or sha256(payload) != expected["sha256"]:
            raise RuntimeError(f"bundle part mismatch: {name}")
        pieces.append(payload)
    encoded = b"".join(pieces)
    if sha256(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("combined base64 mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != int(manifest["gzip_bytes"]) or sha256(compressed) != manifest["gzip_sha256"]:
        raise RuntimeError("compressed bundle mismatch")
    tar_bytes = gzip.decompress(compressed)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        if names != set(manifest["files"]):
            raise RuntimeError(f"unexpected source members: {sorted(names)}")
        for member in members:
            if not member.isfile() or "/" in member.name or member.name.startswith("."):
                raise RuntimeError(f"unsafe source member: {member.name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"cannot extract {member.name}")
            data = extracted.read()
            expected = manifest["files"][member.name]
            if len(data) != int(expected["bytes"]) or sha256(data) != expected["sha256"]:
                raise RuntimeError(f"source mismatch: {member.name}")
            (root / member.name).write_bytes(data)
    print(json.dumps({"status": "RECONSTRUCT_PASS", "files": manifest["files"]}, sort_keys=True))


if __name__ == "__main__":
    main()
