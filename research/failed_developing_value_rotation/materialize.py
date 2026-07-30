from __future__ import annotations
import base64,gzip,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_text())
parts=[]
for name in manifest['carrier_parts']:
    parts.append((ROOT/name).read_text().strip())
raw=base64.b64decode(''.join(parts))
assert hashlib.sha256(raw).hexdigest()==manifest['gzip_sha256']
source=gzip.decompress(raw)
assert hashlib.sha256(source).hexdigest()==manifest['implementation_sha256']
out=ROOT/'materialized'
out.mkdir(exist_ok=True)
(out/'run.py').write_bytes(source)
print(out/'run.py')
