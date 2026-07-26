from pathlib import Path
import base64
import hashlib
import io
import json
import shutil
import tarfile

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "EVIDENCE_BUNDLE_MANIFEST.json").read_text())
parts = []
for index in range(MANIFEST["part_count"]):
    name = f"evidence.part{index:02d}.b64"
    path = ROOT / name
    raw = path.read_bytes()
    expected = MANIFEST["parts"][name]
    assert len(raw) == expected["bytes"]
    assert hashlib.sha256(raw).hexdigest() == expected["sha256"]
    parts.append(raw)
encoded = b"".join(parts)
assert len(encoded) == MANIFEST["base64_chars"]
assert hashlib.sha256(encoded).hexdigest() == MANIFEST["base64_sha256"]
archive = base64.b64decode(encoded, validate=True)
assert len(archive) == MANIFEST["archive_bytes"]
assert hashlib.sha256(archive).hexdigest() == MANIFEST["archive_sha256"]
out = ROOT / "reconstructed"
shutil.rmtree(out, ignore_errors=True)
out.mkdir()
with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as handle:
    handle.extractall(out, filter="data")
print(out, MANIFEST["archive_sha256"])
