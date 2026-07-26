from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "reconstructed"
MANIFEST = ROOT / "source_manifest.json"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def reconstruct(name: str, spec: dict[str, object]) -> dict[str, object]:
    bundle = ROOT / str(spec["bundle"])
    encoded = "".join(bundle.read_text(encoding="ascii").split())
    compressed = base64.b64decode(encoded, validate=True)
    raw = gzip.decompress(compressed)
    expected_bytes = int(spec["bytes"])
    expected_sha = str(spec["sha256"])
    if len(raw) != expected_bytes:
        raise ValueError(f"{name}: byte mismatch {len(raw)} != {expected_bytes}")
    observed_sha = sha256(raw)
    if observed_sha != expected_sha:
        raise ValueError(f"{name}: sha256 mismatch {observed_sha} != {expected_sha}")
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / name
    target.write_bytes(raw)
    return {
        "bundle": bundle.name,
        "path": str(target.relative_to(ROOT)),
        "bytes": len(raw),
        "sha256": observed_sha,
    }


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    observed = {
        name: reconstruct(name, spec)
        for name, spec in sorted(manifest["files"].items())
    }
    payload = {"schema_version": 1, "files": observed}
    (OUT / "reconstruction.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
