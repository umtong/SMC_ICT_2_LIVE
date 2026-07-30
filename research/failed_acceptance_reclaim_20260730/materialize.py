from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "SOURCE_MANIFEST.json").read_text())
    parts = []
    for index, expected_chars in enumerate(manifest["part_chars"], 1):
        path = root / f"SOURCE_BUNDLE.part{index:04d}.b64"
        text = path.read_text().strip()
        if len(text) != expected_chars:
            raise ValueError(f"part length mismatch: {path.name}")
        parts.append(text)
    encoded = "".join(parts)
    if len(encoded) != manifest["base64_chars"]:
        raise ValueError("combined Base64 length mismatch")
    archive = base64.b64decode(encoded, validate=True)
    if len(archive) != manifest["archive_bytes"]:
        raise ValueError("archive byte length mismatch")
    if sha256(archive) != manifest["archive_sha256"]:
        raise ValueError("archive SHA-256 mismatch")

    raw_tar = gzip.decompress(archive)
    args.out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as tar:
        members = tar.getmembers()
        expected = sorted(item["path"] for item in manifest["files"])
        observed = sorted(member.name for member in members if member.isfile())
        if observed != expected:
            raise ValueError(f"archive member mismatch: {observed} != {expected}")
        for member in members:
            if not member.isfile():
                continue
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise ValueError("unsafe archive member")
            source = tar.extractfile(member)
            if source is None:
                raise ValueError(f"cannot read {member.name}")
            (args.out / member.name).write_bytes(source.read())

    for item in manifest["files"]:
        path = args.out / item["path"]
        data = path.read_bytes()
        if len(data) != item["bytes"] or sha256(data) != item["sha256"]:
            raise ValueError(f"extracted file mismatch: {item['path']}")
    print(json.dumps({"status": "PASS", "files": manifest["files"]}, indent=2))


if __name__ == "__main__":
    main()
