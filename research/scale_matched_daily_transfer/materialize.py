from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "materialized"
PARTS = [ROOT / f"SOURCE_BUNDLE.part{i:02d}.b64" for i in range(4)]


def main() -> None:
    manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text())
    encoded = "".join(p.read_text() for p in PARTS)
    raw = base64.b64decode(encoded)
    got = hashlib.sha256(raw).hexdigest()
    if got != manifest["archive_sha256"]:
        raise SystemExit(f"archive sha mismatch: {got}")
    OUT.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            rel = Path(member.name)
            if rel.is_absolute() or ".." in rel.parts:
                raise SystemExit(f"unsafe archive member: {member.name}")
            name = rel.name
            if name not in manifest["files"]:
                raise SystemExit(f"unregistered archive member: {member.name}")
            data = tf.extractfile(member).read()
            spec = manifest["files"][name]
            if len(data) != spec["bytes"] or hashlib.sha256(data).hexdigest() != spec["sha256"]:
                raise SystemExit(f"file mismatch: {name}")
            (OUT / name).write_bytes(data)
    print(f"materialized {len(manifest['files'])} files into {OUT}")


if __name__ == "__main__":
    main()
