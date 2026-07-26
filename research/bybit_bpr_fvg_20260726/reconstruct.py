from __future__ import annotations

import base64
import gzip
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVALUATOR_SHA256 = "6a4dc5270cfd2a0240162628e302b119994c155a8918fd5832a6e4e9617fc9f1"
RESULT_ZIP_SHA256 = "82066394e77765e8130c791796888bc4ef7f17ca91d476d7c11942a1cdd98b69"


def decode_text(name: str) -> bytes:
    return base64.b64decode((ROOT / name).read_text(encoding="utf-8").strip())


def main() -> int:
    evaluator = gzip.decompress(decode_text("evaluator.py.gz.b64"))
    observed = hashlib.sha256(evaluator).hexdigest()
    if observed != EVALUATOR_SHA256:
        raise ValueError(("evaluator sha256", observed, EVALUATOR_SHA256))
    (ROOT / "evaluate.py").write_bytes(evaluator)

    result_zip = decode_text("result_bundle.zip.b64")
    observed = hashlib.sha256(result_zip).hexdigest()
    if observed != RESULT_ZIP_SHA256:
        raise ValueError(("result bundle sha256", observed, RESULT_ZIP_SHA256))
    zip_path = ROOT / "result_bundle.zip"
    zip_path.write_bytes(result_zip)
    result_dir = ROOT / "observed"
    result_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(result_dir)
    print("reconstructed evaluator and immutable result bundle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
