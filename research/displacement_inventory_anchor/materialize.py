from __future__ import annotations

import base64
import gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run.py.gz.b64"
DESTINATION = ROOT / "run.py"


def main() -> int:
    encoded = "".join(SOURCE.read_text(encoding="utf-8").split())
    DESTINATION.write_bytes(gzip.decompress(base64.b64decode(encoded)))
    print(DESTINATION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
