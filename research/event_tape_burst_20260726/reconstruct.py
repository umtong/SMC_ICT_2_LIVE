from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run_screen.py.gz.b64"
TARGET = ROOT / "run_screen.py"
EXPECTED = {
    "base64_sha256": "57612a3d896a2f2a93661e0cbd4f44463930453f2f4ae5009ff1439509ec735f",
    "gzip_sha256": "d2077e001df581224cb524593cc11007c24ae26139d5810b42262fe5501be0bd",
    "raw_sha256": "3f80f36fb1e6e177341733f79a6bbf5da94180da04d42a7a4f3f45de3532b95d",
    "raw_bytes": 35264,
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
