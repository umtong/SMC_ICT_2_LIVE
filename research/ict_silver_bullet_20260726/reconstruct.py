from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source_bundle.tar.gz.b64"
EXPECTED_BASE64_SHA256 = "1e3ee3cc03c9546916ecc4c5e771f448df947bb56939a0538e64937a8af24484"
EXPECTED_TAR_SHA256 = "53fbf6a291564821fb03b484a811995ca1fa384a311d5958a721b67b1696ddb2"
EXPECTED_FILES = {"run.py", "test_run.py"}
EXPECTED_FILE_SHA256 = {
    "run.py": "d777114330588ab90946349157dfc20467cd108c1a81c3505c93c1d7dfecfcde",
    "test_run.py": "6d5b56b1f1af96b7ef577638104c83b9aea90fb79c8f15bc3715309cac65ea39",
}

raw = SOURCE.read_bytes()
if hashlib.sha256(raw).hexdigest() != EXPECTED_BASE64_SHA256:
    raise SystemExit("source bundle base64 SHA-256 mismatch")
payload = base64.b64decode(raw, validate=True)
if hashlib.sha256(payload).hexdigest() != EXPECTED_TAR_SHA256:
    raise SystemExit("source bundle tar SHA-256 mismatch")
with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
    members = archive.getmembers()
    names = {member.name for member in members if member.isfile()}
    if names != EXPECTED_FILES:
        raise SystemExit(f"unexpected source inventory: {sorted(names)}")
    for member in members:
        if member.name.startswith("/") or ".." in Path(member.name).parts:
            raise SystemExit(f"unsafe source path: {member.name}")
        if member.isfile():
            extracted = archive.extractfile(member)
            if extracted is None:
                raise SystemExit(f"cannot extract {member.name}")
            digest = hashlib.sha256(extracted.read()).hexdigest()
            if digest != EXPECTED_FILE_SHA256[member.name]:
                raise SystemExit(f"source file SHA-256 mismatch: {member.name}")
    archive.extractall(ROOT, filter="data")
print("reconstructed and verified ICT Silver Bullet sources")
