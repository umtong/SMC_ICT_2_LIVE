from __future__ import annotations
import base64, hashlib, json, pathlib, shutil, tarfile
ROOT=pathlib.Path(__file__).resolve().parent
M=json.loads((ROOT/'BUNDLE_MANIFEST.json').read_text())
chunks=[]
for item in M['parts']:
    raw=(ROOT/item['path']).read_bytes()
    assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256']
    chunks.append(raw)
combined=b''.join(chunks)
assert hashlib.sha256(combined).hexdigest()==M['combined_base64_sha256']
archive=base64.b64decode(combined,validate=True)
assert len(archive)==M['archive_bytes'] and hashlib.sha256(archive).hexdigest()==M['archive_sha256']
out=ROOT/'reconstructed'
shutil.rmtree(out,ignore_errors=True);out.mkdir()
arc=ROOT/'bundle.tar.gz';arc.write_bytes(archive)
with tarfile.open(arc,'r:gz') as tf: tf.extractall(out,filter='data')
assert hashlib.sha256((out/'MANIFEST.json').read_bytes()).hexdigest()==M['content_manifest_sha256']
inner=json.loads((out/'MANIFEST.json').read_text())
for item in inner['files']:
    raw=(out/item['path']).read_bytes()
    assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256']
print(len(inner['files']),M['archive_sha256'])
