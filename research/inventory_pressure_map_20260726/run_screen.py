from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = tuple(sorted(ROOT.glob("implementation.b64.part*")))
EXPECTED_PART_COUNT = 2
EXPECTED_COMPRESSED_SHA256 = "535fa0ffe310b4f377dee6fdf60e666c61f3436b30b08da4effc3f0ae6021292"
EXPECTED_IMPLEMENTATION_SHA256 = "ddc5d9c6dd22a27d5f3f86572f5c4b80780396c583f29de44ef1d175fc2bf384"

if len(PARTS) != EXPECTED_PART_COUNT:
    raise RuntimeError(f"implementation part count {len(PARTS)} != {EXPECTED_PART_COUNT}")
encoded = "".join("".join(path.read_text(encoding="utf-8").split()) for path in PARTS)
compressed = base64.b64decode(encoded, validate=True)
if hashlib.sha256(compressed).hexdigest() != EXPECTED_COMPRESSED_SHA256:
    raise RuntimeError("compressed implementation SHA-256 mismatch")
source = gzip.decompress(compressed)
if hashlib.sha256(source).hexdigest() != EXPECTED_IMPLEMENTATION_SHA256:
    raise RuntimeError("scientific implementation SHA-256 mismatch")
BUNDLED_IMPLEMENTATION_SHA256 = EXPECTED_IMPLEMENTATION_SHA256
exec(compile(source, str(ROOT / "_bundled_implementation.py"), "exec"), globals(), globals())
