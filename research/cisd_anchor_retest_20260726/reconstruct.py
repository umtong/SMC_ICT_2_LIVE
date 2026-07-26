from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
PATCH_TARGET = "run_screen.py"
PATCHES = (
    (b"expected = bar_seconds * 2", b"expected = bar_seconds * 10"),
    (b"np.all(np.diff(times) == 500_000)", b"np.all(np.diff(times) == 100_000)"),
)
PATCHED_SHA256 = "64265390ba7c7348f444a804747a5fba1eaf0943c4e20742b610bfc94554a8a8"
PATCHED_BYTES = 30144


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads((ROOT / "bundle_manifest.json").read_text(encoding="utf-8"))
    encoded = b"".join((ROOT / "source_bundle.tar.gz.b64").read_bytes().split())
    if len(encoded) != manifest["base64_bytes"] or sha256(encoded) != manifest["base64_sha256"]:
        raise SystemExit("base64 mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != manifest["gzip_bytes"] or sha256(compressed) != manifest["gzip_sha256"]:
        raise SystemExit("gzip mismatch")
    tar_bytes = gzip.decompress(compressed)
    if len(tar_bytes) != manifest["tar_bytes"] or sha256(tar_bytes) != manifest["tar_sha256"]:
        raise SystemExit("tar mismatch")
    emitted: dict[str, dict[str, object]] = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        members = archive.getmembers()
        if {member.name for member in members} != set(manifest["files"]):
            raise SystemExit("inventory mismatch")
        for member in members:
            pure = PurePosixPath(member.name)
            if not member.isfile() or pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
                raise SystemExit(f"unsafe member: {member.name}")
            handle = archive.extractfile(member)
            if handle is None:
                raise SystemExit(f"missing member: {member.name}")
            payload = handle.read()
            spec = manifest["files"][member.name]
            if len(payload) != spec["bytes"] or sha256(payload) != spec["sha256"]:
                raise SystemExit(f"source mismatch: {member.name}")
            original_sha = sha256(payload)
            patched = False
            if member.name == PATCH_TARGET:
                for old, new in PATCHES:
                    if payload.count(old) != 1 or new in payload:
                        raise SystemExit(f"unexpected source-frequency patch context: {old!r}")
                    payload = payload.replace(old, new, 1)
                if len(payload) != PATCHED_BYTES or sha256(payload) != PATCHED_SHA256:
                    raise SystemExit("patched evaluator checksum mismatch")
                patched = True
            compile(payload, str(ROOT / member.name), "exec")
            (ROOT / member.name).write_bytes(payload)
            emitted[member.name] = {
                "original_sha256": original_sha,
                "emitted_sha256": sha256(payload),
                "emitted_bytes": len(payload),
                "source_frequency_patch": patched,
            }
    print(json.dumps({"status": "PASS", "files": emitted}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
