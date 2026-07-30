from __future__ import annotations

import base64
import gzip
import hashlib
import json
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text())
raw = base64.b64decode((ROOT / "run.py.gz.b64").read_text().strip())
try:
    source = gzip.decompress(raw)
except gzip.BadGzipFile:
    # The transported gzip footer is damaged, but the raw DEFLATE member is
    # independently recoverable. Fail closed unless this is the simple
    # no-extra-field gzip form and the recovered scientific source matches
    # the preregistered implementation SHA exactly.
    assert raw[:3] == b"\x1f\x8b\x08" and raw[3] == 0
    source = zlib.decompress(raw[10:-8], -zlib.MAX_WBITS)
assert hashlib.sha256(source).hexdigest() == manifest["implementation_sha256"]
out = ROOT / "materialized"
out.mkdir(exist_ok=True)
(out / "run.py").write_bytes(source)
print(out / "run.py")
