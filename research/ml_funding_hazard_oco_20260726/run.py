from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_PATH = ROOT / "run_impl.py.gz.b64"
EXPECTED_COMPRESSED_SHA256 = "2948efdb675465241277445be5faedb4388c2201a8d4bcb8245fb00027b10010"
EXPECTED_SOURCE_SHA256 = "7bd5f6787a6676535123efd6398dc1c997020099d0fdf62b8c8c0edf7b28ecb7"

encoded = "".join(SOURCE_PATH.read_text(encoding="utf-8").split())
compressed = base64.b64decode(encoded, validate=True)
if hashlib.sha256(compressed).hexdigest() != EXPECTED_COMPRESSED_SHA256:
    raise RuntimeError("compressed implementation SHA-256 mismatch")
source = gzip.decompress(compressed)
if hashlib.sha256(source).hexdigest() != EXPECTED_SOURCE_SHA256:
    raise RuntimeError("scientific implementation SHA-256 mismatch")
exec(compile(source, str(ROOT / "_bundled_run_impl.py"), "exec"), globals(), globals())
