from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

EXPECTED_SHA256 = "823a0d20ebf920c45d4dfbcc07892556eaaa39fb83be8f5fc0765c2254d8a186"


def main() -> int:
    directory = Path(__file__).resolve().parent
    parts = sorted(directory.glob("run_py.gz.b64.part*"))
    if not parts:
        raise FileNotFoundError("run_py.gz.b64.part* payload not found")

    encoded = "".join(part.read_text(encoding="ascii").strip() for part in parts)
    payload = gzip.decompress(base64.b64decode(encoded, validate=True))
    actual = hashlib.sha256(payload).hexdigest()
    if actual != EXPECTED_SHA256:
        raise RuntimeError(f"runner SHA-256 mismatch: expected {EXPECTED_SHA256}, got {actual}")

    output = directory / "run_pre2024_option_surface.py"
    output.write_bytes(payload)
    print(f"reconstructed {output} bytes={len(payload)} sha256={actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
