from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    manifest = json.loads((ROOT / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
    for filename, spec in manifest["files"].items():
        encoded_parts: list[bytes] = []
        for part in spec["parts"]:
            raw_part = (ROOT / part["name"]).read_bytes()
            if len(raw_part) != part["bytes"] or sha256(raw_part) != part["sha256"]:
                raise RuntimeError(f"part mismatch {part['name']}")
            encoded_parts.append(b"".join(raw_part.split()))
        encoded = b"".join(encoded_parts)
        if len(encoded) != spec["base64_bytes"] or sha256(encoded) != spec["base64_sha256"]:
            raise RuntimeError(f"base64 mismatch {filename}")
        compressed = base64.b64decode(encoded, validate=True)
        if len(compressed) != spec["gzip_bytes"] or sha256(compressed) != spec["gzip_sha256"]:
            raise RuntimeError(f"gzip mismatch {filename}")
        raw = gzip.decompress(compressed)
        if len(raw) != spec["raw_bytes"] or sha256(raw) != spec["raw_sha256"]:
            raise RuntimeError(f"source mismatch {filename}")
        (ROOT / filename).write_bytes(raw)
    print(json.dumps({"status": "RECONSTRUCT_PASS", "files": sorted(manifest["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
