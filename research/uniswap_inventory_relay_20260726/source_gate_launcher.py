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
FUTURE_BYBIT_PROBE = '        ("ETHUSDT", 5, 2024, 1, 31),'
PRE2024_BYBIT_PROBE = '        ("ETHUSDT", 5, 2022, 7, 31),'


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def corrected_source_text() -> str:
    text = SOURCE.read_text(encoding="utf-8")

    typo_count = text.count(BAD)
    if typo_count == 1:
        corrected = text.replace(BAD, GOOD)
    elif typo_count == 0:
        corrected = text
    else:
        raise RuntimeError(f"expected zero or one frozen typo occurrence, found {typo_count}")

    future_count = corrected.count(FUTURE_BYBIT_PROBE)
    pre2024_count = corrected.count(PRE2024_BYBIT_PROBE)
    if future_count == 1 and pre2024_count == 0:
        corrected = corrected.replace(FUTURE_BYBIT_PROBE, PRE2024_BYBIT_PROBE)
    elif future_count == 0 and pre2024_count == 1:
        pass
    else:
        raise RuntimeError(
            "expected exactly one future probe to replace or one already-corrected "
            f"pre-2024 probe; future={future_count}, pre2024={pre2024_count}"
        )

    compile(corrected, str(SOURCE), "exec")
    return corrected


def verify_only() -> int:
    original_text = SOURCE.read_text(encoding="utf-8")
    original = original_text.encode("utf-8")
    corrected = corrected_source_text().encode("utf-8")
    print(
        {
            "status": "SOURCE_RUNTIME_VERIFIED",
            "original_sha256": sha256_bytes(original),
            "corrected_sha256": sha256_bytes(corrected),
            "typo_replacement_count": original_text.count(BAD),
            "future_probe_replacement_count": original_text.count(FUTURE_BYBIT_PROBE),
            "pre2024_probe_count_after_correction": corrected.decode("utf-8").count(PRE2024_BYBIT_PROBE),
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
