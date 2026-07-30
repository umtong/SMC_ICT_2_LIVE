#!/usr/bin/env python3
from __future__ import annotations
import base64,hashlib,io,json,tarfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
manifest=json.loads((HERE/'SOURCE_MANIFEST.json').read_text())
raw=base64.b64decode((HERE/'SOURCE_BUNDLE.tar.gz.b64').read_text())
if hashlib.sha256(raw).hexdigest()!=manifest['archive_sha256']:
    raise SystemExit('archive hash mismatch')
out=HERE/'materialized'
out.mkdir(exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as tf:
    tf.extractall(out)
for row in manifest['files']:
    p=out/row['path']
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:
        raise SystemExit(f"file hash mismatch: {row['path']}")
print(out)
