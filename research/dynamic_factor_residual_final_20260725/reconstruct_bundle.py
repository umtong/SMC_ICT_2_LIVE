from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
import shutil
import tarfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).parent)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()

    manifest = json.loads((args.root / "BUNDLE_MANIFEST.json").read_text())
    chunks = []
    for item in manifest["parts"]:
        raw = (args.root / item["path"]).read_bytes()
        assert len(raw) == item["bytes"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        chunks.append(raw)

    combined = b"".join(chunks)
    assert len(combined) == manifest["combined_base64_bytes"]
    assert hashlib.sha256(combined).hexdigest() == manifest["combined_base64_sha256"]

    archive = base64.b64decode(combined, validate=True)
    assert len(archive) == manifest["decoded_tar_gz_bytes"]
    assert hashlib.sha256(archive).hexdigest() == manifest["decoded_tar_gz_sha256"]

    shutil.rmtree(args.output, ignore_errors=True)
    args.output.mkdir(parents=True)
    archive_path = args.output.parent / "dynamic_factor_verified.tar.gz"
    archive_path.write_bytes(archive)
    with tarfile.open(archive_path, "r:gz") as handle:
        handle.extractall(args.output, filter="data")

    inner = args.output / "MANIFEST.json"
    assert hashlib.sha256(inner.read_bytes()).hexdigest() == manifest["content_manifest_sha256"]
    inner_manifest = json.loads(inner.read_text())
    for item in inner_manifest["files"]:
        raw = (args.output / item["path"]).read_bytes()
        assert len(raw) == item["bytes"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]

    print(json.dumps({
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "verified_files": len(inner_manifest["files"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
