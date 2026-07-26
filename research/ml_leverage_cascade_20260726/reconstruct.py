from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "SOURCE_BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
parts = sorted(ROOT.glob("source_bundle.tar.gz.b64.part*"))
if len(parts) != MANIFEST["parts"]:
    raise SystemExit(f"expected {MANIFEST['parts']} source parts, found {len(parts)}")
encoded = "".join(path.read_text(encoding="utf-8").strip() for path in parts)
bundle = base64.b64decode(encoded, validate=True)
actual_bundle_sha = hashlib.sha256(bundle).hexdigest()
if actual_bundle_sha != MANIFEST["bundle_sha256"]:
    raise SystemExit(f"source bundle checksum mismatch: {actual_bundle_sha}")
with tarfile.open(fileobj=io.BytesIO(gzip.decompress(bundle)), mode="r:") as archive:
    names = archive.getnames()
    if sorted(names) != sorted(MANIFEST["members"]):
        raise SystemExit(f"unexpected source members: {names}")
    for name in names:
        member = archive.getmember(name)
        if not member.isfile() or Path(name).name != name:
            raise SystemExit(f"unsafe source member: {name}")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise SystemExit(f"cannot extract source member: {name}")
        data = extracted.read()
        expected = MANIFEST["members"][name]
        if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
            raise SystemExit(f"source member checksum mismatch: {name}")
        (ROOT / name).write_bytes(data)
print(json.dumps({"reconstructed": names, "bundle_sha256": actual_bundle_sha}, sort_keys=True))
