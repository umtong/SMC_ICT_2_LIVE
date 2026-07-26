from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = tuple(ROOT / f"run.py.gz.b64.part{i:02d}" for i in range(4))
TARGET = ROOT / "run.py"
EXPECTED = {
    "part_bytes": [4000, 4000, 4000, 3312],
    "part_sha256": [
        "3ca9697e7803394a5d86a98b2026f70c17c51f2090edd98aab8bef0efacf86a7",
        "8993a782dc134fcca0896319dec8619f51c86f6f4d2d2dde092567b7ffb2dfa0",
        "c3316ed75ab4cec72147a6b8909bf860461e18184a9fbcf7facf86a692b2d5d8",
        "0a85da033465c540b33645348dededa4639b5b6102830a159854b22de3a7ba36",
    ],
    "base64_bytes": 15312,
    "base64_sha256": "29a16a2d86aa117a74f9d226a1b00c53c95ccc51b6421531d1bf3b2c4ee375e4",
    "gzip_bytes": 11482,
    "gzip_sha256": "06f2e226b27a8a4c2169ae38826989532817efc5cb1b2f8099ec40f20cd0b82b",
    "raw_bytes": 41636,
    "raw_sha256": "39a5a3a6156bb43e5c650e8ecd0ac12b94bcf4e8d2af027b5f743b891220f959",
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    missing = [path.name for path in PARTS if not path.is_file()]
    if missing:
        raise SystemExit(f"missing source transport parts: {missing}")
    pieces: list[bytes] = []
    for index, path in enumerate(PARTS):
        payload = path.read_bytes().strip()
        if len(payload) != EXPECTED["part_bytes"][index]:
            raise SystemExit(f"part length mismatch: {path.name}")
        if sha256(payload) != EXPECTED["part_sha256"][index]:
            raise SystemExit(f"part hash mismatch: {path.name}")
        pieces.append(payload)
    encoded = b"".join(pieces)
    if len(encoded) != EXPECTED["base64_bytes"] or sha256(encoded) != EXPECTED["base64_sha256"]:
        raise SystemExit("combined base64 integrity failure")
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) != EXPECTED["gzip_bytes"] or sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise SystemExit("gzip transport integrity failure")
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED["raw_bytes"] or sha256(raw) != EXPECTED["raw_sha256"]:
        raise SystemExit("raw implementation integrity failure")
    TARGET.write_bytes(raw)
    print(json.dumps({"status": "PASS", "target": str(TARGET), **EXPECTED}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
