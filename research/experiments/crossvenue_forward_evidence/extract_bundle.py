from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import json
import tarfile

EXPECTED_ARCHIVE_SHA256 = "ebd83c20abaf6bf3ab7c9c467e63bd1d1129db813ddad9fa2fd3fdcca5ffcaa2"


def safe_extract(archive: Path, destination: Path) -> None:
    archive = Path(archive); destination = Path(destination)
    if sha256(archive.read_bytes()).hexdigest() != EXPECTED_ARCHIVE_SHA256:
        raise ValueError("source archive SHA-256 mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"unsafe archive member: {member.name}")
        handle.extractall(destination, filter="data")
    manifest_path = destination / "FILE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for row in manifest["files"]:
        path = destination / row["path"]
        if not path.is_file():
            raise ValueError(f"missing extracted file: {row['path']}")
        if sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"file SHA-256 mismatch: {row['path']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    safe_extract(args.archive, args.destination)


if __name__ == "__main__":
    main()
