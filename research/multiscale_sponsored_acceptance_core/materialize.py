from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--out", type=Path, required=True)
a = ap.parse_args()
root = Path(__file__).resolve().parent
manifest = json.loads((root / "SOURCE_MANIFEST.json").read_text())
b64 = "".join((root / manifest["carrier_file"]).read_text().split())
assert len(b64) == manifest["base64_chars"]
assert hashlib.sha256(b64.encode()).hexdigest() == manifest["base64_sha256"]
gz = base64.b64decode(b64, validate=True)
assert len(gz) == manifest["gzip_bytes"]
assert hashlib.sha256(gz).hexdigest() == manifest["gzip_sha256"]
raw = gzip.decompress(gz)
assert len(raw) == manifest["source_bytes"]
assert hashlib.sha256(raw).hexdigest() == manifest["source_sha256"]
a.out.mkdir(parents=True, exist_ok=True)
out = a.out / manifest["source_file"]
out.write_bytes(raw)
print(out)
