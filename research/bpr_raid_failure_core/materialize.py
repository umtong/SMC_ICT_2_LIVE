from __future__ import annotations
import argparse,base64,gzip,hashlib,json,tarfile
from pathlib import Path

ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,required=True); args=ap.parse_args()
root=Path(__file__).resolve().parent
m=json.loads((root/'SOURCE_MANIFEST.json').read_text())
b64=''.join((root/m['bundle_file']).read_text().split())
assert len(b64)==m['base64_chars']
gz=base64.b64decode(b64); assert hashlib.sha256(gz).hexdigest()==m['gzip_sha256']
raw=gzip.decompress(gz); assert len(raw)==m['tar_bytes']; assert hashlib.sha256(raw).hexdigest()==m['tar_sha256']
args.out.mkdir(parents=True,exist_ok=True)
tmp=args.out/'bundle.tar'; tmp.write_bytes(raw)
with tarfile.open(tmp,'r') as tf: tf.extractall(args.out,filter='data')
tmp.unlink()
for name,meta in m['files'].items():
    p=args.out/name; assert p.stat().st_size==meta['bytes']; assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256']
print(json.dumps({'status':'PASS','files':sorted(m['files'])},sort_keys=True))
