from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "run_source.py.gz.b64"
EXPECTED_SOURCE_SHA256 = "15ffbd9ac15372297a994588fc7edd6b3b9b6c112c29a81c6016fb50aaf87d1a"
EXPECTED_SOURCE_BYTES = 35064

payload = PAYLOAD.read_text(encoding="utf-8").strip()
source = gzip.decompress(base64.b64decode(payload))
if len(source) != EXPECTED_SOURCE_BYTES:
    raise RuntimeError(f"unexpected decoded source length: {len(source)}")
actual_sha256 = hashlib.sha256(source).hexdigest()
if actual_sha256 != EXPECTED_SOURCE_SHA256:
    raise RuntimeError(
        f"decoded source hash mismatch: {actual_sha256} != {EXPECTED_SOURCE_SHA256}"
    )

source_path = str(ROOT / "run_source.py")
namespace = {"__name__": "__main__", "__file__": source_path}
exec(compile(source, source_path, "exec"), namespace)
