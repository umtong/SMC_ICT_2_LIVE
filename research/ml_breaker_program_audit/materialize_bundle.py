from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
PARTS = HERE / "bundle_parts"
MANIFEST = HERE / "bundle_manifest.json"
ROOT = Path(__file__).resolve().parents[2]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_member(member: tarfile.TarInfo) -> bool:
    path = PurePosixPath(member.name)
    return not path.is_absolute() and ".." not in path.parts


def materialize() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    encoded_parts: list[str] = []
    for item in manifest["parts"]:
        path = PARTS / item["name"]
        text = path.read_text(encoding="ascii")
        if len(text) != int(item["chars"]):
            raise RuntimeError(f"part length mismatch: {path}")
        if sha256_bytes(text.encode("ascii")) != item["sha256"]:
            raise RuntimeError(f"part hash mismatch: {path}")
        encoded_parts.append(text)
    archive = base64.b64decode("".join(encoded_parts), validate=True)
    if len(archive) != int(manifest["archive_size"]):
        raise RuntimeError("archive size mismatch")
    if sha256_bytes(archive) != manifest["archive_sha256"]:
        raise RuntimeError("archive hash mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        members = bundle.getmembers()
        if not all(safe_member(member) for member in members):
            raise RuntimeError("unsafe archive member")
        bundle.extractall(ROOT)


if __name__ == "__main__":
    materialize()
