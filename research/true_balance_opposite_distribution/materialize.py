from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPECTED_ARCHIVE_SHA256 = "334023e05b5f97d20334efb5e77f2b29450da887b0e0face7731f38e950112dd"
EXPECTED_FILES = {
    "run.py": "f44fcb38add13bbfd097eec8d12c4024bc824ff15dd70db60fc0c4f8cf00e072",
    "validate.py": "74aac2d1331c57a93fae526bf37e154faaec23f91f466f0f196490e26247d69b",
    "test_semantics.py": "f6937b2f801c92e185013f6b0aa61714c3a2a410b2f9643bcdec9b14106709b2",
    "audit_funnel.py": "e5e1d5a48ad2cb2c5cff22d171bac2aa5f02c4b495f2580d43ff7e3a9cc31587",
}

raw = base64.b64decode((ROOT / "SOURCE_BUNDLE.tar.gz.b64").read_text().strip())
assert hashlib.sha256(raw).hexdigest() == EXPECTED_ARCHIVE_SHA256
out = ROOT / "materialized"
out.mkdir(exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
    tf.extractall(out, filter="data")
for name, expected in EXPECTED_FILES.items():
    observed = hashlib.sha256((out / name).read_bytes()).hexdigest()
    assert observed == expected, (name, observed, expected)
print("PASS", EXPECTED_ARCHIVE_SHA256)
