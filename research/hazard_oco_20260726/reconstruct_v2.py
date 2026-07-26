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
    manifest = json.loads((root / "v2_bundle_manifest.json").read_text(encoding="utf-8"))
    for record in manifest["files"]:
        encoded = (root / record["encoded_path"]).read_text(encoding="utf-8").strip()
        compressed = base64.b64decode(encoded, validate=True)
        if sha256(compressed) != record["gzip_sha256"]:
            raise AssertionError(f"gzip SHA mismatch: {record['encoded_path']}")
        raw = gzip.decompress(compressed)
        if len(raw) != record["output_bytes"]:
            raise AssertionError(f"byte count mismatch: {record['output_path']}")
        if sha256(raw) != record["output_sha256"]:
            raise AssertionError(f"source SHA mismatch: {record['output_path']}")
        path = root / record["output_path"]
        path.write_bytes(raw)
        print(f"RECONSTRUCTED {path.name} {record['output_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
