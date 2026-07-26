from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "SOURCE_BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
PARTS = sorted(ROOT.glob("source_bundle.tar.gz.b64.part*"))


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    if len(PARTS) != int(MANIFEST["parts"]):
        raise RuntimeError(f"expected {MANIFEST['parts']} parts, found {len(PARTS)}")
    encoded = b"".join(path.read_bytes() for path in PARTS)
    if len(encoded) != int(MANIFEST["base64_chars"]) or digest(encoded) != MANIFEST["base64_sha256"]:
        raise RuntimeError("base64 bundle mismatch")
    archive = base64.b64decode(encoded, validate=True)
    if len(archive) != int(MANIFEST["bundle_bytes"]) or digest(archive) != MANIFEST["bundle_sha256"]:
        raise RuntimeError("compressed bundle mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        members = tar.getmembers()
        expected = set(MANIFEST["members"])
        observed = {member.name for member in members}
        if observed != expected:
            raise RuntimeError(f"member inventory mismatch: {observed} != {expected}")
        for member in members:
            target = (ROOT / member.name).resolve()
            if ROOT.resolve() not in target.parents:
                raise RuntimeError(f"unsafe path: {member.name}")
        tar.extractall(ROOT)
    for name, record in MANIFEST["members"].items():
        path = ROOT / name
        payload = path.read_bytes()
        if len(payload) != int(record["bytes"]) or digest(payload) != record["sha256"]:
            raise RuntimeError(f"restored member mismatch: {name}")
    print(json.dumps({"reconstructed": sorted(MANIFEST["members"]), "bundle_sha256": MANIFEST["bundle_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
