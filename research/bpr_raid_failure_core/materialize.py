from __future__ import annotations
import argparse,base64,gzip,hashlib,json,tarfile
from pathlib import Path

ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,required=True); args=ap.parse_args()
root=Path(__file__).resolve().parent
m=json.loads((root/'SOURCE_MANIFEST.json').read_text())
lines=(root/m['bundle_file']).read_text().splitlines()
stored=''.join(''.join(lines).split())
stored_sha=hashlib.sha256(stored.encode()).hexdigest()
assert stored_sha==m['stored_carrier_stripped_sha256'], (stored_sha,m['stored_carrier_stripped_sha256'])
repair=m.get('transport_repair')
if repair:
    idx=int(repair['line_1_based'])-1; off=int(repair['offset_0_based']); ch=str(repair['insert_character'])
    assert 0<=idx<len(lines) and 0<=off<=len(lines[idx])
    lines[idx]=lines[idx][:off]+ch+lines[idx][off:]
b64=''.join(''.join(lines).split())
gz=base64.b64decode(b64,validate=True)
observed={'base64_chars':len(b64),'gzip_bytes':len(gz),'gzip_sha256':hashlib.sha256(gz).hexdigest(),'stored_carrier_sha256':stored_sha,'transport_repair_applied':bool(repair)}
print(json.dumps({'carrier_observed':observed,'carrier_expected':{k:m[k] for k in ('base64_chars','gzip_bytes','gzip_sha256')}},sort_keys=True))
assert observed['base64_chars']==m['base64_chars'], observed
assert observed['gzip_bytes']==m['gzip_bytes'], observed
assert observed['gzip_sha256']==m['gzip_sha256'], observed
raw=gzip.decompress(gz); assert len(raw)==m['tar_bytes']; assert hashlib.sha256(raw).hexdigest()==m['tar_sha256']
args.out.mkdir(parents=True,exist_ok=True)
tmp=args.out/'bundle.tar'; tmp.write_bytes(raw)
with tarfile.open(tmp,'r') as tf: tf.extractall(args.out,filter='data')
tmp.unlink()
for name,meta in m['files'].items():
    p=args.out/name; assert p.stat().st_size==meta['bytes']; assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256']
print(json.dumps({'status':'PASS','files':sorted(m['files'])},sort_keys=True))
