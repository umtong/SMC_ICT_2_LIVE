#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = {
    "run.py": ("run.py.gz.b64", "99d8cb00dd16d1faf7202a05f80be82b16f50690427dcbec58c71b212c18dc08"),
    "evaluate.py": ("evaluate.py.gz.b64", "5f1b1f86af29f7141c39bcf087d5c7e9a8293291e79242a9fd311d85665c928d"),
}

for output_name, (payload_name, expected_sha256) in FILES.items():
    payload = "".join((ROOT / payload_name).read_text(encoding="utf-8").split())
    raw = gzip.decompress(base64.b64decode(payload))
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise SystemExit(f"{output_name}: sha256 mismatch {actual} != {expected_sha256}")
    target = ROOT / output_name
    target.write_bytes(raw)
    target.chmod(0o755)
    print(f"materialized {target.name} sha256={actual}")
