from __future__ import annotations
import base64,hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
M=json.loads((ROOT/"SOURCE_MANIFEST.json").read_text())
RAW=base64.b64decode((ROOT/"SOURCE_BUNDLE.tar.gz.b64").read_text().strip(),validate=True)
assert len(RAW)==M["archive_bytes"] and hashlib.sha256(RAW).hexdigest()==M["archive_sha256"]
OUT=ROOT/"materialized";OUT.mkdir(exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(RAW),mode="r:gz") as tf:
    members=tf.getmembers();assert all(x.isfile() for x in members)
    for x in members:
        target=(OUT/x.name).resolve();assert target==OUT.resolve() or OUT.resolve() in target.parents
    tf.extractall(OUT,filter="data")
assert hashlib.sha256((OUT/"run.py").read_bytes()).hexdigest()==M["source_files"]["run.py"]
print(M["archive_sha256"],M["source_files"]["run.py"])
