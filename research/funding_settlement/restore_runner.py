from __future__ import annotations

import hashlib
from pathlib import Path

PARTS = (
    ("runner.part01", "c81454b7ce36d31435a49b2da9bfe5b5e9c9ebf487a54572efc4c4115efd48cf"),
    ("runner.part02", "2bfb4d46fc9b2dccbda9f1494b6cee766d8d2969974951a5b54cddd03961fcea"),
    ("runner.part03", "a167340ed88827a3649e04a7be0f7087831ee693cf7ee9639f616cf4437c4c38"),
)
EXPECTED = "bb8d25c19d5c1a5f44467f2b23b4782ba552e5ae3c8dbb93dd11fa173499f7b5"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parent
    chunks: list[bytes] = []
    for name, expected in PARTS:
        data = (root / name).read_bytes()
        observed = sha256(data)
        if observed != expected:
            raise SystemExit(f"fragment hash mismatch: {name}: {observed} != {expected}")
        chunks.append(data)
    source = b"".join(chunks)
    observed = sha256(source)
    if observed != EXPECTED:
        raise SystemExit(f"runner hash mismatch: {observed} != {EXPECTED}")
    target = root / "runner.py"
    target.write_bytes(source)
    compile(source, str(target), "exec")
    print(f"restored {target} sha256={observed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
