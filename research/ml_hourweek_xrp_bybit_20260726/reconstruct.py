from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "run.py"
MANIFEST = ROOT / "source_manifest.json"
PARTS = [ROOT / "run.py.gz.b64.part00", ROOT / "run.py.gz.b64.part01"]
CORRECTED_RAW_SHA256 = "2b56c4a1ae9a66a0a96eeb572b726d1fdab9c34f0fd862d998410980f18d5616"
OLD = '''            frame = pd.read_csv(io.BytesIO(raw), header=None, names=columns)\n            frames.append(frame)\n'''
NEW = '''            frame = pd.read_csv(io.BytesIO(raw), header=None, names=columns)\n            # Binance Vision archives are not uniform across calendar years: some CSVs\n            # include a literal header row while older files are headerless.  Detect and\n            # remove only that transport header before numeric conversion.\n            if len(frame):\n                first = str(frame.iloc[0]["open_time_ms"]).strip().lower()\n                if first in {"open_time", "open_time_ms"}:\n                    frame = frame.iloc[1:].reset_index(drop=True)\n            frames.append(frame)\n'''


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    encoded = b"".join(part.read_bytes().strip() for part in PARTS)
    if len(encoded) != manifest["base64_bytes"] or digest(encoded) != manifest["base64_sha256"]:
        raise RuntimeError("base64 source identity mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != manifest["gzip_bytes"] or digest(compressed) != manifest["gzip_sha256"]:
        raise RuntimeError("gzip source identity mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != manifest["raw_bytes"] or digest(raw) != manifest["raw_sha256"]:
        raise RuntimeError("raw source identity mismatch")

    text = raw.decode("utf-8")
    if text.count(OLD) != 1:
        raise RuntimeError("expected exactly one Binance hourly transport insertion point")
    corrected = text.replace(OLD, NEW, 1).encode("utf-8")
    if digest(corrected) != CORRECTED_RAW_SHA256:
        raise RuntimeError(f"corrected source identity mismatch: {digest(corrected)}")
    compile(corrected, str(TARGET), "exec")
    TARGET.write_bytes(corrected)
    print(
        f"RECONSTRUCTED base_bytes={len(raw)} base_sha256={digest(raw)} "
        f"executed_bytes={len(corrected)} executed_sha256={digest(corrected)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
