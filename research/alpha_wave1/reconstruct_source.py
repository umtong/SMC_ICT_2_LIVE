from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "SOURCE_MANIFEST.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    chunks: list[bytes] = []
    for part in manifest["parts"]:
        path = ROOT / part["name"]
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != part["sha256"] or len(raw) != int(part["bytes"]):
            raise RuntimeError(f"source part mismatch: {path}")
        chunks.append(raw)
    source = b"".join(chunks)
    actual = hashlib.sha256(source).hexdigest()
    if actual != manifest["target_sha256"]:
        raise RuntimeError(f"reconstructed source mismatch: {actual}")
    target = ROOT / manifest["target"]
    target.write_bytes(source)
    print(f"reconstructed={target} sha256={actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
