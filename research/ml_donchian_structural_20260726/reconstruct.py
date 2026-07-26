from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "SOURCE_BUNDLE_MANIFEST.json"
PARTS = sorted(ROOT.glob("source_bundle.tar.gz.b64.part*"))


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if len(PARTS) != int(manifest["part_count"]):
        raise RuntimeError(f"expected {manifest['part_count']} parts, found {len(PARTS)}")
    encoded = "".join(path.read_text(encoding="ascii").strip() for path in PARTS).encode("ascii")
    if len(encoded) != int(manifest["base64_chars"]) or sha256(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("base64 bundle identity mismatch")
    archive = base64.b64decode(encoded, validate=True)
    if len(archive) != int(manifest["archive_bytes"]) or sha256(archive) != manifest["archive_sha256"]:
        raise RuntimeError("gzip archive identity mismatch")
    raw_tar = gzip.decompress(archive)
    if len(raw_tar) != int(manifest["tar_bytes"]) or sha256(raw_tar) != manifest["tar_sha256"]:
        raise RuntimeError("tar identity mismatch")
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as handle:
        members = handle.getmembers()
        observed = {member.name for member in members}
        expected = set(manifest["members"])
        if observed != expected:
            raise RuntimeError(f"member mismatch: observed={observed}, expected={expected}")
        for member in members:
            target = (ROOT / member.name).resolve()
            if ROOT.resolve() not in target.parents:
                raise RuntimeError(f"unsafe archive path: {member.name}")
            if not member.isfile():
                raise RuntimeError(f"non-file archive member: {member.name}")
            source = handle.extractfile(member)
            if source is None:
                raise RuntimeError(f"missing archive payload: {member.name}")
            payload = source.read()
            contract = manifest["members"][member.name]
            if len(payload) != int(contract["bytes"]) or sha256(payload) != contract["sha256"]:
                raise RuntimeError(f"member identity mismatch: {member.name}")
            target.write_bytes(payload)
            print(f"reconstructed {member.name} {len(payload)} {sha256(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
