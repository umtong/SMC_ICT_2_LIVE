from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run_screen.py.gz.b64"
TARGET = ROOT / "run_screen.py"
EXPECTED = {
    "base64_sha256": "f87de47dad313dd9a4608bc5f0b0b6615426606425157fb552358a316b44d4e1",
    "gzip_sha256": "9e659f449898b96e4f5d12ab4b14a313c734eeed1dddf609c259907b98e0b09c",
    "raw_sha256": "068ab91526e08b1de6608bb93f02c3fcaddac93192e5f7ec43cd41edc55cea83",
    "raw_bytes": 48939,
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    transport = SOURCE.read_bytes()
    if sha256(transport) != EXPECTED["base64_sha256"]:
        raise SystemExit("base64 transport checksum mismatch")
    compressed = base64.b64decode(transport, validate=False)
    if sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise SystemExit("gzip checksum mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED["raw_bytes"] or sha256(raw) != EXPECTED["raw_sha256"]:
        raise SystemExit("raw source checksum mismatch")
    TARGET.write_bytes(raw)
    print({"target": str(TARGET), "bytes": len(raw), "sha256": sha256(raw)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
