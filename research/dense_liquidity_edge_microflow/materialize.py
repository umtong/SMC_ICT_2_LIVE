from __future__ import annotations
import base64,hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
M=json.loads((ROOT/"SOURCE_BUNDLE_MANIFEST.json").read_text())
text=(ROOT/"SOURCE_BUNDLE.tar.gz.b64").read_text().strip()
assert len(text)==M["base64_chars"]
assert hashlib.sha256(text.encode()).hexdigest()==M["base64_sha256"]
raw=base64.b64decode(text)
assert len(raw)==M["archive_bytes"] and hashlib.sha256(raw).hexdigest()==M["archive_sha256"]
with tarfile.open(fileobj=io.BytesIO(raw),mode="r:gz") as tf:
    for member in tf.getmembers():
        target=(ROOT/member.name).resolve()
        if ROOT.resolve()!=target and ROOT.resolve() not in target.parents: raise RuntimeError(member.name)
    tf.extractall(ROOT,filter="data")
for x in M["files"]:
    p=ROOT/x["path"]
    assert p.stat().st_size==x["bytes"] and hashlib.sha256(p.read_bytes()).hexdigest()==x["sha256"]
print(f"materialized {len(M['files'])} files")
