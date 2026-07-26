from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = (
    ROOT / "implementation.b64.part00",
    ROOT / "implementation.b64.part01",
    ROOT / "implementation.b64.part02",
)
EXPECTED_PARTS = {
    "implementation.b64.part00": (6000, "2cf1a1607c6f68d7b4544643e82cd332c705bb26ce447ecb7e82f353eb60046b"),
    "implementation.b64.part01": (6000, "7feb83885ec3347b5546a2e3075681c170b0e41cb3b1feb127936eaf52fa36a6"),
    "implementation.b64.part02": (576, "68409eccfe2d225f293df3697cacd6b906c15d1aa74af3a0a1b8f0ec017667f6"),
}
EXPECTED_BASE64_BYTES = 12576
EXPECTED_BASE64_SHA256 = "6c979550f2c4cc94918bc92f2291533f1f190c2c576874d82d13697c123664d3"
EXPECTED_GZIP_BYTES = 9431
EXPECTED_GZIP_SHA256 = "05f0395058fe343acf738a57bd7d5de16359d2f7425c3d5a87e01e51a15b08da"
EXPECTED_RAW_BYTES = 35092
EXPECTED_RAW_SHA256 = "5621cc6dd7366de3808298a938eaaad3802f0523f00d467344147de7a06a2420"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


encoded_parts: list[bytes] = []
for path in PARTS:
    normalized = "".join(path.read_text(encoding="utf-8").split()).encode("ascii")
    expected_bytes, expected_hash = EXPECTED_PARTS[path.name]
    if len(normalized) != expected_bytes or digest(normalized) != expected_hash:
        raise RuntimeError(f"source transport part mismatch: {path.name}")
    encoded_parts.append(normalized)
encoded = b"".join(encoded_parts)
if len(encoded) != EXPECTED_BASE64_BYTES or digest(encoded) != EXPECTED_BASE64_SHA256:
    raise RuntimeError("combined base64 source mismatch")
compressed = base64.b64decode(encoded, validate=True)
if len(compressed) != EXPECTED_GZIP_BYTES or digest(compressed) != EXPECTED_GZIP_SHA256:
    raise RuntimeError("gzip source mismatch")
raw = gzip.decompress(compressed)
if len(raw) != EXPECTED_RAW_BYTES or digest(raw) != EXPECTED_RAW_SHA256:
    raise RuntimeError("scientific source mismatch")
target = ROOT / "run.py"
target.write_bytes(raw)
print(f"reconstructed {target} sha256={digest(raw)}")
