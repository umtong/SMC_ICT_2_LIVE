from __future__ import annotations
import base64,gzip,hashlib,io,json,tarfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parent

def sha256(x:bytes)->str:return hashlib.sha256(x).hexdigest()
def main()->int:
 m=json.loads((ROOT/'bundle_manifest.json').read_text())
 enc=b''.join((ROOT/'source_bundle.tar.gz.b64').read_bytes().split())
 if len(enc)!=m['base64_bytes'] or sha256(enc)!=m['base64_sha256']:raise SystemExit('base64 mismatch')
 gz=base64.b64decode(enc,validate=True)
 if len(gz)!=m['gzip_bytes'] or sha256(gz)!=m['gzip_sha256']:raise SystemExit('gzip mismatch')
 raw=gzip.decompress(gz)
 if len(raw)!=m['tar_bytes'] or sha256(raw)!=m['tar_sha256']:raise SystemExit('tar mismatch')
 with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as ar:
  members=ar.getmembers()
  if {x.name for x in members}!=set(m['files']):raise SystemExit('inventory mismatch')
  for member in members:
   pure=PurePosixPath(member.name)
   if not member.isfile() or pure.is_absolute() or '..' in pure.parts or len(pure.parts)!=1:raise SystemExit('unsafe member')
   payload=ar.extractfile(member).read(); spec=m['files'][member.name]
   if len(payload)!=spec['bytes'] or sha256(payload)!=spec['sha256']:raise SystemExit('source mismatch')
   compile(payload,str(ROOT/member.name),'exec');(ROOT/member.name).write_bytes(payload)
 print(json.dumps({'status':'PASS','files':m['files']},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
