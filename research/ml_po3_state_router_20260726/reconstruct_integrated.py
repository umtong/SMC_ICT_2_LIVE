from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = [
    "run_integrated.py.gz.b64.part00",
    "run_integrated.py.gz.b64.part010",
    "run_integrated.py.gz.b64.part011",
    "run_integrated.py.gz.b64.part02",
]
PART_SHA256 = [
    "ceb4812977684e90fbc38698a6545e9974f4a532b5e05b4dfdb72b4df3a134f8",
    "9687b1e561006d89ae71b92628c016b584e2bdf464b41b566a54968888463756",
    "c451b0c7fda667e71bb9e53f3cd898fde536039ee604e47198400811c98ad9f4",
    "6f43924c7b29615f93ee8c21bec4c75d2ba79adea3a5ec3b8cca8ade2a58be9c",
]
GZIP_SHA256 = "18472f54d3655df6380af50ba674f5a09de680b6ceb3ea97fec5ddc28b74ae7d"
RAW_SHA256 = "26c9d2f349f9af0d52cd8056cd1fc0c694b357f01f5e19af44ff6daad37e027c"

encoded = []
for name, expected in zip(PARTS, PART_SHA256):
    data = (ROOT / name).read_bytes()
    observed = hashlib.sha256(data).hexdigest()
    assert observed == expected, (name, observed, expected)
    encoded.append(data.decode("ascii").strip())
compressed = base64.b64decode("".join(encoded), validate=True)
assert hashlib.sha256(compressed).hexdigest() == GZIP_SHA256
raw = gzip.decompress(compressed)
assert hashlib.sha256(raw).hexdigest() == RAW_SHA256
output = ROOT / "reconstructed" / "run.py"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(raw)
print(RAW_SHA256)
