from __future__ import annotations
import base64,gzip,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def sha(x:bytes)->str:return hashlib.sha256(x).hexdigest()

def main()->int:
 m=json.loads((ROOT/"BUNDLE_MANIFEST.json").read_text())
 for name,item in m["files"].items():
  parts=[ROOT/f"{item['prefix']}{i:02d}" for i in range(item['parts'])]
  if not all(p.exists() for p in parts):raise FileNotFoundError(name)
  encoded="".join(p.read_text().strip() for p in parts).encode("ascii")
  if sha(encoded)!=item["base64_sha256"]:raise RuntimeError(f"base64 mismatch {name}")
  compressed=base64.b64decode(encoded,validate=True)
  if sha(compressed)!=item["gzip_sha256"]:raise RuntimeError(f"gzip mismatch {name}")
  raw=gzip.decompress(compressed)
  if len(raw)!=item["raw_bytes"] or sha(raw)!=item["raw_sha256"]:raise RuntimeError(f"raw mismatch {name}")
  (ROOT/name).write_bytes(raw)
  print(name,len(raw),sha(raw))
 return 0
if __name__=="__main__":raise SystemExit(main())
