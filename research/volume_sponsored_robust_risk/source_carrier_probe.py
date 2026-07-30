from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "volume_sponsored_channel"
OUT = Path("research_runs/volume_sponsored_robust_risk/source")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads((SRC / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    encoded = b"".join((SRC / "SOURCE_BUNDLE.tar.gz.b64").read_bytes().split())
    raw = base64.b64decode(encoded, validate=True)
    actual_archive = {"bytes": len(raw), "sha256": sha256(raw)}
    declared_archive = {
        "bytes": int(manifest["archive_bytes"]),
        "sha256": str(manifest["archive_sha256"]),
    }

    expected = {item["path"]: item for item in manifest["files"]}
    extracted: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        if names != set(expected):
            raise SystemExit(
                f"archive inventory mismatch: missing={sorted(set(expected)-names)} "
                f"extra={sorted(names-set(expected))}"
            )
        for member in members:
            pure = PurePosixPath(member.name)
            if not member.isfile() or pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
                raise SystemExit(f"unsafe archive member: {member.name}")
            handle = archive.extractfile(member)
            if handle is None:
                raise SystemExit(f"unreadable archive member: {member.name}")
            payload = handle.read()
            spec = expected[member.name]
            if len(payload) != int(spec["bytes"]):
                raise SystemExit(f"size mismatch for {member.name}")
            if sha256(payload) != str(spec["sha256"]):
                raise SystemExit(f"sha256 mismatch for {member.name}")
            extracted[member.name] = payload

    OUT.mkdir(parents=True, exist_ok=True)
    for name, payload in extracted.items():
        (OUT / name).write_bytes(payload)

    report = {
        "status": "PASS_FILE_LEVEL_EXACT_SOURCE",
        "archive_container_matches_manifest": actual_archive == declared_archive,
        "declared_archive": declared_archive,
        "actual_archive": actual_archive,
        "encoded_bytes": len(encoded),
        "files_verified": len(extracted),
        "file_sha256": {name: sha256(payload) for name, payload in sorted(extracted.items())},
        "interpretation": (
            "exact internal source recovered; archive-container mismatch is transport metadata only"
            if actual_archive != declared_archive
            else "archive and internal source both exact"
        ),
    }
    (OUT / "SOURCE_CARRIER_PROBE.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
