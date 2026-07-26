#!/usr/bin/env python3
from __future__ import annotations
import base64, gzip, hashlib, io, json, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'reconstructed_portfolio'
def sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def main()->int:
    manifest=json.loads((ROOT/'source_manifest.json').read_text())
    chunks=[]
    for item in manifest['parts']:
        raw=(ROOT/item['path']).read_bytes().strip()
        if len(raw)!=int(item['chars']) or sha(raw)!=item['sha256']:
            raise ValueError(f"part mismatch: {item['path']}")
        chunks.append(raw)
    encoded=b''.join(chunks)
    if len(encoded)!=int(manifest['archive']['base64_chars']):raise ValueError('base64 length mismatch')
    archive=base64.b64decode(encoded,validate=True)
    if len(archive)!=int(manifest['archive']['bytes']) or sha(archive)!=manifest['archive']['sha256']:raise ValueError('archive mismatch')
    tar_payload=gzip.decompress(archive)
    if len(tar_payload)!=int(manifest['tar']['bytes']) or sha(tar_payload)!=manifest['tar']['sha256']:raise ValueError('tar mismatch')
    OUT.mkdir(parents=True,exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tar_payload),mode='r:') as tf:
        members=tf.getmembers(); expected=set(manifest['files']); observed={m.name for m in members}
        if observed!=expected:raise ValueError(f'members mismatch: {observed} != {expected}')
        for member in members:
            if not member.isfile() or Path(member.name).name!=member.name:raise ValueError(f'unsafe member: {member.name}')
            handle=tf.extractfile(member)
            if handle is None:raise ValueError(f'cannot extract: {member.name}')
            data=handle.read()
            spec=manifest['files'][member.name]
            if len(data)!=int(spec['bytes']) or sha(data)!=spec['sha256']:raise ValueError(f'file mismatch: {member.name}')
            (OUT/member.name).write_bytes(data)
    print(json.dumps(manifest['files'],indent=2,sort_keys=True))
    return 0
if __name__=='__main__':raise SystemExit(main())
