#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
manifest = json.loads((HERE / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
row = manifest["source_files"][0]
text = "".join((HERE / row["carrier"]).read_text(encoding="utf-8").split())
assert len(text) == row["base64_chars"]
assert hashlib.sha256(text.encode("ascii")).hexdigest() == row["base64_sha256"]
gz = base64.b64decode(text, validate=True)
assert len(gz) == row["gzip_bytes"]
assert hashlib.sha256(gz).hexdigest() == row["gzip_sha256"]
raw = gzip.decompress(gz)
assert len(raw) == row["bytes"]
assert hashlib.sha256(raw).hexdigest() == row["sha256"]
out = HERE / "materialized"
out.mkdir(exist_ok=True)
(out / row["path"]).write_bytes(raw)
print(out / row["path"])
