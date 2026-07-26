from __future__ import annotations
import base64,gzip,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
M=json.loads((ROOT/"source_manifest.json").read_text())
def h(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def main()->int:
    chunks=[]
    for item in M["parts"]:
        p=ROOT/item["path"];b=p.read_bytes()
        if len(b)!=item["bytes"] or h(b)!=item["sha256"]:raise RuntimeError(f"part mismatch {p}")
        chunks.append(b)
    e=b"".join(chunks)
    if h(e)!=M["base64_sha256"]:raise RuntimeError("base64 mismatch")
    z=base64.b64decode(e,validate=True)
    if len(z)!=M["gzip_bytes"] or h(z)!=M["gzip_sha256"]:raise RuntimeError("gzip mismatch")
    raw=gzip.decompress(z)
    if len(raw)!=M["raw_bytes"] or h(raw)!=M["raw_sha256"]:raise RuntimeError("raw mismatch")
    (ROOT/M["source_path"]).write_bytes(raw);print(M["raw_sha256"]);return 0
if __name__=="__main__":raise SystemExit(main())
