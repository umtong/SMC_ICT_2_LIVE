from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPECTED_SHA256 = "9642a8927e7292e3a7f09f0b235dd2551763bd409d1e255ce86a39e501084c21"


def main() -> int:
    encoded = (ROOT / "result_bundle.zip.b64").read_text(encoding="utf-8").strip()
    payload = base64.b64decode(encoded)
    observed = hashlib.sha256(payload).hexdigest()
    if observed != EXPECTED_SHA256:
        raise ValueError((observed, EXPECTED_SHA256))
    archive = ROOT / "result_bundle.zip"
    archive.write_bytes(payload)
    destination = ROOT / "observed"
    destination.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(destination)
    print("reconstructed result", observed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
