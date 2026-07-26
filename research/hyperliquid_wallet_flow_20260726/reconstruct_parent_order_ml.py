from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "parent_order_ml_source_manifest.json"
SOURCE = ROOT / "run_parent_order_ml.py.gz"
TARGET = ROOT / "run_parent_order_ml.py"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    compressed = SOURCE.read_bytes()
    if len(compressed) != int(manifest["gzip_bytes"]) or sha256(compressed) != manifest["gzip_sha256"]:
        raise RuntimeError("gzip source identity mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != int(manifest["raw_bytes"]) or sha256(raw) != manifest["raw_sha256"]:
        raise RuntimeError("raw source identity mismatch")
    compile(raw, str(TARGET), "exec")
    TARGET.write_bytes(raw)
    print(f"RECONSTRUCTED {TARGET} bytes={len(raw)} sha256={sha256(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
