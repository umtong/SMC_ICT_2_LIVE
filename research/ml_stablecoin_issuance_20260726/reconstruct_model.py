from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "MODEL_SOURCE_MANIFEST.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    encoded = b"".join(
        (ROOT / name).read_bytes().strip()
        for name in manifest["parts"]
    )
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != int(manifest["decoded_gzip_bytes"]):
        raise RuntimeError("gzip byte-count mismatch")
    if sha256(compressed) != manifest["decoded_gzip_sha256"]:
        raise RuntimeError("gzip SHA-256 mismatch")
    source = gzip.decompress(compressed)
    if len(source) != int(manifest["source_bytes"]):
        raise RuntimeError("source byte-count mismatch")
    if sha256(source) != manifest["source_sha256"]:
        raise RuntimeError("source SHA-256 mismatch")
    output = ROOT / manifest["output_path"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(source)
    print(json.dumps({
        "output": str(output),
        "bytes": len(source),
        "sha256": sha256(source),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
