from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "reconstructed"
MANIFEST = ROOT / "source_manifest.json"


def reconstruct(name: str, item: dict[str, object]) -> dict[str, object]:
    prefix = str(item.get("bundle_prefix") or name.replace(".", "_"))
    pattern = f"{prefix}.gz.b64.part*"
    parts = sorted(ROOT.glob(pattern))
    if not parts:
        raise FileNotFoundError(f"no source parts for {name}: {pattern}")
    encoded = b"".join(part.read_bytes().strip() for part in parts)
    raw = gzip.decompress(base64.b64decode(encoded, validate=True))
    target = OUT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {
        "path": str(target.relative_to(ROOT)),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "parts": [part.name for part in parts],
    }


def main() -> int:
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    observed = {name: reconstruct(name, expected[name]) for name in sorted(expected)}
    for name, item in expected.items():
        if observed[name]["bytes"] != item["bytes"]:
            raise ValueError(f"byte-size mismatch for {name}")
        if observed[name]["sha256"] != item["sha256"]:
            raise ValueError(f"sha256 mismatch for {name}")
    (OUT / "reconstruction.json").write_text(
        json.dumps({"schema_version": 1, "files": observed}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(observed, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
