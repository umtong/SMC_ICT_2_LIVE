from pathlib import Path
import base64,hashlib,json,tarfile

root=Path(__file__).resolve().parent
m=json.loads((root/"SOURCE_MANIFEST.json").read_text())
chunks=[]
for spec in m["bundle_parts"]:
    text="".join((root/spec["file"]).read_text().split())
    assert len(text)==spec["base64_chars"]
    assert hashlib.sha256(text.encode()).hexdigest()==spec["sha256"]
    chunks.append(text)

b64="".join(chunks)
assert len(b64)==m["base64_chars"]
raw=base64.b64decode(b64)
assert len(raw)==m["tar_gzip_bytes"]
assert hashlib.sha256(raw).hexdigest()==m["tar_gzip_sha256"]

out=root/"materialized"
out.mkdir(exist_ok=True)
tmp=root/"source_bundle.tar.gz"
tmp.write_bytes(raw)
with tarfile.open(tmp,"r:gz") as tf:
    tf.extractall(out,filter="data")

for name,spec in m["files"].items():
    path=out/name
    assert path.stat().st_size==spec["bytes"]
    assert hashlib.sha256(path.read_bytes()).hexdigest()==spec["sha256"]
print(out)
