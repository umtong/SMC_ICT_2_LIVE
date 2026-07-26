from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = tuple(sorted(ROOT.glob("run.py.gz.b64.part*")))
TARGET = ROOT / "run.py"
DIAGNOSTICS = ROOT / "RECONSTRUCTED_SOURCE.json"
EXPECTED_PARTS = {
    "run.py.gz.b64.part00": "14992337facf9b156ba483e6bfa857f35ac91efda1519a7e86e4f8aeb897fa85",
    "run.py.gz.b64.part01": "da69d2b6f00f3a5c723fa3023285b4b7ba8fd7e0880c62201f9e5fd5b64185ce",
    "run.py.gz.b64.part02": "c88ac54be1f1df99ed0607eba59ae0a2aecd8044cddcaab1c4d336ac8b7c856b",
    "run.py.gz.b64.part03": "62449652dc0ef3b84bbdf82c1e1418272351adb9009f16de2a24c2a42a086147",
    "run.py.gz.b64.part04": "82672bd7abc68272e5dd11f44e43a52a96a30aab27265f0a6ba502c5e2b3dc4c",
    "run.py.gz.b64.part05": "cfc137c47297d6c071976ea3c1d71f3c2354edecc041ad1b1c59591c5c908819",
    "run.py.gz.b64.part06": "e9c56b17bd296e9ad8328c6d99472d3392eb7512cb0f06ddcce1dad4724a2204",
    "run.py.gz.b64.part07": "eab9c03f47957f3d5c9918fd173962d3ff5dcf91d96bca2887e4b04f9b3ec8a0"
}
EXPECTED = {
    "part_count": 8,
    "base64_bytes": 16104,
    "base64_sha256": "1c1951c5577acd30b0ee41349dc26ba956365106382d0c5e6d34aa094f8d2acf",
    "gzip_bytes": 12076,
    "gzip_sha256": "9e7532bd5d3bdd3e15866f8d676afbae6f1843a91c494d313fbca634a5aff099",
    "raw_bytes": 49994,
    "raw_sha256": "3563ec0bb01b89a0051a411d62e2a353720b4ceafcb6c7d9961f81801c1a22b1"
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    if len(PARTS) != EXPECTED["part_count"]:
        raise RuntimeError(f"transport part count {len(PARTS)} != {EXPECTED['part_count']}")
    encoded_parts: list[bytes] = []
    observed_parts: dict[str, str] = {}
    for path in PARTS:
        payload = path.read_bytes()
        observed = sha256(payload)
        expected = EXPECTED_PARTS.get(path.name)
        if expected is None or observed != expected:
            raise RuntimeError(f"transport part SHA-256 mismatch: {path.name}")
        encoded_parts.append(payload)
        observed_parts[path.name] = observed
    encoded = b"".join(encoded_parts)
    if len(encoded) != EXPECTED["base64_bytes"]:
        raise RuntimeError("combined base64 transport length mismatch")
    if sha256(encoded) != EXPECTED["base64_sha256"]:
        raise RuntimeError("combined base64 transport SHA-256 mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != EXPECTED["gzip_bytes"]:
        raise RuntimeError("gzip payload length mismatch")
    if sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise RuntimeError("gzip payload SHA-256 mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED["raw_bytes"]:
        raise RuntimeError("scientific source length mismatch")
    if sha256(raw) != EXPECTED["raw_sha256"]:
        raise RuntimeError("scientific source SHA-256 mismatch")
    TARGET.write_bytes(raw)
    diagnostics = {**EXPECTED, "part_sha256": observed_parts}
    DIAGNOSTICS.write_text(json.dumps(diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(diagnostics, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
