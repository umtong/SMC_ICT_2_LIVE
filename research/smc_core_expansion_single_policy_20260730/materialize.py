from pathlib import Path
import base64,hashlib,json,tarfile

root=Path(__file__).resolve().parent
m=json.loads((root/"SOURCE_MANIFEST.json").read_text())
chunks=[]
errors=[]
for spec in m["bundle_parts"]:
    text="".join((root/spec["file"]).read_text().split())
    observed={
        "file":spec["file"],
        "expected_chars":spec["base64_chars"],
        "observed_chars":len(text),
        "expected_sha256":spec["sha256"],
        "observed_sha256":hashlib.sha256(text.encode()).hexdigest(),
    }
    print(json.dumps(observed,sort_keys=True),flush=True)
    if observed["expected_chars"]!=observed["observed_chars"] or observed["expected_sha256"]!=observed["observed_sha256"]:
        errors.append(observed)
    chunks.append(text)
assert not errors, errors

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
