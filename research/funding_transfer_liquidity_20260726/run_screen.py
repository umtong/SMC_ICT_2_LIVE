from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = tuple(sorted(ROOT.glob("implementation.b64.part*")))
EXPECTED_PART_COUNT = 2
EXPECTED_COMPRESSED_SHA256 = "430f9963f6767e250520bdcb10e43cb9b1b40a187f0d779c7f384d9ad0b26abf"
EXPECTED_IMPLEMENTATION_SHA256 = "a5b3b5e41e6697de766ee5b3aef4712401a2350ea3e88a97f07ada57eab636fe"

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
