from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
MANIFEST=json.loads((ROOT/"implementation_manifest.json").read_text())
parts=[]
for name in sorted(MANIFEST["parts"]):
    payload="".join((ROOT/name).read_text().split())
    expected=MANIFEST["parts"][name]
    if len(payload)!=expected["bytes"] or hashlib.sha256(payload.encode()).hexdigest()!=expected["sha256"]:
        raise RuntimeError(f"source part integrity failure: {name}")
    parts.append(payload)
encoded="".join(parts)
if len(encoded)!=MANIFEST["base64_bytes"] or hashlib.sha256(encoded.encode()).hexdigest()!=MANIFEST["base64_sha256"]:
    raise RuntimeError("combined base64 integrity failure")
compressed=base64.b64decode(encoded,validate=True)
if len(compressed)!=MANIFEST["gzip_bytes"] or hashlib.sha256(compressed).hexdigest()!=MANIFEST["gzip_sha256"]:
    raise RuntimeError("gzip integrity failure")
source=gzip.decompress(compressed)
if len(source)!=MANIFEST["raw_bytes"] or hashlib.sha256(source).hexdigest()!=MANIFEST["raw_sha256"]:
    raise RuntimeError("scientific source integrity failure")
BUNDLED_IMPLEMENTATION_SHA256=MANIFEST["raw_sha256"]
exec(compile(source,str(ROOT/"_bundled_implementation.py"),"exec"),globals(),globals())
