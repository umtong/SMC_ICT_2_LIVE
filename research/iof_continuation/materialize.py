from __future__ import annotations
import base64,hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
M=json.loads((ROOT/"SOURCE_MANIFEST.json").read_text())
RAW=base64.b64decode((ROOT/"SOURCE_BUNDLE.tar.gz.b64").read_text().strip(),validate=True)
assert len(RAW)==M["archive_bytes"]
assert hashlib.sha256(RAW).hexdigest()==M["archive_sha256"]
OUT=ROOT/"materialized";OUT.mkdir(exist_ok=True)
expected={x["path"]:x for x in M["files"]}
with tarfile.open(fileobj=io.BytesIO(RAW),mode="r:gz") as tf:
    members=[x for x in tf.getmembers() if x.isfile()]
    assert {x.name for x in members}==set(expected)
    for x in tf.getmembers():
        target=(OUT/x.name).resolve()
        assert target==OUT.resolve() or OUT.resolve() in target.parents
    tf.extractall(OUT,filter="data")
for name,item in expected.items():
    raw=(OUT/name).read_bytes()
    assert len(raw)==item["bytes"]
    assert hashlib.sha256(raw).hexdigest()==item["sha256"]
print(M["archive_sha256"],len(expected))
