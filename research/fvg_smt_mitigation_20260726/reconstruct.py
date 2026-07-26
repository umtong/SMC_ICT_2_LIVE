from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRANSPORT = ROOT / "transport"
TARGET = ROOT / "run_screen.py"
PARTS = (
    ("part00.b64", 4000, "50db393e2a5dc4641f5ec834e53d1a9630e1911d22db4336dc09ea19de954d99"),
    ("part01.b64", 4000, "6eba59b7a7d1e4f74e68d667b69ea77cf135dd5dec05ed50bdf7a17b7e8694cc"),
    ("part02.b64", 4000, "28da57445181b9cc47ad4c3c436964b1dac47c67cd7a4c5f09a441a63148a118"),
    ("part03.b64", 2324, "c531bc1a98cb7f6ba26a872da474268d18dca0ba9142e34e2424e8397d368241"),
)
EXPECTED_BASE64_CHARS = 14324
EXPECTED_BASE64_SHA256 = "4a0b9d0e296e3f93562b68c3fba5030ec290011b6cc1ef7a03347f527ef0440d"
EXPECTED_GZIP_BYTES = 10741
EXPECTED_GZIP_SHA256 = "b47c69a3a836c824ebb2cf56479e167c1f6465b1b0d1c0bfe47aff173f789aa1"
EXPECTED_RAW_BYTES = 44891
EXPECTED_RAW_SHA256 = "52e84a74d846c93251bbcb6b12ede9226dbb78de6cbe84b7e1efeb54a6ce738e"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    encoded_parts: list[bytes] = []
    for name, expected_chars, expected_sha in PARTS:
        payload = b"".join((TRANSPORT / name).read_bytes().split())
        if len(payload) != expected_chars or sha256(payload) != expected_sha:
            raise SystemExit(
                f"transport part mismatch {name}: chars={len(payload)} sha256={sha256(payload)}"
            )
        encoded_parts.append(payload)
    encoded = b"".join(encoded_parts)
    if len(encoded) != EXPECTED_BASE64_CHARS or sha256(encoded) != EXPECTED_BASE64_SHA256:
        raise SystemExit(
            f"combined base64 mismatch: chars={len(encoded)} sha256={sha256(encoded)}"
        )
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != EXPECTED_GZIP_BYTES or sha256(compressed) != EXPECTED_GZIP_SHA256:
        raise SystemExit(
            f"gzip mismatch: bytes={len(compressed)} sha256={sha256(compressed)}"
        )
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED_RAW_BYTES or sha256(raw) != EXPECTED_RAW_SHA256:
        raise SystemExit(
            f"raw implementation mismatch: bytes={len(raw)} sha256={sha256(raw)}"
        )
    compile(raw, str(TARGET), "exec")
    TARGET.write_bytes(raw)
    print(f"RECONSTRUCTED {TARGET} bytes={len(raw)} sha256={sha256(raw)}")


if __name__ == "__main__":
    main()
