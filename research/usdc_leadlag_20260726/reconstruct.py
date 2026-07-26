from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run_screen.py.gz.b64"
TARGET = ROOT / "run_screen.py"
EXPECTED = {
    "original_base64_sha256": "06a9343d5dff4f43ab221464f25810043e05cc2536924e578393ed475fbae66b",
    "original_gzip_sha256": "5c2b5e780222a58bf3cdafef4bbaf501bdec5d93182d9eb9f76ed081a800aa44",
    "raw_sha256": "36b07c34c0753a6f8c4031809a52427e77729a40ea08bcab00ccf4a3a13af87d",
    "raw_bytes": 30229,
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    # Content APIs may rewrap or recompress a transport without changing the
    # executable source. Normalize base64 whitespace and make the uncompressed
    # source identity the hard gate. Transport hashes remain diagnostic.
    encoded = b"".join(SOURCE.read_bytes().split())
    encoded_sha = sha256(encoded)
    compressed = base64.b64decode(encoded, validate=True)
    compressed_sha = sha256(compressed)
    raw = gzip.decompress(compressed)
    raw_sha = sha256(raw)
    if len(raw) != EXPECTED["raw_bytes"] or raw_sha != EXPECTED["raw_sha256"]:
        raise SystemExit(
            "reconstructed implementation checksum mismatch: "
            f"bytes={len(raw)} raw_sha256={raw_sha} "
            f"gzip_sha256={compressed_sha} encoded_sha256={encoded_sha}"
        )
    compile(raw, str(TARGET), "exec")
    TARGET.write_bytes(raw)
    print(
        "RECONSTRUCTED "
        f"{TARGET} bytes={len(raw)} raw_sha256={raw_sha} "
        f"gzip_sha256={compressed_sha} encoded_sha256={encoded_sha} "
        f"original_gzip_match={compressed_sha == EXPECTED['original_gzip_sha256']} "
        f"original_encoded_match={encoded_sha == EXPECTED['original_base64_sha256']}"
    )


if __name__ == "__main__":
    main()
