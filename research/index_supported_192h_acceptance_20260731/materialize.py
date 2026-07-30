from __future__ import annotations
import argparse,base64,gzip,hashlib,json
from pathlib import Path
ap=argparse.ArgumentParser(); ap.add_argument("--out",type=Path,required=True); args=ap.parse_args()
root=Path(__file__).resolve().parent
m=json.loads((root/"SOURCE_MANIFEST.json").read_text())
b64="".join((root/m["bundle_file"]).read_text().split())
assert len(b64)==m["base64_chars"]
gz=base64.b64decode(b64,validate=True)
assert len(gz)==m["gzip_bytes"] and hashlib.sha256(gz).hexdigest()==m["gzip_sha256"]
raw=gzip.decompress(gz)
assert len(raw)==m["source_bytes"] and hashlib.sha256(raw).hexdigest()==m["source_sha256"]
args.out.mkdir(parents=True,exist_ok=True)
p=args.out/m["source_file"]; p.write_bytes(raw)
print(json.dumps({"status":"PASS","path":str(p),"sha256":m["source_sha256"]},sort_keys=True))
