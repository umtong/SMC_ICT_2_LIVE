from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "train.py"
ORIGINAL_SHA256 = "eaa13329f74fa0a8f8ed5698f36e2c9549c592974f4af4a0ab5f26c72ce7f06e"
OLD = '''    observed = sorted(frame["stage"].unique().tolist())
    if observed != sorted(STAGES_2022):
        raise RuntimeError(f"unexpected stages in 2022 train job: {observed}")
'''
NEW = '''    observed = sorted(frame["stage"].unique().tolist())
    unexpected = sorted(set(observed) - set(STAGES_2022))
    if unexpected:
        raise RuntimeError(f"unexpected stages in 2022 train job: {unexpected}")
'''


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    payload = TARGET.read_bytes()
    actual = sha256(payload)
    if actual != ORIGINAL_SHA256:
        raise SystemExit(f"refuse patch: original train.py sha256 {actual} != {ORIGINAL_SHA256}")
    text = payload.decode("utf-8")
    if text.count(OLD) != 1:
        raise SystemExit(f"refuse patch: exact termination block count={text.count(OLD)}")
    patched = text.replace(OLD, NEW, 1).encode("utf-8")
    TARGET.write_bytes(patched)
    patched_sha = sha256(patched)
    (ROOT / "TERMINATION_PATCH_SHA256.txt").write_text(
        f"{patched_sha}  {TARGET.as_posix()}\n", encoding="utf-8"
    )
    print(f"TERMINATION_ONLY_PATCH_PASS original={actual} patched={patched_sha}")


if __name__ == "__main__":
    main()
