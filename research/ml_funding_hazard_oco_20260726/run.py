from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_PATH = ROOT / "run_impl.py.gz.b64"
EXPECTED_COMPRESSED_SHA256 = "24812bc759fc200e11cf2ead44a5dae34e7db955e4885fd69d86bef9b8034e30"
EXPECTED_SOURCE_SHA256 = "e5f69d90d7422ca536c22be07840686eca0668eb49513df2b16edafeafe28747"

encoded = "".join(SOURCE_PATH.read_text(encoding="utf-8").split())
compressed = base64.b64decode(encoded, validate=True)
if hashlib.sha256(compressed).hexdigest() != EXPECTED_COMPRESSED_SHA256:
    raise RuntimeError("compressed implementation SHA-256 mismatch")
source = gzip.decompress(compressed)
if hashlib.sha256(source).hexdigest() != EXPECTED_SOURCE_SHA256:
    raise RuntimeError("scientific implementation SHA-256 mismatch")
exec(compile(source, str(ROOT / "_bundled_run_impl.py"), "exec"), globals(), globals())
