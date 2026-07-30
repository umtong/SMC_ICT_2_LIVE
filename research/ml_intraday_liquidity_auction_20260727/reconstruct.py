from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "bundle_manifest.json").read_text())
    encoded_parts: list[bytes] = []
    for index in range(manifest["part_count"]):
        name = f"run.py.gz.b64.part{index:02d}"
        payload = b"".join((root / name).read_bytes().split())
        expected = manifest["parts"][name]
        if len(payload) != expected["bytes"] or sha256(payload) != expected["sha256"]:
            raise RuntimeError(f"bundle part mismatch: {name}")
        encoded_parts.append(payload)
    encoded = b"".join(encoded_parts)
    if sha256(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("combined base64 mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != manifest["gzip_bytes"] or sha256(compressed) != manifest["gzip_sha256"]:
        raise RuntimeError("gzip bundle mismatch")
    source = gzip.decompress(compressed)
    if len(source) != manifest["source_bytes"] or sha256(source) != manifest["source_sha256"]:
        raise RuntimeError("source mismatch")
    (root / manifest["source_file"]).write_bytes(source)
    print(json.dumps({"status": "RECONSTRUCT_PASS", "source_sha256": sha256(source)}, sort_keys=True))


if __name__ == "__main__":
    main()
