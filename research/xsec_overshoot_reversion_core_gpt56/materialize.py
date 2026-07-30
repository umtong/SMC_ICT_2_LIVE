from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text())
encoded = (ROOT / "SOURCE.py.gz.b64").read_text().strip()
raw_gzip = base64.b64decode(encoded)
assert len(encoded) == MANIFEST["base64_chars"]
assert len(raw_gzip) == MANIFEST["gzip_bytes"]
assert hashlib.sha256(raw_gzip).hexdigest() == MANIFEST["gzip_sha256"]
source = gzip.decompress(raw_gzip)
assert len(source) == MANIFEST["source_bytes"]
assert hashlib.sha256(source).hexdigest() == MANIFEST["source_sha256"]
out = ROOT / "materialized"
out.mkdir(exist_ok=True)
path = out / MANIFEST["source_file"]
path.write_bytes(source)
print(path)
