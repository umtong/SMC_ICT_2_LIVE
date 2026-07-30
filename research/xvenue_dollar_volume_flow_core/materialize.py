from __future__ import annotations
import argparse, base64, hashlib, json, tarfile
from pathlib import Path

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument('--out',default='materialized')
    args=p.parse_args()
    root=Path(__file__).resolve().parent
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((root/'SOURCE_MANIFEST.json').read_text())
    b64=''.join((root/'SOURCE_BUNDLE.tar.gz.b64').read_text().split())
    assert len(b64)==manifest['base64_chars']
    assert sha256(b64.encode())==manifest['base64_sha256']
    raw=base64.b64decode(b64,validate=True)
    assert len(raw)==manifest['archive_bytes']
    assert sha256(raw)==manifest['archive_sha256']
    archive=out/'SOURCE_BUNDLE.tar.gz'
    archive.write_bytes(raw)
    with tarfile.open(archive,'r:gz') as tf:
        members=tf.getmembers()
        for m in members:
            target=(out/m.name).resolve()
            if not str(target).startswith(str(out.resolve())):
                raise ValueError('unsafe archive member')
        tf.extractall(out)
    for item in manifest['files']:
        data=(out/item['path']).read_bytes()
        assert len(data)==item['bytes']
        assert sha256(data)==item['sha256']
    print(json.dumps({'status':'PASS','out':str(out),'files':len(manifest['files'])}))

if __name__=='__main__':
    main()
