#!/usr/bin/env python3
from __future__ import annotations
import base64, gzip, hashlib, io, tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
payload = base64.b64decode((ROOT / "SOURCE_BUNDLE.tar.gz.b64").read_text())
expected = "feee96b615f46b9de04ae09c613e6b28ec4234f0ebafd35ceed1c9b6ad1d1960"
actual = hashlib.sha256(payload).hexdigest()
if actual != expected:
    raise SystemExit(f"source bundle SHA mismatch: {actual}")
with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as handle:
    tar_data = handle.read()
with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:") as archive:
    for member in archive.getmembers():
        if member.name not in {"screen.py", "test_screen.py"}:
            raise SystemExit(f"unexpected member: {member.name}")
    archive.extractall(ROOT, filter="data")
print(actual)
