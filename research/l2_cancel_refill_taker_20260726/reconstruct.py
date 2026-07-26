from __future__ import annotations
import base64, gzip, hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parent
ENC = ROOT / "run.py.gz.b64"
OUT = ROOT / "run.py"
RAW_SHA256 = "af94c567aa31593aaf77644e89592e30178b7eeb18da7561ac288a514a358d3c"
GZIP_SHA256 = "5fe67a20b5f5297f60c8759bc52d0bd5bea2dcbe401f6967a9f4582902f6d96c"
compressed = base64.b64decode(ENC.read_text().strip(), validate=True)
assert hashlib.sha256(compressed).hexdigest() == GZIP_SHA256
raw = gzip.decompress(compressed)
assert hashlib.sha256(raw).hexdigest() == RAW_SHA256
OUT.write_bytes(raw)
print(RAW_SHA256)
