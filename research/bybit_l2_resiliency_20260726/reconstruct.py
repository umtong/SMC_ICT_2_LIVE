from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source_bundle.tar.gz.b64"
MANIFEST = ROOT / "bundle_manifest.json"

# The original checked-in evaluator passed synthetic tests, then the first real
# Tardis day exposed that pandas returns a Series from to_datetime here. Apply
# one deterministic implementation correction after verifying the immutable
# original source bytes and before compilation. No market rule, model, feature,
# threshold, date or execution assumption changes.
PATCH_TARGET = "run_screen.py"
PATCH_OLD = (
    b"seconds = timestamps.hour * 3600 + timestamps.minute * 60 + timestamps.second"
)
PATCH_NEW = (
    b"seconds = timestamps.dt.hour * 3600 + timestamps.dt.minute * 60 + timestamps.dt.second"
)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    encoded = b"".join(SOURCE.read_bytes().split())
    if len(encoded) != manifest["base64_bytes"] or sha256(encoded) != manifest["base64_sha256"]:
        raise SystemExit("base64 transport mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != manifest["gzip_bytes"] or sha256(compressed) != manifest["gzip_sha256"]:
        raise SystemExit("gzip transport mismatch")
    tar_bytes = gzip.decompress(compressed)
    if len(tar_bytes) != manifest["tar_bytes"] or sha256(tar_bytes) != manifest["tar_sha256"]:
        raise SystemExit("tar transport mismatch")
    expected = set(manifest["files"])
    emitted: dict[str, dict[str, object]] = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        members = archive.getmembers()
        if {member.name for member in members} != expected:
            raise SystemExit("bundle inventory mismatch")
        for member in members:
            pure = PurePosixPath(member.name)
            if not member.isfile() or pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
                raise SystemExit(f"unsafe bundle member: {member.name}")
            handle = archive.extractfile(member)
            if handle is None:
                raise SystemExit(f"missing member payload: {member.name}")
            payload = handle.read()
            spec = manifest["files"][member.name]
            if len(payload) != spec["bytes"] or sha256(payload) != spec["sha256"]:
                raise SystemExit(f"source mismatch: {member.name}")
            original_sha = sha256(payload)
            if member.name == PATCH_TARGET:
                if payload.count(PATCH_OLD) != 1 or PATCH_NEW in payload:
                    raise SystemExit("unexpected pandas timestamp patch context")
                payload = payload.replace(PATCH_OLD, PATCH_NEW, 1)
            compile(payload, str(ROOT / member.name), "exec")
            (ROOT / member.name).write_bytes(payload)
            emitted[member.name] = {
                "original_sha256": original_sha,
                "emitted_sha256": sha256(payload),
                "emitted_bytes": len(payload),
                "deterministic_patch": member.name == PATCH_TARGET,
            }
    print(json.dumps({"status": "PASS", "files": emitted}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
