#!/usr/bin/env python3
from pathlib import Path
import base64, hashlib, json, tarfile
root=Path(__file__).resolve().parent
m=json.loads((root/"SOURCE_BUNDLE_MANIFEST.json").read_text())
b64=(root/"source_bundle.tar.gz.b64").read_text().strip()
assert len(b64)==m["base64_bytes"]
assert hashlib.sha256(b64.encode()).hexdigest()==m["base64_sha256"]
raw=base64.b64decode(b64, validate=True)
assert len(raw)==m["archive_bytes"]
assert hashlib.sha256(raw).hexdigest()==m["archive_sha256"]
with tarfile.open(fileobj=__import__("io").BytesIO(raw), mode="r:gz") as tf:
    tf.extractall(root, filter="data")
for item in m["files"]:
    b=(root/item["path"]).read_bytes()
    assert len(b)==item["bytes"]
    assert hashlib.sha256(b).hexdigest()==item["sha256"]
print("verified", len(m["files"]), "files")
