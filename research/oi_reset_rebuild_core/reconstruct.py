#!/usr/bin/env python3
from __future__ import annotations
import argparse, base64, hashlib, io, json, tarfile
from pathlib import Path


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=Path("materialized"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "SOURCE_MANIFEST.json").read_text())
    encoded = (root / "source_bundle.tar.gz.b64").read_bytes()
    assert len(encoded) == manifest["base64_bytes"]
    assert sha(encoded) == manifest["base64_sha256"]
    archive = base64.b64decode(encoded)
    assert len(archive) == manifest["archive_bytes"]
    assert sha(archive) == manifest["archive_sha256"]
    args.destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        tf.extractall(args.destination, filter="data")
    for record in manifest["files"]:
        path = args.destination / record["path"]
        data = path.read_bytes()
        assert len(data) == record["bytes"], record["path"]
        assert sha(data) == record["sha256"], record["path"]
    print(f"verified {len(manifest['files'])} source files in {args.destination}")


if __name__ == "__main__":
    main()
