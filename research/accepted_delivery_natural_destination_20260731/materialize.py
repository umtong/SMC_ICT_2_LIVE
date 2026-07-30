from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / "SOURCE_MANIFEST.json").read_text())
spec = manifest["source_bundle"]
bundle = root / spec["file"]
raw = bundle.read_bytes()
assert len(raw) == spec["bytes"]
assert hashlib.sha256(raw).hexdigest() == spec["sha256"]

with tarfile.open(bundle, "r:gz") as tf:
    members = tf.getmembers()
    assert all(Path(m.name).name == m.name and not m.isdir() for m in members)
    tf.extractall(root, filter="data")

for name, file_spec in spec["files"].items():
    path = root / name
    data = path.read_bytes()
    assert len(data) == file_spec["bytes"], name
    assert hashlib.sha256(data).hexdigest() == file_spec["sha256"], name

print(root)
