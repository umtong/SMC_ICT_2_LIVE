from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "source_bundle_manifest.json").read_text(encoding="utf-8"))
    for record in manifest["files"]:
        encoded = "".join((root / name).read_text(encoding="utf-8").strip() for name in record["encoded_parts"])
        if len(encoded) != int(record["base64_characters"]):
            raise AssertionError("base64 character count mismatch")
        compressed = base64.b64decode(encoded, validate=True)
        if len(compressed) != int(record["gzip_bytes"]) or sha256(compressed) != record["gzip_sha256"]:
            raise AssertionError("gzip identity mismatch")
        raw = gzip.decompress(compressed)
        if len(raw) != int(record["output_bytes"]) or sha256(raw) != record["output_sha256"]:
            raise AssertionError("source identity mismatch")
        target = root / record["output_path"]
        target.write_bytes(raw)
        compile(raw, str(target), "exec")
        print(f"RECONSTRUCTED {target.name} bytes={len(raw)} sha256={sha256(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
