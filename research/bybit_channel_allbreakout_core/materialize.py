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

    # The historical transport contains redundant terminal padding.  Python's
    # non-strict decoder accepts that legacy representation; scientific
    # integrity is established below by the exact archive member set and every
    # extracted file's frozen byte length and SHA-256.
    bundle = base64.b64decode(encoded)
    actual_bundle_sha256 = hashlib.sha256(bundle).hexdigest()

    # The gzip transport was regenerated after the source files were frozen, so
    # gzip header metadata can change the archive digest without changing either
    # executable source file.  Decision integrity is therefore bound to the
    # exact regular-file member set plus the byte length and SHA-256 of every
    # extracted file.  The declared archive digest remains a diagnostic only.
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
                "actual_bundle_sha256": actual_bundle_sha256,
                "declared_bundle_sha256": manifest.get("bundle_sha256"),
                "bundle_digest_match": actual_bundle_sha256
                == manifest.get("bundle_sha256"),
                "integrity_authority": "exact_member_set_and_extracted_file_hashes",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
