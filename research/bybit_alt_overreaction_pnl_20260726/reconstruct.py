from __future__ import annotations

import base64
import hashlib
import json
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = tuple(ROOT / f"run.py.zlib.b64.part{i:02d}" for i in range(1, 5))
OUTPUT = ROOT / "reconstructed" / "run.py"
EXPECTED_RAW_SHA256 = "8d0dc3fcf7a7b9c05c90973aa7c68a92c0b08f4da047ea47f1244ffe801e0895"
EXPECTED_BYTES = 21408


def main() -> int:
    encoded = "".join(part.read_text(encoding="utf-8").strip() for part in PARTS)
    raw = zlib.decompress(base64.b64decode(encoded))
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != EXPECTED_BYTES:
        raise RuntimeError(f"byte length mismatch: {len(raw)} != {EXPECTED_BYTES}")
    if digest != EXPECTED_RAW_SHA256:
        raise RuntimeError(f"source sha256 mismatch: {digest} != {EXPECTED_RAW_SHA256}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(raw)
    attestation = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-1612-ALT-OVERREACTION-PNL-001",
        "source_transport_parts": [str(part.relative_to(ROOT)) for part in PARTS],
        "output": str(OUTPUT.relative_to(ROOT)),
        "bytes": len(raw),
        "sha256": digest,
    }
    (OUTPUT.parent / "reconstruction.json").write_text(
        json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(attestation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
