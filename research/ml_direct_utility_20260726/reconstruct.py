from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "source_manifest.json"
TARGET = ROOT / "run.py"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    part_records = manifest.get("source_parts", [])
    if len(part_records) != manifest.get("part_count"):
        raise RuntimeError("source part count mismatch")
    parts = [ROOT / record["name"] for record in part_records]
    if any(not path.is_file() for path in parts):
        raise RuntimeError("source transport part missing")
    encoded = b"".join(b"".join(path.read_bytes().split()) for path in parts)
    observed = {
        "base64_bytes": len(encoded),
        "base64_sha256": digest(encoded),
    }
    print("OBSERVED_BASE64 " + json.dumps(observed, sort_keys=True))
    if len(encoded) != manifest["base64_bytes"] or digest(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("combined base64 source identity mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    observed.update({
        "gzip_bytes": len(compressed),
        "gzip_sha256": digest(compressed),
    })
    print("OBSERVED_GZIP " + json.dumps(observed, sort_keys=True))
    if len(compressed) != manifest["gzip_bytes"] or digest(compressed) != manifest["gzip_sha256"]:
        raise RuntimeError("gzip source identity mismatch")
    raw = gzip.decompress(compressed)
    observed.update({
        "raw_bytes": len(raw),
        "raw_sha256": digest(raw),
    })
    print("OBSERVED_RAW " + json.dumps(observed, sort_keys=True))
    if len(raw) != manifest["raw_bytes"] or digest(raw) != manifest["raw_sha256"]:
        raise RuntimeError("raw source identity mismatch")
    compile(raw, str(TARGET), "exec")
    TARGET.write_bytes(raw)
    print(f"RECONSTRUCTED bytes={len(raw)} sha256={digest(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
