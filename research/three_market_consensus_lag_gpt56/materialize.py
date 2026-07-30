from __future__ import annotations
import base64, hashlib, json, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
m=json.loads((ROOT/'SOURCE_MANIFEST.json').read_text())
parts=[]
for item in m['parts']:
    text=(ROOT/item['path']).read_text().strip()
    assert len(text)==item['chars']
    parts.append(text)
encoded=''.join(parts)
assert len(encoded)==m['base64_chars']
raw=base64.b64decode(encoded)
assert len(raw)==m['archive_bytes']
assert hashlib.sha256(raw).hexdigest()==m['archive_sha256']
out=ROOT/'materialized';out.mkdir(exist_ok=True)
arc=ROOT/'source_bundle.tar.gz';arc.write_bytes(raw)
with tarfile.open(arc,'r:gz') as tf:
    tf.extractall(out)
for item in m['files']:
    p=out/item['path']
    assert p.stat().st_size==item['bytes']
    assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
print('source OK',out)
