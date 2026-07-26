from __future__ import annotations
import base64,gzip,hashlib,io,json,tarfile
from pathlib import Path

def h(data:bytes)->str:return hashlib.sha256(data).hexdigest()

def main()->None:
 root=Path(__file__).resolve().parent; m=json.loads((root/"bundle_manifest.json").read_text())
 pieces=[]
 for i in range(m["part_count"]):
  name=f"source_bundle.tar.gz.b64.part{i:02d}"; payload=b"".join((root/name).read_bytes().split()); exp=m["parts"][name]
  if len(payload)!=exp["bytes"] or h(payload)!=exp["sha256"]:raise RuntimeError(f"part mismatch {name}")
  pieces.append(payload)
 encoded=b"".join(pieces)
 if h(encoded)!=m["base64_sha256"]:raise RuntimeError("base64 mismatch")
 compressed=base64.b64decode(encoded,validate=True)
 if len(compressed)!=m["gzip_bytes"] or h(compressed)!=m["gzip_sha256"]:raise RuntimeError("gzip mismatch")
 raw=gzip.decompress(compressed)
 with tarfile.open(fileobj=io.BytesIO(raw),mode="r:") as archive:
  members=archive.getmembers()
  if {x.name for x in members}!=set(m["files"]):raise RuntimeError("member mismatch")
  for member in members:
   if not member.isfile() or "/" in member.name or member.name.startswith("."):raise RuntimeError(f"unsafe member {member.name}")
   data=archive.extractfile(member).read(); exp=m["files"][member.name]
   if len(data)!=exp["bytes"] or h(data)!=exp["sha256"]:raise RuntimeError(f"source mismatch {member.name}")
   (root/member.name).write_bytes(data)
 print(json.dumps({"status":"RECONSTRUCT_PASS","files":m["files"]},sort_keys=True))

if __name__=="__main__":main()
