from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "evaluate_source_manifest.json"
ENCODED = ROOT / "evaluate_source.py.gz.b64"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    encoded = b"".join(ENCODED.read_bytes().split())
    if len(encoded) != manifest["base64_bytes"] or digest(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("base64 evaluator identity mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != manifest["gzip_bytes"] or digest(compressed) != manifest["gzip_sha256"]:
        raise RuntimeError("gzip evaluator identity mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != manifest["raw_bytes"] or digest(raw) != manifest["raw_sha256"]:
        raise RuntimeError("raw evaluator identity mismatch")
    code = compile(raw, str(ROOT / "evaluate_source.py"), "exec")
    namespace = {"__name__": "__main__", "__file__": str(ROOT / "evaluate_source.py")}
    exec(code, namespace)


if __name__ == "__main__":
    main()
