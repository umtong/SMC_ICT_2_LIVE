from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "implementation_manifest.json").read_text(encoding="utf-8"))
PARTS = tuple(ROOT / name for name in sorted(MANIFEST["parts"]))
fragments: list[str] = []
for path in PARTS:
    if not path.is_file():
        raise RuntimeError(f"missing source transport part: {path.name}")
    payload = "".join(path.read_text(encoding="utf-8").split())
    expected = MANIFEST["parts"][path.name]
    if len(payload) != expected["bytes"] or hashlib.sha256(payload.encode()).hexdigest() != expected["sha256"]:
        raise RuntimeError(f"source transport part integrity failure: {path.name}")
    fragments.append(payload)
encoded = "".join(fragments)
if len(encoded) != MANIFEST["base64_bytes"] or hashlib.sha256(encoded.encode()).hexdigest() != MANIFEST["base64_sha256"]:
    raise RuntimeError("combined base64 source integrity failure")
compressed = base64.b64decode(encoded, validate=True)
if len(compressed) != MANIFEST["gzip_bytes"] or hashlib.sha256(compressed).hexdigest() != MANIFEST["gzip_sha256"]:
    raise RuntimeError("gzip source integrity failure")
source = gzip.decompress(compressed)
if len(source) != MANIFEST["raw_bytes"] or hashlib.sha256(source).hexdigest() != MANIFEST["raw_sha256"]:
    raise RuntimeError("scientific source integrity failure")
BUNDLED_IMPLEMENTATION_SHA256 = MANIFEST["raw_sha256"]
exec(compile(source, str(ROOT / "_bundled_implementation.py"), "exec"), globals(), globals())
