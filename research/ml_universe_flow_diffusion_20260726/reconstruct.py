from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = {
    "run.py": {
        "parts": ["run.py.gz.b64.part00", "run.py.gz.b64.part01"],
        "gzip_sha256": "1e9cb1d249ea87c83a241e6822458ff175ffed57b7b49178a705116a83092603",
        "sha256": "dfa359a0547c3312535be92aa9d43b7e4ae49a403ff1d4804e43d73a5111cefa",
    },
    "test_run.py": {
        "parts": ["test_run.py.gz.b64.part00"],
        "gzip_sha256": "28782b6b42b3aea9903ce799de62378cf7165c2d2db986c43f3bb33cb9a3d817",
        "sha256": "e610ccec4b64b73d3a4609dde0bd04a1be4e0e2704c1a0e75c8d41dc02b216ce",
    },
}


def main() -> None:
    for output_name, spec in FILES.items():
        encoded = "".join((ROOT / part).read_text().strip() for part in spec["parts"])
        compressed = base64.b64decode(encoded, validate=True)
        if hashlib.sha256(compressed).hexdigest() != spec["gzip_sha256"]:
            raise RuntimeError(f"gzip digest mismatch: {output_name}")
        raw = gzip.decompress(compressed)
        if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
            raise RuntimeError(f"source digest mismatch: {output_name}")
        (ROOT / output_name).write_bytes(raw)
        print(f"RECONSTRUCTED {output_name} {len(raw)} bytes")


if __name__ == "__main__":
    main()
