from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = {
    'run.py': {
        "parts": ['run.py.gz.b64.part00', 'run.py.gz.b64.part01'],
        "gzip_sha256": '5280e318b3aa402fd419486072f3cf1a4940db311784c1d9929d469ee9400582',
        "sha256": 'e960e30c3abdfac238925d2f2cc6720118c98054867b6ff52aab443ef75138fd',
    },
    'test_run.py': {
        "parts": ['test_run.py.gz.b64.part00'],
        "gzip_sha256": '70943e5e8374b1f364b6803f7b8e9e69b381d1c506f7abae54e458dcc3e76fa0',
        "sha256": '665d9c047a35ecc9e827fa5599d10b0fef35d6b0528a4a9ea2c8acc7b1d05924',
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
