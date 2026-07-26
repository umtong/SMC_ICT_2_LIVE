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
    "implementation.b64.part00": (6000, "a203bf0de30ee6a8ab4e631aa90ce85e97482629434ab5a04f07cae66bb2226d"),
    "implementation.b64.part01": (6000, "3319a4ea2feae2eb729acdb66815687e0725502f416ac701753224ac7f19c8f3"),
    "implementation.b64.part02": (836, "1bfd1addf51668536815e48b1d17c73bbf5e65db42ed38c9a5d5a5cd0c5a0888"),
}
EXPECTED_BASE64_BYTES = 12836
EXPECTED_BASE64_SHA256 = "8263f7a7d88aae656bb0a0f34df4b14bb28b14fb570ab19b59c5e975f26461e8"
EXPECTED_GZIP_BYTES = 9626
EXPECTED_GZIP_SHA256 = "02f7d9c93cc063919573fc4bd76dc241860224e64260b85ca353680d60814e86"
EXPECTED_RAW_BYTES = 36401
EXPECTED_RAW_SHA256 = "6b37f2941ba41794b9e7d20cd6929ca2015b8bbfe7cf4c9496532d86e1af85be"


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
