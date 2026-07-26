from __future__ import annotations
import base64, gzip, hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run.py.gz.b64"
OUTPUT = ROOT / "run.py"
EXPECTED = {
    "base64_sha256": "a28b18a5bd40cc868aaf17a795a3ec83511a3dd0b0101535a02e5a39735fb1d9",
    "gzip_sha256": "1635a1b1f4f03505a594bd564dc16dee91a0eb05a40ca38ce2acccb69545e4e0",
    "raw_sha256": "470ae3ba24f33e1cb9cace531afcd03bc0553b7abd46b97b70d1e84f85a3c6c6",
}

def main() -> int:
    text = SOURCE.read_text(encoding="ascii").strip()
    if hashlib.sha256(text.encode()).hexdigest() != EXPECTED["base64_sha256"]:
        raise RuntimeError("base64 source hash mismatch")
    compressed = base64.b64decode(text, validate=True)
    if hashlib.sha256(compressed).hexdigest() != EXPECTED["gzip_sha256"]:
        raise RuntimeError("gzip source hash mismatch")
    raw = gzip.decompress(compressed)
    if hashlib.sha256(raw).hexdigest() != EXPECTED["raw_sha256"]:
        raise RuntimeError("raw runner hash mismatch")
    OUTPUT.write_bytes(raw)
    print(json.dumps({"output": str(OUTPUT), **EXPECTED}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
