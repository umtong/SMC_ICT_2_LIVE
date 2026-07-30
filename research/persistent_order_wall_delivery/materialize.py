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
EXPECTED_PARTS = {
    "SOURCE_BUNDLE.b64.part00": (7000, "f54f15ea4afea77ab2c2e6390b6722429c3d11162ea8ed212edd5dd7ca714026"),
    "SOURCE_BUNDLE.b64.part01a": (3500, "8662a578fa60d8a12b1a7809052e95044cff9a3cc6c413d058d6785f34c139d6"),
    "SOURCE_BUNDLE.b64.part01b": (3500, "d75f0325da34d031f2dce95b0499a6ac1a3d2a5f4fe22692196410077673150a"),
    "SOURCE_BUNDLE.b64.part02": (7000, "237a73b429f4681d824b7c6db3a6dd5e2faee4bba67fb94bb10bd766d3b6add4"),
    "SOURCE_BUNDLE.b64.part03": (7000, "7ec524ab4e9300f3a775c2cfa0212eb4aab602588ab70324d9b548fb24cb3e63"),
    "SOURCE_BUNDLE.b64.part04": (4120, "2149a305e796294afaff668768399c180e47fc7c910fdf5cec6f3c25654822c5"),
}

parts = sorted(ROOT.glob("SOURCE_BUNDLE.b64.part*"))
if parts:
    observed_names = [part.name for part in parts]
    if observed_names != sorted(EXPECTED_PARTS):
        raise RuntimeError(f"carrier part set mismatch: {observed_names}")
    texts = []
    for part in parts:
        # Base64 is intentionally wrapped for reliable GitHub text transport.
        text = "".join(part.read_text().split())
        expected_len, expected_sha = EXPECTED_PARTS[part.name]
        observed_sha = hashlib.sha256(text.encode()).hexdigest()
        if len(text) != expected_len or observed_sha != expected_sha:
            raise RuntimeError(
                f"carrier part mismatch {part.name}: "
                f"{len(text)}/{observed_sha} != {expected_len}/{expected_sha}"
            )
        texts.append(text)
    encoded = "".join(texts)
else:
    encoded = "".join((ROOT / "SOURCE_BUNDLE.tar.gz.b64").read_text().split())

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
