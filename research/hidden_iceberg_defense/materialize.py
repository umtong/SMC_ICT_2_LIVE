#!/usr/bin/env python3
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text())
b64 = "".join((ROOT / "run.py.gz.b64").read_text().split())
assert len(b64) == manifest["base64_chars"]
gz = base64.b64decode(b64)
assert len(gz) == manifest["gzip_bytes"]
assert hashlib.sha256(gz).hexdigest() == manifest["gzip_sha256"]
raw = gzip.decompress(gz)
assert len(raw) == manifest["source_bytes"]
assert hashlib.sha256(raw).hexdigest() == manifest["source_sha256"]
(ROOT / manifest["source_file"]).write_bytes(raw)
print(manifest["source_sha256"])
