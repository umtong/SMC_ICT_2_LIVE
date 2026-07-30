from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text())
PARTS = json.loads((ROOT / "BUNDLE_PARTS.json").read_text())

encoded_parts: list[bytes] = []
for item in PARTS["parts"]:
    raw = (ROOT / item["path"]).read_bytes()
    assert len(raw) == item["bytes"]
    assert hashlib.sha256(raw).hexdigest() == item["sha256"]
    encoded_parts.append(raw)

encoded = b"".join(encoded_parts)
assert len(encoded) == PARTS["combined_base64_bytes"]
assert hashlib.sha256(encoded).hexdigest() == PARTS["combined_base64_sha256"]

archive = base64.b64decode(encoded, validate=True)
assert len(archive) == PARTS["archive_bytes"] == SOURCE["archive_bytes"]
assert hashlib.sha256(archive).hexdigest() == PARTS["archive_sha256"] == SOURCE["archive_sha256"]

out = ROOT / "materialized"
shutil.rmtree(out, ignore_errors=True)
out.mkdir()
expected = {item["path"]: item for item in SOURCE["files"]}

with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
    members = tf.getmembers()
    regular = [item for item in members if item.isfile()]
    assert len(regular) == len(expected)
    assert {item.name for item in regular} == set(expected)
    for item in members:
        target = (out / item.name).resolve()
        assert target == out.resolve() or out.resolve() in target.parents
    tf.extractall(out, filter="data")

for path_name, item in expected.items():
    raw = (out / path_name).read_bytes()
    assert len(raw) == item["bytes"]
    assert hashlib.sha256(raw).hexdigest() == item["sha256"]

print(json.dumps({
    "archive_sha256": SOURCE["archive_sha256"],
    "files": len(expected),
    "parts": len(PARTS["parts"]),
}, sort_keys=True))
