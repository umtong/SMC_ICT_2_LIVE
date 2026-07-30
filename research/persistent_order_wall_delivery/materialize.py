from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "materialized"

parts = sorted(ROOT.glob("SOURCE_BUNDLE.b64.part*"))
if parts:
    encoded = "".join(part.read_text().strip() for part in parts)
else:
    # Compatibility fallback for an intact single-file carrier.
    encoded = (ROOT / "SOURCE_BUNDLE.tar.gz.b64").read_text().strip()

raw = base64.b64decode(encoded, validate=True)
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
print(
    json.dumps(
        {
            "carrier_parts": [part.name for part in parts],
            "carrier_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "materialized": sorted(manifest),
            "output": str(OUT),
        },
        sort_keys=True,
    )
)
