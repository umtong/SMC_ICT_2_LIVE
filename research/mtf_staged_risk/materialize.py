#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLES = (
    ("source_bundle.tar.gz.b64", "628ec87150c307802c02fe43b4e64b2c524745563f333ea3e2d7dd6aaf444bd9", True),
    ("evidence_bundle.tar.gz.b64", "774dacfeabd5ded71f7f3196fcc429c0cfb121fb484547906c976bfa36bc2ba0", False),
)

for payload_name, expected_sha256, required in BUNDLES:
    payload = ROOT / payload_name
    if not payload.is_file():
        if required:
            raise SystemExit(f"missing required payload: {payload_name}")
        print(
            f"WARNING: optional historical evidence carrier is absent: {payload_name}; "
            "source validation continues, but the compact committed result is not a full evidence replay"
        )
        continue
    encoded = "".join(payload.read_text(encoding="utf-8").split())
    raw = base64.b64decode(encoded, validate=True)
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise SystemExit(f"{payload_name}: sha256 mismatch {actual} != {expected_sha256}")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not member.isfile():
                raise SystemExit(f"unsafe or unsupported archive member: {member.name}")
        archive.extractall(ROOT, members=members, filter="data")
    print(f"materialized {len(members)} files from {payload_name}; sha256={actual}")

for name in ("run.py", "generate_symbol.py", "evaluate_generated.py", "winner_removal.py", "deep_exit_diag.py", "diagnose.py", "test_run.py"):
    path = ROOT / name
    if not path.is_file():
        raise SystemExit(f"missing materialized source: {name}")
    path.chmod(0o755)
