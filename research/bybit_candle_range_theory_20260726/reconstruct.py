from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPECTED_SHA256 = "0b692cfe4b84c4566602a41769365747b9986bb0eba745788c85f12964f3df6b"


def main() -> int:
    encoded = (ROOT / "evaluator.py.gz.b64").read_text(encoding="utf-8").strip()
    source = gzip.decompress(base64.b64decode(encoded))
    observed = hashlib.sha256(source).hexdigest()
    if observed != EXPECTED_SHA256:
        raise ValueError((observed, EXPECTED_SHA256))
    (ROOT / "evaluate.py").write_bytes(source)
    print("reconstructed", observed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
