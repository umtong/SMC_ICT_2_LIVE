#!/usr/bin/env python3
from pathlib import Path
import base64, gzip, hashlib, io, json, tarfile

ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / "TRANSPORT_MANIFEST.json").read_text())
encoded = "".join((ROOT / p["path"]).read_text().strip() for p in manifest["parts"])
payload = base64.b85decode(encoded.encode("ascii"))
observed = hashlib.sha256(payload).hexdigest()
expected = manifest["bundle_sha256"]
if observed != expected:
    raise SystemExit(f"bundle SHA mismatch: {observed} != {expected}")
with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as gz:
    tar_bytes = gz.read()
with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
    for member in tar.getmembers():
        target = (ROOT / "reconstructed" / member.name).resolve()
        if not str(target).startswith(str((ROOT / "reconstructed").resolve())):
            raise SystemExit("unsafe archive path")
    tar.extractall(ROOT / "reconstructed")
for item in manifest["files"]:
    path = ROOT / "reconstructed" / item["path"]
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed != item["sha256"]:
        raise SystemExit(f"file SHA mismatch: {item['path']}")
print(f"RECONSTRUCTED {len(manifest['files'])} FILES; BUNDLE SHA256={expected}")
