#!/usr/bin/env python3
from pathlib import Path
import base64
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / "TRANSPORT_MANIFEST.json").read_text())
chunks = []
for part in manifest["parts"]:
    raw = (ROOT / part["name"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == part["sha256"]
    chunks.append(raw)
source = gzip.decompress(base64.b85decode(b"".join(chunks)))
assert hashlib.sha256(source).hexdigest() == manifest["decoded_sha256"]
out = ROOT / manifest["decoded_path"]
out.write_bytes(source)
print(out, len(source), manifest["decoded_sha256"])
