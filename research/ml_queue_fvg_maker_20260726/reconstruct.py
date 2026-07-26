from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "SOURCE_TRANSPORT.json").read_text(encoding="utf-8"))
TARGET = ROOT / "reconstructed"


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parts: list[bytes] = []
    for name, expected in MANIFEST["parts"].items():
        path = ROOT / name
        payload = path.read_bytes()
        if len(payload) != expected["bytes"] or sha(payload) != expected["sha256"]:
            raise SystemExit(f"part integrity failure: {name}")
        parts.append(payload)
    encoded = b"".join(parts)
    expected = MANIFEST["base64"]
    if len(encoded) != expected["bytes"] or sha(encoded) != expected["sha256"]:
        raise SystemExit("combined base64 integrity failure")
    archive = base64.b64decode(encoded, validate=True)
    expected = MANIFEST["gzip_tar"]
    if len(archive) != expected["bytes"] or sha(archive) != expected["sha256"]:
        raise SystemExit("tar.gz integrity failure")
    TARGET.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        names = sorted(member.name for member in bundle.getmembers() if member.isfile())
        if names != sorted(MANIFEST["files"]):
            raise SystemExit(f"unexpected archive members: {names}")
        bundle.extractall(TARGET, filter="data")
    for name, expected in MANIFEST["files"].items():
        payload = (TARGET / name).read_bytes()
        if len(payload) != expected["bytes"] or sha(payload) != expected["sha256"]:
            raise SystemExit(f"reconstructed file integrity failure: {name}")
    print(json.dumps({"status": "PASS", "target": str(TARGET), "files": MANIFEST["files"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
