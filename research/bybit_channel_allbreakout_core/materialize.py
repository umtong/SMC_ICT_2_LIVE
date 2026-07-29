from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("materialized"))
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    manifest = json.loads((here / "SOURCE_BUNDLE_MANIFEST.json").read_text())
    bundle = base64.b64decode((here / "source_bundle.tar.gz.b64").read_text())
    if hashlib.sha256(bundle).hexdigest() != manifest["bundle_sha256"]:
        raise SystemExit("bundle sha256 mismatch")
    args.out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as archive:
        for member in archive.getmembers():
            target = (args.out / member.name).resolve()
            if args.out.resolve() not in target.parents:
                raise SystemExit(f"unsafe member: {member.name}")
        archive.extractall(args.out, filter="data")
    for item in manifest["files"]:
        path = args.out / item["path"]
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise SystemExit(f"file mismatch: {item['path']}")
    print(json.dumps({"materialized": [x["path"] for x in manifest["files"]], "bundle_sha256": manifest["bundle_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
