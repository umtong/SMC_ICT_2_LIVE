from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "run_research.py.gz.b64"
DESTINATION = HERE / "run_research.py"
EXPECTED_BASE64_SHA256 = "9a4a4c5a6c841f718f227e5e4c4adf30c8eef9230312c0c3cef0741fb2330e96"
EXPECTED_RUNNER_SHA256 = "36bb09775fc0adac9caee7fe4d7499999d7c114d13d312ecf6ca3a9da2f70a91"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    encoded = SOURCE.read_bytes()
    if sha256(encoded) != EXPECTED_BASE64_SHA256:
        raise RuntimeError("encoded runner checksum mismatch")
    decoded = gzip.decompress(base64.b64decode(encoded, validate=True))
    if sha256(decoded) != EXPECTED_RUNNER_SHA256:
        raise RuntimeError("decoded runner checksum mismatch")
    DESTINATION.write_bytes(decoded)
    print(DESTINATION)
    print(EXPECTED_RUNNER_SHA256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
