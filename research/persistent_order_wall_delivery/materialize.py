from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
B64 = ROOT / "SOURCE_BUNDLE.tar.gz.b64"
OUT = ROOT / "materialized"

raw = base64.b64decode(B64.read_text().strip(), validate=True)
tar_bytes = gzip.decompress(raw)
OUT.mkdir(parents=True, exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
    members = tar.getmembers()
    for member in members:
        target = (OUT / member.name).resolve()
        if OUT.resolve() not in target.parents:
            raise RuntimeError(f"unsafe archive path: {member.name}")
    tar.extractall(OUT)

manifest = json.loads((OUT / "BUNDLE_MANIFEST.json").read_text())
for name, meta in manifest.items():
    path = OUT / name
    data = path.read_bytes()
    observed = hashlib.sha256(data).hexdigest()
    if observed != meta["sha256"] or len(data) != int(meta["size"]):
        raise RuntimeError(
            f"bundle mismatch {name}: {observed}/{len(data)} "
            f"!= {meta['sha256']}/{meta['size']}"
        )
print(json.dumps({"materialized": sorted(manifest), "output": str(OUT)}, sort_keys=True))
