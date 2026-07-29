from pathlib import Path
import base64,hashlib,json,tarfile
R=Path(__file__).resolve().parent
m=json.loads((R/'BUNDLE_MANIFEST.json').read_text())
raw=base64.b64decode(''.join((R/p).read_text().strip() for p in m['base64_parts']))
assert hashlib.sha256(raw).hexdigest()==m['sha256']
a=R/m['archive'];a.write_bytes(raw)
out=R/'materialized';out.mkdir(exist_ok=True)
with tarfile.open(a,'r:gz') as t:t.extractall(out)
print(out)
