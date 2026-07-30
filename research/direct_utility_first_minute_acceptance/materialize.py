#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
manifest = json.loads((HERE / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
parts = []
for row in manifest["bundle_parts"]:
    path = HERE / row["path"]
    parts.append("".join(path.read_text(encoding="utf-8").split()))
joined = "".join(parts)
if len(joined) != manifest["base64_chars"]:
    raise SystemExit(f"joined base64 length mismatch: {len(joined)}")
if hashlib.sha256(joined.encode("ascii")).hexdigest() != manifest["base64_sha256"]:
    raise SystemExit("joined base64 hash mismatch")
raw = base64.b64decode(joined, validate=True)
if len(raw) != manifest["archive_bytes"]:
    raise SystemExit("archive byte count mismatch")
if hashlib.sha256(raw).hexdigest() != manifest["archive_sha256"]:
    raise SystemExit("archive hash mismatch")
out = HERE / "materialized"
if out.exists():
    shutil.rmtree(out)
out.mkdir()
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
    root = out.resolve()
    for member in archive.getmembers():
        target = (out / member.name).resolve()
        if target != root and root not in target.parents:
            raise SystemExit(f"unsafe archive member: {member.name}")
    archive.extractall(out, filter="data")
for row in manifest["files"]:
    path = out / row["path"]
    if not path.is_file() or path.stat().st_size != row["bytes"]:
        raise SystemExit(f"file size mismatch: {row['path']}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
        raise SystemExit(f"file hash mismatch: {row['path']}")
print(out)
