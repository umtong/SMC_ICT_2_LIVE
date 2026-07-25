from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run_screen.py.gz.b64"
TARGET = ROOT / "run_screen.py"
TRANSPORT = {
    "base64_sha256": "57612a3d896a2f2a93661e0cbd4f44463930453f2f4ae5009ff1439509ec735f",
    "gzip_sha256": "d2077e001df581224cb524593cc11007c24ae26139d5810b42262fe5501be0bd",
    "raw_sha256": "3f80f36fb1e6e177341733f79a6bbf5da94180da04d42a7a4f3f45de3532b95d",
    "raw_bytes": 35264,
}
PATCHED = {
    "raw_sha256": "9844142fed8460382d2baeeff1a530204fdef8e10899a483e211577dd3c1922e",
    "raw_bytes": 35265,
}
OLD = b'spec["move"]["0.5"]'
NEW = b'spec["move"]["0.50"]'


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    encoded = SOURCE.read_bytes().strip()
    if sha256(encoded) != TRANSPORT["base64_sha256"]:
        raise SystemExit("encoded transport checksum mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if sha256(compressed) != TRANSPORT["gzip_sha256"]:
        raise SystemExit("gzip checksum mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != TRANSPORT["raw_bytes"] or sha256(raw) != TRANSPORT["raw_sha256"]:
        raise SystemExit("transport raw-source checksum mismatch")
    if raw.count(OLD) != 1 or NEW in raw:
        raise SystemExit("unexpected absorption-threshold patch context")
    patched = raw.replace(OLD, NEW, 1)
    if len(patched) != PATCHED["raw_bytes"] or sha256(patched) != PATCHED["raw_sha256"]:
        raise SystemExit("patched implementation checksum mismatch")
    compile(patched, str(TARGET), "exec")
    TARGET.write_bytes(patched)
    print(
        f"RECONSTRUCTED {TARGET} bytes={len(patched)} "
        f"sha256={sha256(patched)} deterministic_patch=absorption_move_key_0.50"
    )


if __name__ == "__main__":
    main()
