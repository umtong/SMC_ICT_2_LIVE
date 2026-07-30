from __future__ import annotations
import base64,hashlib,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
MAN=json.loads((ROOT/'SOURCE_MANIFEST.json').read_text())
def unpack(name,parts,out):
 data=''.join((ROOT/p).read_text().strip() for p in parts);raw=base64.b64decode(data)
 assert hashlib.sha256(raw).hexdigest()==MAN[name]['archive_sha256']
 path=ROOT/out;path.mkdir(exist_ok=True)
 arc=ROOT/(out+'.tar.gz');arc.write_bytes(raw)
 with tarfile.open(arc,'r:gz') as tf: tf.extractall(path)
 for rel,meta in MAN[name]['members'].items():
  p=path/rel;assert p.stat().st_size==meta['bytes'];assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256']
 print(name,'OK',path)
unpack('source',['SOURCE_BUNDLE.tar.gz.b64'],'materialized_source')
unpack('evidence',MAN['evidence']['parts'],'materialized_evidence')
