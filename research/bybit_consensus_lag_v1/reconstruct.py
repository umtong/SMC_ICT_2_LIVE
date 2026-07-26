from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_PARTS = (
    ROOT / "run_v1c.py.gz.b64.part00",
    ROOT / "run_v1c.py.gz.b64.part01",
    ROOT / "run_v1c.py.gz.b64.part02",
    ROOT / "run_v1c.py.gz.b64.part03",
)
TARGET = ROOT / "run.py"
EXPECTED = {
    "base64_bytes": 14260,
    "base64_sha256": "48385fdde7fd9eae049798938eda49ea090d0b787e6fc68b1f891a040f90d083",
    "gzip_bytes": 10695,
    "gzip_sha256": "cb5bd752b56168c131ab62fe377412d5e7a9be738c8f2c2fe07f767e3c62d2b9",
    "raw_bytes": 38958,
    "raw_sha256": "d3ac04f629a6114247b16a69333e43c91312247dc3dcbdd120f054014e1cf29d",
}
PARTS = {
    "run_v1c.py.gz.b64.part00": (4000, "f9927adad66a35d3268a0ebd6ba6ad678327f0e3e986873a4871332600349385"),
    "run_v1c.py.gz.b64.part01": (4000, "e03fa9f3a7619ebfadcb27977559613b8c6d986972940f27346f484c034231f3"),
    "run_v1c.py.gz.b64.part02": (4000, "bf908b7fd14de3eed57680ebea249f4e9f25b76d14a496a7dfa8d79731b0e965"),
    "run_v1c.py.gz.b64.part03": (2260, "b6390f5f5905cdd80a99eada02a1fed96fc7a466c3e22df48555d5a8a2efd5b7"),
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    fragments: list[bytes] = []
    observed_parts: list[dict[str, object]] = []
    for path in SOURCE_PARTS:
        if not path.is_file():
            raise SystemExit(f"missing source transport part: {path}")
        payload = path.read_bytes().strip()
        expected_bytes, expected_hash = PARTS[path.name]
        observed = {
            "name": path.name,
            "bytes": len(payload),
            "sha256": sha256(payload),
        }
        observed_parts.append(observed)
        if len(payload) != expected_bytes or sha256(payload) != expected_hash:
            raise SystemExit(f"source transport part integrity failure: {observed}")
        fragments.append(payload)

    encoded = b"".join(fragments)
    if len(encoded) != EXPECTED["base64_bytes"] or sha256(encoded) != EXPECTED["base64_sha256"]:
        raise SystemExit("combined base64 transport integrity failure")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != EXPECTED["gzip_bytes"] or sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise SystemExit("gzip transport integrity failure")
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED["raw_bytes"] or sha256(raw) != EXPECTED["raw_sha256"]:
        raise SystemExit("raw implementation integrity failure")
    TARGET.write_bytes(raw)
    print(
        json.dumps(
            {
                "status": "PASS",
                "target": str(TARGET),
                "parts": observed_parts,
                **EXPECTED,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
