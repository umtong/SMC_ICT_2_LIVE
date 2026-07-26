from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = sorted(ROOT.glob("run.py.gz.b64.part*"))
OUT = ROOT / "run.py"
RAW_SHA256 = "af94c567aa31593aaf77644e89592e30178b7eeb18da7561ac288a514a358d3c"
GZIP_SHA256 = "5fe67a20b5f5297f60c8759bc52d0bd5bea2dcbe401f6967a9f4582902f6d96c"
PART_SHA256 = [
    "9d6d814fddf3dd420ae22dcf68ede1a01d1bc8a44b7efe180cab0f333177072a",
    "a8bc392da5e6d16e7fbb560902765617f5f817321d3ae64e398e0c5b155cda64",
    "ab5e1b4b565c14c16bf40b7155c28ee12746249a5ea8fe14673774bf2b336c9f",
    "13b803a5756bd90a70fb0328db3f800ea7487df379dbceba4315021a6ce737e1",
    "35685434af4f108adbc71b52fcf1eeca77f6027473e689655090ad51d9a33b5c",
    "78e3907553ab048d850fc56aa36186d76a77c73abc4fcbe8c5bcb6b5bfd2e56a",
    "070496c07f395c0d8f953fb21d2dc612bde9c4ad5c1fae8699f2a34677ddd37d",
    "12316248fbf13cc76351b8ee92eb608ba7e5d82396ef942ab416d85f30fdeccb",
    "15bcc36a5035e155a681715a8cba2f8358c24c14f8bd175a77fbf187e179cafc",
    "cbf6a053a29806c23b503977245689d3557f60e73c7ee73d09b4e40396d4ae2e",
    "19aa7bd5cf3d556742f63e67e6180250c54f9f68af5e8d6c528035e0548965ee",
]

assert len(PARTS) == len(PART_SHA256), (len(PARTS), len(PART_SHA256))
for path, expected in zip(PARTS, PART_SHA256, strict=True):
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    assert observed == expected, (path.name, observed, expected)

encoded = "".join(path.read_text().strip() for path in PARTS)
compressed = base64.b64decode(encoded, validate=True)
assert hashlib.sha256(compressed).hexdigest() == GZIP_SHA256
raw = gzip.decompress(compressed)
assert hashlib.sha256(raw).hexdigest() == RAW_SHA256
OUT.write_bytes(raw)
print(RAW_SHA256)
