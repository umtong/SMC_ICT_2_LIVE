from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run_screen.py.gz.b64"
TARGET = ROOT / "run_screen.py"
EXPECTED_RAW_SHA256 = "3b177232914139f4ef99259989ee7a19ad8f630778c432004ea5840cd1f80213"
EXPECTED_RAW_BYTES = 49156


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    # The transport representation is not trusted. GitHub's Contents API may
    # wrap base64 text, so normalize ASCII whitespace, decode, and accept the
    # result only when the immutable raw-source length and SHA-256 both match.
    transport = b"".join(SOURCE.read_bytes().split())
    compressed = base64.b64decode(transport, validate=True)
    raw = gzip.decompress(compressed)
    diagnostics = {
        "normalized_base64_sha256": sha256(transport),
        "gzip_sha256": sha256(compressed),
        "raw_sha256": sha256(raw),
        "raw_bytes": len(raw),
    }
    print(diagnostics)
    if len(raw) != EXPECTED_RAW_BYTES or sha256(raw) != EXPECTED_RAW_SHA256:
        raise SystemExit("raw source checksum mismatch")
    TARGET.write_bytes(raw)
    print({"target": str(TARGET), "bytes": len(raw), "sha256": sha256(raw)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
