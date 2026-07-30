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
    encoded = (here / "source_bundle.tar.gz.b64").read_text().strip()
    bundle = base64.b64decode(encoded, validate=True)
    actual_bundle_sha256 = hashlib.sha256(bundle).hexdigest()
    if actual_bundle_sha256 != manifest["bundle_sha256"]:
        raise SystemExit("bundle sha256 mismatch")

    expected = {item["path"]: item for item in manifest["files"]}
    args.out.mkdir(parents=True, exist_ok=True)

    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as archive:
        members = archive.getmembers()
        regular = [member for member in members if member.isfile()]
        names = [member.name for member in regular]

        if len(names) != len(set(names)):
            raise SystemExit("duplicate archive member")
        if set(names) != set(expected):
            raise SystemExit(
                "archive member-set mismatch: "
                f"expected={sorted(expected)} actual={sorted(names)}"
            )
        if any(not (member.isfile() or member.isdir()) for member in members):
            raise SystemExit("unsupported non-regular archive member")

        root = args.out.resolve()
        for member in members:
            target = (args.out / member.name).resolve()
            if target != root and root not in target.parents:
                raise SystemExit(f"unsafe member: {member.name}")
        archive.extractall(args.out, filter="data")

    for path_name, item in expected.items():
        path = args.out / path_name
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise SystemExit(f"file mismatch: {path_name}")

    print(
        json.dumps(
            {
                "materialized": sorted(expected),
                "bundle_sha256": actual_bundle_sha256,
                "integrity_authority": manifest["integrity_authority"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
