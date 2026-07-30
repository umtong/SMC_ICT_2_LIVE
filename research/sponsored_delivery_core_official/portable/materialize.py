#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "PORTABLE_BUNDLE_MANIFEST.json"
OUTPUT = ROOT / "materialized"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    chunks: list[str] = []
    for part in manifest["parts"]:
        path = ROOT / part["file"]
        compact = "".join(path.read_text().split())
        # GitHub's text contents API may normalize the terminal newline. The
        # scientific identity is therefore enforced on the reconstructed
        # archive and every extracted member, not on transport whitespace.
        assert len(compact) == part["chars"]
        chunks.append(compact)
    text = "".join(chunks)
    assert len(text) == manifest["base64_chars"]
    archive = base64.b64decode(text, validate=True)
    assert len(archive) == manifest["archive_bytes"]
    assert sha256(archive) == manifest["archive_sha256"]
    tar_bytes = gzip.decompress(archive)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for old in OUTPUT.iterdir():
        if old.is_file():
            old.unlink()
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
        names = {member.name for member in tf.getmembers()}
        assert names == set(manifest["members"])
        for member in tf.getmembers():
            assert member.isfile() and "/" not in member.name and ".." not in member.name
            data = tf.extractfile(member).read()
            expected = manifest["members"][member.name]
            assert len(data) == expected["bytes"]
            assert sha256(data) == expected["sha256"]
            (OUTPUT / member.name).write_bytes(data)
    print(json.dumps({"archive_sha256": manifest["archive_sha256"], "members": manifest["members"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
