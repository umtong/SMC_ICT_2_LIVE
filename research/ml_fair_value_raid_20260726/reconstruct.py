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
    "run.py.gz.b64.part04": "9e237b0712bcaa50f552bd551709a150903f3d839b8f6a6af86f7d87b5d02f32",
    "run.py.gz.b64.part05": "36c34aa321b2e7c8222f6b058f4da5a659028282ab038096036488f609ff56a7",
    "run.py.gz.b64.part06": "623e142dedf7539aed1405a8dcc84fa4f1a53c5e8565ce7b196aa92285bcda5c",
    "run.py.gz.b64.part07": "cb7042ef124f492c609c75ded3a2a738086f1d97cbe5fe3d2e3cd2ca6f230d18"
}
EXPECTED = {
    "part_count": 8,
    "base64_bytes": 16085,
    "base64_sha256": "a3ea86f2e8dff289a77ddff9b7a8934a5a7352e5bb18984d61f5b2ab107e1a64",
    "gzip_bytes": 12063,
    "gzip_sha256": "c842630e89cbc661f7e6200e7069c7e1fdc1bb17c597e2c92e6342f76fcaad51",
    "raw_bytes": 49951,
    "raw_sha256": "8cc765ecc379da4808599d95f91a5c44d3672483141d34d7781cf9c336fdc3c9"
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
