from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source_bundle.tar.gz.b64"
EXPECTED_BASE64_SHA256 = "7d1d05b6aadd520197b225f06b1578e8bb91fab3b07d4b7c3bd0908dea897ba9"
EXPECTED_TAR_SHA256 = "72adec13dbb5f6025b28a07abdd9b6ce2c9804fc78ab77f399539f56a28b1ffc"
EXPECTED_FILES = {"run_screen.py", "test_run_screen.py"}

raw = SOURCE.read_bytes()
if hashlib.sha256(raw).hexdigest() != EXPECTED_BASE64_SHA256:
    raise SystemExit("source bundle base64 SHA-256 mismatch")
payload = base64.b64decode(raw, validate=True)
if hashlib.sha256(payload).hexdigest() != EXPECTED_TAR_SHA256:
    raise SystemExit("source bundle tar SHA-256 mismatch")
with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
    members = archive.getmembers()
    names = {member.name for member in members if member.isfile()}
    if names != EXPECTED_FILES:
        raise SystemExit(f"unexpected source inventory: {sorted(names)}")
    for member in members:
        if member.name.startswith("/") or ".." in Path(member.name).parts:
            raise SystemExit(f"unsafe source path: {member.name}")
    archive.extractall(ROOT, filter="data")
print("reconstructed and verified ICT Unicorn sources")
