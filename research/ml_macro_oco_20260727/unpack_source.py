#!/usr/bin/env python3
"""Materialize exact plain evaluator source and event snapshot from committed chunks."""
import base64,hashlib,json,zlib
from pathlib import Path
root=Path(__file__).resolve().parent

def unpack(pattern,manifest,out):
    encoded="".join(p.read_text(encoding="ascii").strip() for p in sorted(root.glob(pattern)))
    data=zlib.decompress(base64.b64decode(encoded))
    expected=json.loads((root/manifest).read_text(encoding="utf-8"))["sha256"]
    actual=hashlib.sha256(data).hexdigest()
    if actual!=expected: raise SystemExit(f"content hash mismatch: {actual}")
    path=root/out; path.write_bytes(data); print(path)

unpack("_source/part_*.b64","source_manifest.json","run_impl.py")
unpack("_events/*.b64","events_manifest.json","events.csv")
