from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run.py"
ORIGINAL_SHA256 = "cfd0d7c72ebd71d0dc479341fab10fb427033535590260a9016bd85ed438bb4a"
PATCHED_SHA256 = "80d94063c427074b5c10896e659f06cf22a77acb94b9961c08587cd9f3b6905e"

OLD = '''TRAIN_DATES = ("2022-01-01", "2022-03-01", "2022-05-01")
CALIBRATION_DATES = ("2022-07-01",)
'''

NEW = '''TRAIN_DATES = ("2022-01-01", "2022-02-01", "2022-03-01", "2022-04-01", "2022-05-01", "2022-06-01")
CALIBRATION_DATES = ("2022-07-01", "2022-08-01")
'''


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    raw = SOURCE.read_bytes()
    if sha256(raw) != ORIGINAL_SHA256:
        raise RuntimeError("unexpected reconstructed source identity")
    text = raw.decode("utf-8")
    if text.count(OLD) != 1:
        raise RuntimeError("expected chronological date block not found exactly once")
    patched = text.replace(OLD, NEW, 1).encode("utf-8")
    if sha256(patched) != PATCHED_SHA256:
        raise RuntimeError("sample-amended source identity mismatch")
    compile(patched, str(SOURCE), "exec")
    SOURCE.write_bytes(patched)
    print(f"applied source-only sample amendment bytes={len(patched)} sha256={sha256(patched)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
