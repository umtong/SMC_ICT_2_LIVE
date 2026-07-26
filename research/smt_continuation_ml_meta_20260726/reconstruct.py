from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "source_manifest.json"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def reconstruct(name: str, item: dict[str, object]) -> dict[str, object]:
    expected_parts = item["parts"]
    encoded_parts: list[bytes] = []
    for part in expected_parts:
        path = ROOT / str(part["name"])
        normalized = "".join(path.read_text(encoding="ascii").split()).encode("ascii")
        if len(normalized) != int(part["bytes"]) or digest(normalized) != str(part["sha256"]):
            raise RuntimeError(f"source part mismatch: {path.name}")
        encoded_parts.append(normalized)
    encoded = b"".join(encoded_parts)
    if len(encoded) != int(item["base64_bytes"]) or digest(encoded) != str(item["base64_sha256"]):
        raise RuntimeError(f"combined base64 mismatch: {name}")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != int(item["gzip_bytes"]) or digest(compressed) != str(item["gzip_sha256"]):
        raise RuntimeError(f"gzip mismatch: {name}")
    raw = gzip.decompress(compressed)
    if len(raw) != int(item["raw_bytes"]) or digest(raw) != str(item["raw_sha256"]):
        raise RuntimeError(f"raw source mismatch: {name}")
    target = ROOT / name
    target.write_bytes(raw)
    return {"path": str(target), "bytes": len(raw), "sha256": digest(raw)}


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    observed = {name: reconstruct(name, item) for name, item in sorted(manifest["files"].items())}
    (ROOT / "RECONSTRUCTION.json").write_text(
        json.dumps(observed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(observed, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
