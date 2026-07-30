from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text())
B64 = "".join((ROOT / "run.py.gz.b64").read_text().split())
assert len(B64) == MANIFEST["base64_chars"]
GZIP_BYTES = base64.b64decode(B64)
assert len(GZIP_BYTES) == MANIFEST["gzip_bytes"]
assert hashlib.sha256(GZIP_BYTES).hexdigest() == MANIFEST["gzip_sha256"]
SOURCE = gzip.decompress(GZIP_BYTES)
assert len(SOURCE) == MANIFEST["source_bytes"]
assert hashlib.sha256(SOURCE).hexdigest() == MANIFEST["source_sha256"]
(ROOT / "run.py").write_bytes(SOURCE)
print(ROOT / "run.py")
