from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text())
raw = base64.b64decode((ROOT / "run.py.gz.b64").read_text().strip())
source = gzip.decompress(raw)
assert hashlib.sha256(source).hexdigest() == manifest["implementation_sha256"]
out = ROOT / "materialized"
out.mkdir(exist_ok=True)
(out / "run.py").write_bytes(source)
print(out / "run.py")
