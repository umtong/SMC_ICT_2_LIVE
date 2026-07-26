from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = tuple(sorted(ROOT.glob("implementation.b64.part*")))
EXPECTED_PART_COUNT = 3
EXPECTED_COMPRESSED_SHA256 = "24a9b559368326a9b35348a946c6b7c6569c8f42738403794cdecef8a760fee7"
EXPECTED_IMPLEMENTATION_SHA256 = "ed9be20707cb25836077f7a2e72cfa8d6339c2ffffbb79d97d11fbed5574316b"

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
