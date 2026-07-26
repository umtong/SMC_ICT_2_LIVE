from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_PATH = ROOT / "run_impl.py.gz.b64"
EXPECTED_COMPRESSED_SHA256 = "8d73152bc26a55ea7b515bdb86a8d19c284461389bd9e35af8a8d72503fbf8ef"
EXPECTED_SOURCE_SHA256 = "eb4ef78d7b226490288463bef5ae5bce15bc313c5a45fab6e95520a3acb1b735"

encoded = "".join(SOURCE_PATH.read_text(encoding="utf-8").split())
compressed = base64.b64decode(encoded, validate=True)
if hashlib.sha256(compressed).hexdigest() != EXPECTED_COMPRESSED_SHA256:
    raise RuntimeError("compressed implementation SHA-256 mismatch")
source = gzip.decompress(compressed)
if hashlib.sha256(source).hexdigest() != EXPECTED_SOURCE_SHA256:
    raise RuntimeError("scientific implementation SHA-256 mismatch")
exec(compile(source, str(ROOT / "_bundled_run_impl.py"), "exec"), globals(), globals())
