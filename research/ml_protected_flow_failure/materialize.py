from __future__ import annotations
import base64, hashlib, io, json, tarfile
from pathlib import Path
root=Path(__file__).resolve().parent
m=json.loads((root/"PAYLOAD_MANIFEST.json").read_text())
encoded="".join((root/p["path"]).read_text().strip() for p in m["parts"])
raw=base64.b64decode(encoded)
assert hashlib.sha256(raw).hexdigest()==m["archive_sha256"]
with tarfile.open(fileobj=io.BytesIO(raw),mode="r:gz") as tf:
    for member in tf.getmembers():
        target=(root/member.name).resolve()
        if root.resolve() not in target.parents:
            raise RuntimeError(f"unsafe path: {member.name}")
    tf.extractall(root, filter="data")
print(f"materialized {len(m['files'])} files")
