from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BUNDLES = (
    (HERE / "bundle_parts", HERE / "source_bundle_manifest.json"),
    (HERE / "evidence_parts", HERE / "evidence_bundle_manifest.json"),
)


def materialize(parts_dir: Path, manifest_path: Path) -> None:
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    encoded = "".join(path.read_text(encoding="ascii") for path in sorted(parts_dir.glob("part_*")))
    archive = base64.b64decode(encoded)
    actual_archive = hashlib.sha256(archive).hexdigest()
    if actual_archive != expected["archive_sha256"]:
        raise RuntimeError(f"archive hash mismatch for {parts_dir.name}: {actual_archive}")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        members = {member.name: member for member in tf.getmembers() if member.isfile()}
        if set(members) != set(expected["files"]):
            raise RuntimeError(f"bundle member set mismatch for {parts_dir.name}")
        for name, expected_sha in expected["files"].items():
            posix = PurePosixPath(name)
            if posix.is_absolute() or ".." in posix.parts:
                raise RuntimeError(f"unsafe archive path: {name}")
            handle = tf.extractfile(members[name])
            if handle is None:
                raise RuntimeError(f"missing archive member: {name}")
            content = handle.read()
            actual = hashlib.sha256(content).hexdigest()
            if actual != expected_sha:
                raise RuntimeError(f"member hash mismatch: {name}")
            target = ROOT / Path(*posix.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            print(f"materialized {name} sha256={actual}")


def main() -> None:
    for parts_dir, manifest_path in BUNDLES:
        materialize(parts_dir, manifest_path)


if __name__ == "__main__":
    main()
