from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = ['run.py.gz.b64.part00', 'run.py.gz.b64.part01', 'run.py.gz.b64.part02']
PART_SHA256 = ['eca9d9f7210240384b92c80a165ec72e09d6cdaed6ed9c7dc0492f41801576a5', '11ecb0b29152442c89d4fd7e9d188be3cc9d07fb79d94226f4b0ce8178d2b5ee', 'ae75676d358808e5310a7d38dbebcb6d958e0a7bd71ae846965e3d40db6fd0e4']
GZIP_SHA256 = 'dd22a5c26f77bf5fc02d0e3bdfa0cd657cfe151bbb8ce3f6c5ff5a2d6dd0fc8e'
RAW_SHA256 = '7e93fc5bb8f999c2a60a80eba3ba7f7d795964c4b7cd20ea1af89bbd8ef659fd'

encoded_parts = []
for name, expected in zip(PARTS, PART_SHA256):
    data = (ROOT / name).read_bytes()
    observed = hashlib.sha256(data).hexdigest()
    assert observed == expected, (name, observed, expected)
    encoded_parts.append(data.decode().strip())
compressed = base64.b64decode(''.join(encoded_parts), validate=True)
assert hashlib.sha256(compressed).hexdigest() == GZIP_SHA256
raw = gzip.decompress(compressed)
assert hashlib.sha256(raw).hexdigest() == RAW_SHA256
(ROOT / 'run.py').write_bytes(raw)
print(RAW_SHA256)
