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
    manifest = json.loads((root / "local_trigger_bundle_manifest.json").read_text(encoding="utf-8"))
    for record in manifest["files"]:
        if "encoded_parts" in record:
            encoded = "".join((root / name).read_text(encoding="utf-8").strip() for name in record["encoded_parts"])
        else:
            encoded = (root / record["encoded_path"]).read_text(encoding="utf-8").strip()
        if len(encoded) != int(record["base64_characters"]):
            raise AssertionError(f"base64 character mismatch: {record['output_path']}")
        compressed = base64.b64decode(encoded, validate=True)
        if sha256(compressed) != record["gzip_sha256"]:
            raise AssertionError(f"gzip SHA mismatch: {record['output_path']}")
        raw = gzip.decompress(compressed)
        if len(raw) != int(record["output_bytes"]):
            raise AssertionError(f"raw byte mismatch: {record['output_path']}")
        if sha256(raw) != record["output_sha256"]:
            raise AssertionError(f"raw SHA mismatch: {record['output_path']}")
        target = root / record["output_path"]
        target.write_bytes(raw)
        compile(raw, str(target), "exec")
        print(f"RECONSTRUCTED {target.name} sha256={sha256(raw)} bytes={len(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
