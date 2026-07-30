from __future__ import annotations
import base64,hashlib,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
MAN=json.loads((ROOT/'SOURCE_MANIFEST.json').read_text())
data=(ROOT/'SOURCE_BUNDLE.tar.gz.b64').read_text().strip()
raw=base64.b64decode(data)
assert hashlib.sha256(raw).hexdigest()==MAN['source']['archive_sha256']
out=ROOT/'materialized_source';out.mkdir(exist_ok=True)
arc=ROOT/'source_bundle.tar.gz';arc.write_bytes(raw)
with tarfile.open(arc,'r:gz') as tf: tf.extractall(out)
for rel,meta in MAN['source']['members'].items():
 p=out/rel
 assert p.stat().st_size==meta['bytes']
 assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256']
print('source OK',out)
print('expected external evidence sha256',MAN['evidence_external']['archive_sha256'])
