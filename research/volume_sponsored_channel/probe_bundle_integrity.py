from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
encoded = (ROOT / "SOURCE_BUNDLE.tar.gz.b64").read_text(encoding="utf-8").strip()
raw = base64.b64decode(encoded, validate=True)
result: dict[str, object] = {
    "schema_version": 1,
    "encoded_characters": len(encoded),
    "decoded_bytes": len(raw),
    "decoded_sha256": hashlib.sha256(raw).hexdigest(),
    "manifest_archive_bytes": manifest.get("archive_bytes"),
    "manifest_archive_sha256": manifest.get("archive_sha256"),
    "archive_size_match": len(raw) == int(manifest["archive_bytes"]),
    "archive_sha256_match": hashlib.sha256(raw).hexdigest()
    == str(manifest["archive_sha256"]),
    "tar_opened": False,
    "members": [],
    "file_checks": [],
}
output = ROOT / "bundle_probe_materialized"
output.mkdir(exist_ok=True)
try:
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()
        result["tar_opened"] = True
        result["members"] = [
            {
                "name": member.name,
                "size": member.size,
                "type": (
                    member.type.decode("ascii", errors="backslashreplace")
                    if isinstance(member.type, bytes)
                    else str(member.type)
                ),
            }
            for member in members
        ]
        for member in members:
            target = (output / member.name).resolve()
            if output.resolve() not in target.parents:
                raise RuntimeError(f"unsafe archive path: {member.name}")
        archive.extractall(output, filter="data")
except Exception as error:
    result["tar_error"] = repr(error)

checks = []
for item in manifest.get("files", []):
    path = output / item["path"]
    exists = path.is_file()
    observed_bytes = path.stat().st_size if exists else None
    observed_sha = hashlib.sha256(path.read_bytes()).hexdigest() if exists else None
    checks.append(
        {
            "path": item["path"],
            "exists": exists,
            "observed_bytes": observed_bytes,
            "expected_bytes": item["bytes"],
            "bytes_match": observed_bytes == item["bytes"],
            "observed_sha256": observed_sha,
            "expected_sha256": item["sha256"],
            "sha256_match": observed_sha == item["sha256"],
        }
    )
result["file_checks"] = checks
result["all_files_match"] = bool(checks) and all(
    row["exists"] and row["bytes_match"] and row["sha256_match"] for row in checks
)
(ROOT / "BUNDLE_PROBE_RESULT.json").write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(result, indent=2, sort_keys=True))
