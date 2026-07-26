from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "run.py.gz.b64"
OUTPUT_DIR = ROOT / "reconstructed"
OUTPUT = OUTPUT_DIR / "run.py"
EXPECTED_GZIP_SHA256 = "0eeb3a57d708d7ed7771acbaeea5cc8b42f35b67e56da796a29f006da83224e2"
EXPECTED_RUN_SHA256 = "7b6cccffe35e3253d1659ef0bba62450ba222a100252f42e771df7ba6d28405c"


def main() -> None:
    encoded = "".join(BUNDLE.read_text(encoding="ascii").split())
    compressed = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(compressed).hexdigest() != EXPECTED_GZIP_SHA256:
        raise SystemExit("compressed implementation SHA-256 mismatch")
    raw = gzip.decompress(compressed)
    if hashlib.sha256(raw).hexdigest() != EXPECTED_RUN_SHA256:
        raise SystemExit("reconstructed implementation SHA-256 mismatch")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(raw)
    print("SOURCE_RECONSTRUCTION_PASS")


if __name__ == "__main__":
    main()
