from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run_screen.py.gz.b64"
TARGET = ROOT / "run_screen.py"
EXPECTED = {
    "base64_sha256": "59024216d64101fe993e0a6b558136ef323da5350899c8c0b776425a14ca78eb",
    "gzip_sha256": "024c1d21b04469fc3b6b2116ede173535cd874a105041243daf3e4ba15658efb",
    "raw_sha256": "4224ee77d04f8cd648dfcc93e46d54a597c43685aa2eb99604396c5c1878b675",
    "raw_bytes": 36252,
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
