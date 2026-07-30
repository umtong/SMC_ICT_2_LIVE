from pathlib import Path
import base64,hashlib,json,tarfile
root=Path(__file__).resolve().parent
m=json.loads((root/"SOURCE_MANIFEST.json").read_text())
b64="".join((root/m["bundle_file"]).read_text().split())
assert len(b64)==m["base64_chars"]
raw=base64.b64decode(b64)
assert len(raw)==m["tar_gzip_bytes"] and hashlib.sha256(raw).hexdigest()==m["tar_gzip_sha256"]
out=root/"materialized";out.mkdir(exist_ok=True)
tmp=root/"source_bundle.tar.gz";tmp.write_bytes(raw)
with tarfile.open(tmp,"r:gz") as tf: tf.extractall(out,filter="data")
for name,s in m["files"].items():
 p=out/name;assert p.stat().st_size==s["bytes"] and hashlib.sha256(p.read_bytes()).hexdigest()==s["sha256"]
print(out)
