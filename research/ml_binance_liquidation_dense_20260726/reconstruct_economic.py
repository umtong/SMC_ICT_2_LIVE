from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads((ROOT / "ECONOMIC_BUNDLE_MANIFEST.json").read_text())
    for name, item in manifest["files"].items():
        parts = [ROOT / f"{item['prefix']}{index:02d}" for index in range(item["parts"])]
        if not all(path.is_file() for path in parts):
            raise FileNotFoundError(name)
        encoded = "".join(path.read_text().strip() for path in parts).encode("ascii")
        if len(encoded) != item["base64_bytes"] or sha256(encoded) != item["base64_sha256"]:
            raise RuntimeError(f"base64 mismatch: {name}")
        compressed = base64.b64decode(encoded, validate=True)
        if len(compressed) != item["gzip_bytes"] or sha256(compressed) != item["gzip_sha256"]:
            raise RuntimeError(f"gzip mismatch: {name}")
        raw = gzip.decompress(compressed)
        if len(raw) != item["raw_bytes"] or sha256(raw) != item["raw_sha256"]:
            raise RuntimeError(f"raw mismatch: {name}")
        (ROOT / name).write_bytes(raw)
        print(name, len(raw), sha256(raw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
