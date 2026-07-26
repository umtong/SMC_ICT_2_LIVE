from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source_gate.py"
BAD = "\nn        for attempt in range(6):"
GOOD = "\n        for attempt in range(6):"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def corrected_source_text() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    count = text.count(BAD)
    if count != 1:
        raise RuntimeError(f"expected exactly one frozen typo occurrence, found {count}")
    corrected = text.replace(BAD, GOOD)
    compile(corrected, str(SOURCE), "exec")
    return corrected


def verify_only() -> int:
    original = SOURCE.read_bytes()
    corrected = corrected_source_text().encode("utf-8")
    print(
        {
            "status": "SOURCE_RUNTIME_CORRECTION_VERIFIED",
            "original_sha256": sha256_bytes(original),
            "corrected_sha256": sha256_bytes(corrected),
            "replacement_count": 1,
        }
    )
    return 0


def run_forwarded(arguments: list[str]) -> int:
    corrected = corrected_source_text()
    with tempfile.TemporaryDirectory(prefix="uniswap_inventory_source_") as temp_dir:
        runtime = Path(temp_dir) / "source_gate_runtime.py"
        runtime.write_text(corrected, encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(runtime), *arguments],
            cwd=ROOT,
            check=False,
        )
        return int(completed.returncode)


def main() -> int:
    args = sys.argv[1:]
    if args == ["--verify-only"]:
        return verify_only()
    if not args:
        raise SystemExit("pass --verify-only or the frozen source_gate.py arguments")
    return run_forwarded(args)


if __name__ == "__main__":
    raise SystemExit(main())
