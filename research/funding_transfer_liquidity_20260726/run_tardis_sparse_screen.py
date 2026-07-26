from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = tuple(sorted(ROOT.glob("tardis_sparse_impl.b64.part*")))
EXPECTED_PART_COUNT = 2
EXPECTED_COMPRESSED_SHA256 = "31f42859c5fb7d543575897d908c139130788d32dc5a7d2603de71b8049ba578"
EXPECTED_IMPLEMENTATION_SHA256 = "d4880a734be09ab2da992e2be29f37ab289f4ae3f64fac48196c708af5715ac4"

if len(PARTS) != EXPECTED_PART_COUNT:
    raise RuntimeError(f"implementation part count {len(PARTS)} != {EXPECTED_PART_COUNT}")
encoded = "".join("".join(path.read_text(encoding="utf-8").split()) for path in PARTS)
compressed = base64.b64decode(encoded, validate=True)
if hashlib.sha256(compressed).hexdigest() != EXPECTED_COMPRESSED_SHA256:
    raise RuntimeError("compressed Tardis sparse implementation SHA-256 mismatch")
source = gzip.decompress(compressed)
if hashlib.sha256(source).hexdigest() != EXPECTED_IMPLEMENTATION_SHA256:
    raise RuntimeError("Tardis sparse scientific implementation SHA-256 mismatch")
BUNDLED_IMPLEMENTATION_SHA256 = EXPECTED_IMPLEMENTATION_SHA256
exec(compile(source, str(ROOT / "_bundled_tardis_sparse.py"), "exec"), globals(), globals())
