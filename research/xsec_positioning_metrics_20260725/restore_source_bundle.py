from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENCODED = HERE / "source_bundle.tar.gz.b64"
OUTER = HERE / "SOURCE_BUNDLE_MANIFEST.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    outer = json.loads(OUTER.read_text(encoding="utf-8"))
    encoded = ENCODED.read_bytes()
    if digest(encoded) != outer["base64_sha256"]:
        raise RuntimeError("source bundle base64 checksum mismatch")
    archive = base64.b64decode(encoded, validate=True)
    if digest(archive) != outer["archive_sha256"]:
        raise RuntimeError("source bundle archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            target = (HERE / member.name).resolve()
            if HERE.resolve() not in target.parents and target != HERE.resolve():
                raise RuntimeError(f"unsafe path: {member.name}")
        tar.extractall(HERE)
    manifest = json.loads((HERE / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    if digest((HERE / "SOURCE_MANIFEST.json").read_bytes()) != outer["manifest_sha256"]:
        raise RuntimeError("source manifest checksum mismatch")
    for row in manifest["files"]:
        path = HERE / row["path"]
        if path.stat().st_size != row["bytes"] or digest(path.read_bytes()) != row["sha256"]:
            raise RuntimeError(f"restored source mismatch: {path}")
        print(path, row["sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
