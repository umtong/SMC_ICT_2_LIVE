from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run_screen.py.gz.b64"
TARGET = ROOT / "run_screen.py"
DIAGNOSTICS = ROOT / "RECONSTRUCTED_SOURCE.json"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    # GitHub's contents transport may wrap the base64 text. The base64 wrapper
    # itself is not a scientific dependency. Normalize whitespace, require a
    # valid base64 stream and gzip CRC, then compile and self-test the exact
    # reconstructed source in the workflow. Its actual immutable hash is
    # persisted for result provenance.
    transport = b"".join(SOURCE.read_bytes().split())
    compressed = base64.b64decode(transport, validate=True)
    raw = gzip.decompress(compressed)
    diagnostics = {
        "normalized_base64_sha256": sha256(transport),
        "gzip_sha256": sha256(compressed),
        "raw_sha256": sha256(raw),
        "raw_bytes": len(raw),
    }
    TARGET.write_bytes(raw)
    DIAGNOSTICS.write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(diagnostics)
    print({"target": str(TARGET), "bytes": len(raw), "sha256": sha256(raw)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
