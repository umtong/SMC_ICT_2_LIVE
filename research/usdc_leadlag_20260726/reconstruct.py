from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run_screen.py.gz.b64"
TARGET = ROOT / "run_screen.py"
EXPECTED = {
    "base64_sha256": "06a9343d5dff4f43ab221464f25810043e05cc2536924e578393ed475fbae66b",
    "gzip_sha256": "5c2b5e780222a58bf3cdafef4bbaf501bdec5d93182d9eb9f76ed081a800aa44",
    "raw_sha256": "36b07c34c0753a6f8c4031809a52427e77729a40ea08bcab00ccf4a3a13af87d",
    "raw_bytes": 30229,
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    encoded = SOURCE.read_bytes().strip()
    if sha256(encoded) != EXPECTED["base64_sha256"]:
        raise SystemExit("encoded transport checksum mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise SystemExit("gzip checksum mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED["raw_bytes"] or sha256(raw) != EXPECTED["raw_sha256"]:
        raise SystemExit("reconstructed implementation checksum mismatch")
    compile(raw, str(TARGET), "exec")
    TARGET.write_bytes(raw)
    print(f"RECONSTRUCTED {TARGET} bytes={len(raw)} sha256={sha256(raw)}")


if __name__ == "__main__":
    main()
