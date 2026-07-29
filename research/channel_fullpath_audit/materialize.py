from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text())
RAW = base64.b64decode((ROOT / "SOURCE_BUNDLE.tar.gz.b64").read_text().strip())
assert hashlib.sha256(RAW).hexdigest() == MANIFEST["archive_sha256"]

with tarfile.open(fileobj=io.BytesIO(RAW), mode="r:gz") as archive:
    for member in archive.getmembers():
        target = (ROOT / member.name).resolve()
        if ROOT.resolve() not in target.parents:
            raise RuntimeError(f"unsafe archive path: {member.name}")
    archive.extractall(ROOT, filter="data")

for item in MANIFEST["files"]:
    path = ROOT / item["path"]
    assert path.stat().st_size == item["bytes"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]

print(f"materialized {len(MANIFEST['files'])} source files")
