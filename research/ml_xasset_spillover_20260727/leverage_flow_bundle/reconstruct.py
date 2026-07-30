#!/usr/bin/env python3
"""Reconstruct and verify the frozen leverage-flow code bundle."""
from __future__ import annotations

import base64
import hashlib
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def main() -> None:
    encoded = "".join(path.read_text(encoding="ascii").strip() for path in sorted(ROOT.glob("bundle.part*")))
    encoded_bytes = encoded.encode("ascii")
    expected = MANIFEST["archive"]
    if len(encoded_bytes) != expected["base64_bytes"]:
        raise SystemExit("base64 byte count mismatch")
    if sha256_bytes(encoded_bytes) != expected["base64_sha256"]:
        raise SystemExit("base64 SHA-256 mismatch")
    payload = base64.b64decode(encoded_bytes, validate=True)
    if len(payload) != expected["decoded_bytes"]:
        raise SystemExit("decoded byte count mismatch")
    if sha256_bytes(payload) != expected["decoded_sha256"]:
        raise SystemExit("decoded SHA-256 mismatch")

    archive_path = ROOT / expected["decoded_name"]
    archive_path.write_bytes(payload)
    output = ROOT / "reconstructed"
    output.mkdir(exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(output, filter="data")
    for name, digest in MANIFEST["files"].items():
        path = output / name
        if not path.is_file() or file_sha256(path) != digest:
            raise SystemExit(f"reconstructed file mismatch: {name}")
    print(json.dumps({"output": str(output), "verified_files": sorted(MANIFEST["files"])}, indent=2))


if __name__ == "__main__":
    main()
