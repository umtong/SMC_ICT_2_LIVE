from __future__ import annotations

import base64
import hashlib
import json
import lzma
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "source_bundle"
OUTPUT = ROOT / "implementation"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    text = "".join(
        (BUNDLE / name).read_text(encoding="utf-8").strip()
        for name in manifest["parts"]
    )
    if len(text) != int(manifest["base64_characters"]):
        raise AssertionError("base64 length mismatch")
    if sha256(text.encode("ascii")) != manifest["base64_sha256"]:
        raise AssertionError("base64 hash mismatch")
    compressed = base64.b64decode(text, validate=True)
    if len(compressed) != int(manifest["compressed_bytes"]):
        raise AssertionError("compressed size mismatch")
    if sha256(compressed) != manifest["compressed_sha256"]:
        raise AssertionError("compressed hash mismatch")
    source = lzma.decompress(compressed)
    if len(source) != int(manifest["source_bytes"]):
        raise AssertionError("source size mismatch")
    if sha256(source) != manifest["source_sha256"]:
        raise AssertionError("source hash mismatch")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "__init__.py").write_text(
        '"""Causal flow-impact efficiency research."""\n', encoding="utf-8"
    )
    (OUTPUT / "run.py").write_bytes(source)
    print(
        json.dumps(
            {
                "implementation": str(OUTPUT / "run.py"),
                "sha256": sha256(source),
                "bytes": len(source),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
