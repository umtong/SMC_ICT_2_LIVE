#!/usr/bin/env python3
from __future__ import annotations
import base64, gzip, hashlib, io, json, tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "SOURCE_BUNDLE.tar.gz.b64"
EXPECTED_ARCHIVE_SHA256 = "0ea2750a9e089a2b4d9e994deb3f5903da4ae589a57522fcd13a7c023b5d8131"
MEMBERS = {"channel_base.py": "e468b50035344b355ca610afdd4ee6deaff30a0f8722441c6a38d1ceca963f38", "run.py": "a5d1d42ad71c02bab8cbbc534e9e457d6dc009fbf776cfbb87054a44f44077f7", "test_semantics.py": "12b5868c32dfa746f2a81a1d6021547f9032a6afcb7b1a5a81def45ebdd6f7b6"}

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main() -> None:
    raw = base64.b64decode(BUNDLE.read_text(encoding="utf-8"))
    assert sha256(raw) == EXPECTED_ARCHIVE_SHA256
    out = ROOT / "materialized"
    out.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        for member in tf.getmembers():
            assert member.name in MEMBERS and member.isfile()
            data = tf.extractfile(member).read()
            assert sha256(data) == MEMBERS[member.name]
            (out / member.name).write_bytes(data)
    assert set(p.name for p in out.iterdir() if p.is_file()) == set(MEMBERS)
    print(json.dumps({"archive_sha256": EXPECTED_ARCHIVE_SHA256, "members": MEMBERS}, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
