#!/usr/bin/env python3
"""Load immutable evaluator inputs; run unpack_source.py for plain-source review."""
import base64 as _b64
import hashlib as _hash
import json as _json
import zlib as _zlib
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parent

def _decode(parts, manifest):
    encoded="".join(p.read_text(encoding="ascii").strip() for p in parts)
    data=_zlib.decompress(_b64.b64decode(encoded))
    expected=_json.loads(manifest.read_text(encoding="utf-8"))["sha256"]
    actual=_hash.sha256(data).hexdigest()
    if actual!=expected:
        raise RuntimeError(f"content hash mismatch: {actual}")
    return data

_EVENTS=_decode(sorted((_ROOT/"_events").glob("*.b64")),_ROOT/"events_manifest.json")
(_ROOT/"events.csv").write_bytes(_EVENTS)
_SOURCE=_decode(sorted((_ROOT/"_source").glob("part_*.b64")),_ROOT/"source_manifest.json")
exec(compile(_SOURCE.decode("utf-8"),str(_ROOT/"run_impl.py"),"exec"),globals(),globals())
