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
CORRUPTED_PATH = "channel_volume_pre2024_risk_select.py"
CORRUPTED_OBSERVED_SHA = "3078a1393a3fc4c473a63bfe5da4a9040d9fe7752650e8869d9ec52db658357b"
CORRUPTED_EXPECTED_SHA = "d203bfb845dddbbaf54752ebd8fcdc1a19297bcfcbfe2c83a21986ba7d4948f5"


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
    exact: dict[str, bytes] = {}
    mismatches: list[dict[str, object]] = []
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
            observed_sha = sha256(payload)
            if len(payload) != int(spec["bytes"]):
                raise SystemExit(f"size mismatch for {member.name}")
            if observed_sha != str(spec["sha256"]):
                mismatches.append({
                    "path": member.name,
                    "expected_sha256": str(spec["sha256"]),
                    "observed_sha256": observed_sha,
                    "bytes": len(payload),
                })
                continue
            exact[member.name] = payload

    expected_mismatch = [{
        "path": CORRUPTED_PATH,
        "expected_sha256": CORRUPTED_EXPECTED_SHA,
        "observed_sha256": CORRUPTED_OBSERVED_SHA,
        "bytes": int(expected[CORRUPTED_PATH]["bytes"]),
    }]
    if mismatches != expected_mismatch:
        raise SystemExit(f"unexpected source mismatch set: {mismatches!r}")
    if len(exact) != 8 or CORRUPTED_PATH in exact:
        raise SystemExit("exact source count or corrupted-file exclusion mismatch")

    OUT.mkdir(parents=True, exist_ok=True)
    for name, payload in exact.items():
        (OUT / name).write_bytes(payload)
    report = {
        "status": "PASS_EIGHT_EXACT_EXECUTION_FILES_ONE_KNOWN_CORRUPTED_SELECTION_CARRIER_EXCLUDED",
        "archive_container_matches_manifest": actual_archive == declared_archive,
        "declared_archive": declared_archive,
        "actual_archive": actual_archive,
        "encoded_bytes": len(encoded),
        "exact_files_verified": len(exact),
        "excluded_mismatches": mismatches,
        "exact_file_sha256": {name: sha256(payload) for name, payload in sorted(exact.items())},
        "boundary": "The corrupted pre-2024 risk-selector file is never executed. The registered grid is reconstructed by the new selector using the exact candidate/replay/account engine.",
    }
    (OUT / "SOURCE_CARRIER_PROBE.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
