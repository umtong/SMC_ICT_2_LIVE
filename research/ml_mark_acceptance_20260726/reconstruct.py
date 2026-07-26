from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = {
    "run.py": {
        "pattern": "run_py.gz.b64.part*",
        "part_count": 6,
        "base64_sha256": "c4eb3ad7dfae14683e87bceee3f44e209db6d4ffea504ac12aca569938d1a629",
        "gzip_sha256": "f46b10706ee26303d3fe5be38119a859753f047caf7b1c9205a59c16fd70d927",
        "raw_sha256": "03684c32b09aadc75e7d939e6111ea1ed269b0dca4efe19e48071c16947d02d7",
        "raw_bytes": 64966,
    },
    "test_run.py": {
        "pattern": "test_py.gz.b64.part*",
        "part_count": 1,
        "base64_sha256": "9fc337f46e828345cb71f0a3a9ba55d5a1de95cc35997dbf093c72f1adea106b",
        "gzip_sha256": "7f82b2e590d1b1ca04eca772a89c16065bd1a17179b4f9b2f7ce8f9d61c65295",
        "raw_sha256": "d1ff42a6e6d469d2a94194e370213d3e37deca9fe32b28e147ca30b48f26e89e",
        "raw_bytes": 9604,
    },
}


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def reconstruct(target_name: str, contract: dict[str, object]) -> None:
    parts = sorted(ROOT.glob(str(contract["pattern"])))
    if len(parts) != int(contract["part_count"]):
        raise RuntimeError(f"{target_name}: expected {contract['part_count']} parts, found {len(parts)}")
    encoded = "".join(path.read_text(encoding="ascii").strip() for path in parts).encode("ascii")
    if digest(encoded) != contract["base64_sha256"]:
        raise RuntimeError(f"{target_name}: base64 checksum mismatch")
    compressed = base64.b64decode(encoded, validate=True)
    if digest(compressed) != contract["gzip_sha256"]:
        raise RuntimeError(f"{target_name}: gzip checksum mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != int(contract["raw_bytes"]) or digest(raw) != contract["raw_sha256"]:
        raise RuntimeError(f"{target_name}: raw source identity mismatch")
    (ROOT / target_name).write_bytes(raw)
    print(f"reconstructed {target_name} {len(raw)} {digest(raw)}")


def main() -> int:
    for name, contract in TARGETS.items():
        reconstruct(name, contract)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
