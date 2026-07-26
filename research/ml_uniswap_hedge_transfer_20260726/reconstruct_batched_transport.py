from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENCODED = ROOT / "batched_transport_bundle.tar.gz.b64"
MANIFEST = ROOT / "batched_transport_bundle_manifest.json"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    encoded = b"".join(ENCODED.read_bytes().split())
    if len(encoded) != manifest["base64_bytes"] or digest(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("batched transport base64 identity mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != manifest["gzip_bytes"] or digest(compressed) != manifest["gzip_sha256"]:
        raise RuntimeError("batched transport gzip identity mismatch")
    raw_tar = gzip.decompress(compressed)
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
        members = archive.getmembers()
        expected = set(manifest["files"])
        observed = {member.name for member in members}
        if observed != expected:
            raise RuntimeError(f"bundle members mismatch: {observed} != {expected}")
        for member in members:
            if not member.isfile() or Path(member.name).name != member.name:
                raise RuntimeError(f"unsafe bundle member: {member.name}")
            handle = archive.extractfile(member)
            if handle is None:
                raise RuntimeError(f"cannot extract {member.name}")
            payload = handle.read()
            spec = manifest["files"][member.name]
            if len(payload) != spec["bytes"] or digest(payload) != spec["sha256"]:
                raise RuntimeError(f"source identity mismatch: {member.name}")
            compile(payload, str(ROOT / member.name), "exec")
            (ROOT / member.name).write_bytes(payload)
            print(f"RECONSTRUCTED {member.name} bytes={len(payload)} sha256={digest(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
