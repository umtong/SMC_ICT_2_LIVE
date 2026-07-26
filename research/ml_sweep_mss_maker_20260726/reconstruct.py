from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "bundle_manifest.json").read_text(encoding="utf-8"))
ENCODED_PARTS = tuple(sorted(ROOT.glob("source_bundle.tar.gz.b64.part*")))
TARGET = ROOT / "reconstructed"
ORIGINAL_RUN_SHA256 = "01eb44c9764b0dc2eb86f371b06cd303ebf4f063dec5fe8c497b61bba25ca2cf"
CORRECTED_RUN_SHA256 = "659a5a64c8acbd87a89d8f576c49d9ccfecc82191829599f971859c55306ce7c"
BOUND_REPLACEMENTS = (
    ("for k in range(start, len(trades)):", "for k in range(start, len(t_us)):") ,
    ("for k in range(fill_idx + 1, len(trades)):", "for k in range(fill_idx + 1, len(t_us)):") ,
)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def apply_bound_runtime_correction() -> dict[str, object]:
    path = TARGET / "run.py"
    original = path.read_bytes()
    if digest(original) != ORIGINAL_RUN_SHA256:
        raise SystemExit("runtime correction original hash mismatch")
    text = original.decode("utf-8")
    applied: list[dict[str, str]] = []
    for old, new in BOUND_REPLACEMENTS:
        if text.count(old) != 1:
            raise SystemExit(f"runtime correction occurrence mismatch: {old!r}")
        text = text.replace(old, new, 1)
        applied.append({"from": old, "to": new})
    corrected = text.encode("utf-8")
    if digest(corrected) != CORRECTED_RUN_SHA256:
        raise SystemExit("runtime correction final hash mismatch")
    path.write_bytes(corrected)
    return {
        "amendment": "IMPLEMENTATION_CORRECTION_001",
        "original_sha256": ORIGINAL_RUN_SHA256,
        "corrected_sha256": CORRECTED_RUN_SHA256,
        "replacements": applied,
    }


def main() -> int:
    if not ENCODED_PARTS:
        raise SystemExit("missing source transport parts")
    encoded = "".join("".join(path.read_text(encoding="utf-8").split()) for path in ENCODED_PARTS).encode()
    if len(encoded) != MANIFEST["base64_bytes"] or digest(encoded) != MANIFEST["base64_sha256"]:
        raise SystemExit("base64 transport integrity failure")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != MANIFEST["gzip_bytes"] or digest(compressed) != MANIFEST["gzip_sha256"]:
        raise SystemExit("gzip transport integrity failure")
    tar_bytes = gzip.decompress(compressed)
    if len(tar_bytes) != MANIFEST["tar_bytes"] or digest(tar_bytes) != MANIFEST["tar_sha256"]:
        raise SystemExit("tar transport integrity failure")
    TARGET.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        names = sorted(member.name for member in archive.getmembers() if member.isfile())
        if names != sorted(MANIFEST["files"]):
            raise SystemExit(f"unexpected archive files: {names}")
        for member in archive.getmembers():
            if not member.isfile():
                continue
            if Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                raise SystemExit("unsafe archive member")
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(f"cannot read {member.name}")
            payload = source.read()
            expected = MANIFEST["files"][member.name]
            if len(payload) != expected["bytes"] or digest(payload) != expected["sha256"]:
                raise SystemExit(f"file integrity failure: {member.name}")
            (TARGET / member.name).write_bytes(payload)
    correction = apply_bound_runtime_correction()
    print(json.dumps({"status": "PASS", "target": str(TARGET), "files": names, "runtime_correction": correction}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
