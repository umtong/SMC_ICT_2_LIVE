from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "reconstructed"
MANIFEST = json.loads((ROOT / "source_manifest.json").read_text(encoding="utf-8"))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, expected in MANIFEST["files"].items():
        prefix = expected["bundle_prefix"]
        parts = sorted(ROOT.glob(f"{prefix}.gz.b64.part*"))
        if len(parts) != expected["part_count"]:
            raise ValueError(f"part count mismatch for {name}")
        encoded = "".join(part.read_text(encoding="utf-8").strip() for part in parts)
        if hashlib.sha256(encoded.encode()).hexdigest() != expected["base64_sha256"]:
            raise ValueError(f"base64 hash mismatch for {name}")
        compressed = base64.b64decode(encoded, validate=True)
        if hashlib.sha256(compressed).hexdigest() != expected["gzip_sha256"]:
            raise ValueError(f"gzip hash mismatch for {name}")
        raw = gzip.decompress(compressed)
        if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            raise ValueError(f"raw source mismatch for {name}")
        (OUT / name).write_bytes(raw)
    print(json.dumps(MANIFEST, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
