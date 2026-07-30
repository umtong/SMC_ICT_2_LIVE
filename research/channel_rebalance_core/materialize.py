from __future__ import annotations
import base64,hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
M=json.loads((ROOT/"SOURCE_MANIFEST.json").read_text())
chunks=[]
for item in M["parts"]:
    raw=(ROOT/item["path"]).read_bytes()
    assert len(raw)==item["bytes"] and hashlib.sha256(raw).hexdigest()==item["sha256"]
    chunks.append(raw)
ENCODED=b"".join(chunks)
RAW=base64.b64decode(ENCODED,validate=True)
assert len(RAW)==M["archive_bytes"] and hashlib.sha256(RAW).hexdigest()==M["archive_sha256"]
OUT=ROOT/"materialized";OUT.mkdir(exist_ok=True)
expected={x["path"]:x for x in M["files"]}
with tarfile.open(fileobj=io.BytesIO(RAW),mode="r:gz") as tf:
    members=[x for x in tf.getmembers() if x.isfile()]
    assert {x.name for x in members}==set(expected) and len(members)==len(expected)
    for x in tf.getmembers():
        target=(OUT/x.name).resolve();assert target==OUT.resolve() or OUT.resolve() in target.parents
    tf.extractall(OUT,filter="data")
for path,item in expected.items():
    raw=(OUT/path).read_bytes();assert len(raw)==item["bytes"] and hashlib.sha256(raw).hexdigest()==item["sha256"]
print(M["archive_sha256"],len(expected))
