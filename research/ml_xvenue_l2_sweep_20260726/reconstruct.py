from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "source_bundle_manifest.json").read_text(encoding="utf-8"))
    encoded = "".join((root / name).read_text(encoding="utf-8").strip() for name in manifest["encoded_parts"])
    if len(encoded) != int(manifest["base64_characters"]):
        raise AssertionError("base64 character count mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if sha256(compressed) != manifest["gzip_sha256"]:
        raise AssertionError("gzip SHA mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != int(manifest["output_bytes"]):
        raise AssertionError("output byte count mismatch")
    if sha256(raw) != manifest["output_sha256"]:
        raise AssertionError("output SHA mismatch")
    output = root / manifest["output_path"]
    output.write_bytes(raw)
    print(f"RECONSTRUCTED {output.name} sha256={sha256(raw)} bytes={len(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
