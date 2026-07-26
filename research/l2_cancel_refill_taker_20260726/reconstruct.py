from __future__ import annotations
import base64, gzip, hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parent
ENC = ROOT / 'run.py.gz.b64'
OUT = ROOT / 'run.py'
RAW_SHA256 = 'c400e82bc33cef7dfe46cecb1f133a103ff515be63f7222d90622d9b4311d65d'
GZIP_SHA256 = 'dc109908e535a08420a35148984f5130e9320acd22020b772b0cedf5434a9d5c'
compressed = base64.b64decode(ENC.read_text().strip(), validate=True)
assert hashlib.sha256(compressed).hexdigest() == GZIP_SHA256
raw = gzip.decompress(compressed)
assert hashlib.sha256(raw).hexdigest() == RAW_SHA256
OUT.write_bytes(raw)
print(RAW_SHA256)
