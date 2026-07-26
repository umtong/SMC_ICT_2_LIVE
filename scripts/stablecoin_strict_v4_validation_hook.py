from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIGGER = (
    ROOT
    / "research"
    / "triggers"
    / "stablecoin_strict_v4_validator"
    / "RUN_20260727T0122KST.json"
)
RUNNER_TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
WORK = RUNNER_TEMP / "stablecoin_profit_v5_validator_work"
PUBLISH = RUNNER_TEMP / "stablecoin_profit_v5_validator_result"
MARKER = RUNNER_TEMP / "stablecoin_profit_v5_validator_summary.json"
AUTHORITY = ROOT / "scripts" / "run_stablecoin_profit_v5_single_pass_authority.py"


def run(
    command: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    print(
        "STABLECOIN_PROFIT_V5_VALIDATOR_COMMAND",
        json.dumps(command),
        flush=True,
    )
    environment = os.environ.copy()
    environment["SMC_STABLECOIN_PROFIT_V5_HOOK_ACTIVE"] = "1"
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        check=check,
    )


def main() -> int:
    if not TRIGGER.exists():
        return 0
    if MARKER.exists():
        print("STABLECOIN_PROFIT_V5_RESULT_BEGIN")
        print(MARKER.read_text(encoding="utf-8").strip())
        print("STABLECOIN_PROFIT_V5_RESULT_END")
        return 0

    print("STABLECOIN_PROFIT_V5_VALIDATOR_HOOK_BEGIN", flush=True)
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "requests==2.32.4",
            "pytest==8.3.5",
            "numpy==2.1.3",
            "pandas==2.2.3",
            "scikit-learn==1.6.1",
            "pyarrow==18.1.0",
        ]
    )
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(PUBLISH, ignore_errors=True)
    process = run(
        [
            sys.executable,
            str(AUTHORITY),
            "--work-dir",
            str(WORK),
            "--publish-dir",
            str(PUBLISH),
        ],
        check=False,
    )

    decision = PUBLISH / "DECISION.json"
    failure = PUBLISH / "EXECUTION_FAILURE.json"
    if decision.exists():
        payload = json.loads(decision.read_text(encoding="utf-8"))
    elif failure.exists():
        payload = json.loads(failure.read_text(encoding="utf-8"))
    else:
        payload = {
            "schema_version": 1,
            "status": "EXECUTION_FAILURE_WITHOUT_DURABLE_RESULT",
            "process_returncode": process.returncode,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        }
    payload["validator_process_returncode"] = process.returncode
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    MARKER.write_text(encoded + "\n", encoding="utf-8")
    print("STABLECOIN_PROFIT_V5_RESULT_BEGIN")
    print(encoded)
    print("STABLECOIN_PROFIT_V5_RESULT_END")
    print("STABLECOIN_PROFIT_V5_VALIDATOR_HOOK_END", flush=True)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
