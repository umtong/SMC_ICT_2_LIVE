from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = tuple(sorted(ROOT.glob("implementation.b64.part*")))
EXPECTED_PART_COUNT = 3
EXPECTED_COMPRESSED_SHA256 = "d608cf5e7fc570f9dd911a14c12d5185123b2aeadf9376674ee2928b9d558b69"
EXPECTED_IMPLEMENTATION_SHA256 = "53980d59ac304cf5f992151e30480f876cfca61633c4a7c7b68af4c76c43e1ff"

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
