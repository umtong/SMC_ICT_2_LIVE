from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "reconstructed"
MANIFEST = ROOT / "source_manifest.json"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    parts = []
    for item in manifest["parts"]:
        path = ROOT / item["path"]
        raw = path.read_bytes().strip()
        if len(raw) != int(item["chars"]):
            raise ValueError(f"character-count mismatch: {path.name}")
        if sha256(raw) != item["sha256"]:
            raise ValueError(f"part hash mismatch: {path.name}")
        parts.append(raw)
    archive = base64.b64decode(b"".join(parts), validate=True)
    if len(archive) != int(manifest["archive"]["bytes"]):
        raise ValueError("archive size mismatch")
    if sha256(archive) != manifest["archive"]["sha256"]:
        raise ValueError("archive hash mismatch")
    tar_payload = gzip.decompress(archive)
    OUT.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tar_payload), mode="r:") as tar:
        members = tar.getmembers()
        expected = set(manifest["files"])
        observed = {member.name for member in members}
        if observed != expected:
            raise ValueError(f"archive members differ: {observed} != {expected}")
        for member in members:
            if not member.isfile() or Path(member.name).name != member.name:
                raise ValueError(f"unsafe archive member: {member.name}")
            handle = tar.extractfile(member)
            if handle is None:
                raise ValueError(f"cannot extract {member.name}")
            payload = handle.read()
            spec = manifest["files"][member.name]
            if len(payload) != int(spec["bytes"]) or sha256(payload) != spec["sha256"]:
                raise ValueError(f"source mismatch: {member.name}")
            (OUT / member.name).write_bytes(payload)
    (OUT / "reconstruction.json").write_text(
        json.dumps({"schema_version": 1, "files": manifest["files"]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest["files"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
