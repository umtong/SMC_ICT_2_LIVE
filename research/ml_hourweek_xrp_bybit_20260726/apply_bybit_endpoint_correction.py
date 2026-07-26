from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "run.py"
PREVIOUS_SHA256 = "c4aef87f1bb42fe8f196630a545a37d6a4ae3b7a1e4f8d3b4b7ada60f9826aaa"
CORRECTED_SHA256 = "74943366c11fa6317248758f29536c7fe7b47a87e6b3c97d34f4f637e3bcc9dd"
OLD = "https://api.bybit.com"
NEW = "https://api.bytick.com"
EXPECTED_COUNT = 3


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    raw = TARGET.read_bytes()
    current = digest(raw)
    if current == CORRECTED_SHA256:
        print(f"BYBIT_ENDPOINT_CORRECTION_ALREADY_APPLIED sha256={current}")
        return 0
    if current != PREVIOUS_SHA256:
        raise RuntimeError(f"unexpected pre-endpoint-correction source hash {current}")
    text = raw.decode("utf-8")
    if text.count(OLD) != EXPECTED_COUNT:
        raise RuntimeError(f"expected {EXPECTED_COUNT} Bybit endpoint anchors, found {text.count(OLD)}")
    corrected = text.replace(OLD, NEW).encode("utf-8")
    if digest(corrected) != CORRECTED_SHA256:
        raise RuntimeError(f"corrected source identity mismatch {digest(corrected)}")
    compile(corrected, str(TARGET), "exec")
    TARGET.write_bytes(corrected)
    print(f"BYBIT_ENDPOINT_CORRECTION_APPLIED bytes={len(corrected)} sha256={digest(corrected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
