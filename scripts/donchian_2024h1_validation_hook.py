from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIM_ROOT = ROOT / "research" / "donchian_2024h1_20260726"
TRIGGER = CLAIM_ROOT / "RUN_VIA_VALIDATE_PROJECT_20260726T2218KST.txt"
RUNNER_TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
MARKER = RUNNER_TEMP / "donchian_2024h1_validation_hook_summary.json"
DATA = RUNNER_TEMP / "donchian_2024h1_validator_data"
OUT = RUNNER_TEMP / "donchian_2024h1_validator_result"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str]) -> None:
    print("DONCHIAN_2024H1_HOOK_COMMAND", json.dumps(command))
    subprocess.run(command, cwd=ROOT, check=True)


def compact_result(result: dict) -> dict:
    manifest_bytes = json.dumps(result["source_manifest"], sort_keys=True, separators=(",", ":")).encode()
    funding = result.get("funding_status", {})
    return {
        "schema_version": 1,
        "claim_id": result["claim_id"],
        "result_id": result["result_id"],
        "status": result["status"],
        "hard_validity_status": result["hard_validity_status"],
        "economic_status": result["economic_status"],
        "ranking_role": result["ranking_role"],
        "candidate_event_count": result["candidate_event_count"],
        "evaluation": result["evaluation"],
        "funding_mode": funding.get("mode"),
        "funding_counts": funding.get("counts", funding.get("counts_before_fallback", {})),
        "source_file_count": len(result["source_manifest"]),
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "paths": result["paths"],
        "target": result["target"],
        "opened_periods": result["opened_periods"],
        "unopened_periods": result["unopened_periods"],
        "orders_submitted": result["orders_submitted"],
        "paper_live_started": result["paper_live_started"],
        "result_sha256": sha256_file(OUT / "RESULT.json"),
        "output_sha256sums_sha256": sha256_file(OUT / "SHA256SUMS.txt"),
    }


def main() -> int:
    if not TRIGGER.exists():
        return 0
    if MARKER.exists():
        print("DONCHIAN_2024H1_RESULT_BEGIN")
        print(MARKER.read_text(encoding="utf-8").strip())
        print("DONCHIAN_2024H1_RESULT_END")
        return 0

    print("DONCHIAN_2024H1_HOOK_BEGIN")
    run([
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "numpy==2.1.3",
        "pandas==2.2.3",
        "requests==2.32.4",
    ])
    run([sys.executable, str(CLAIM_ROOT / "reconstruct.py")])
    run([sys.executable, "-m", "py_compile", str(CLAIM_ROOT / "run.py"), str(CLAIM_ROOT / "download_bars.py"), str(CLAIM_ROOT / "download_funding.py")])
    run([sys.executable, "-m", "pytest", "-q", str(CLAIM_ROOT / "test_run.py")])
    run([sys.executable, str(CLAIM_ROOT / "run.py"), "self-test"])

    shutil.rmtree(DATA, ignore_errors=True)
    shutil.rmtree(OUT, ignore_errors=True)
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    run([sys.executable, str(CLAIM_ROOT / "download_bars.py"), "--output", str(DATA)])
    run([sys.executable, str(CLAIM_ROOT / "download_funding.py"), "--output", str(DATA)])
    run([sys.executable, str(CLAIM_ROOT / "run.py"), "run", "--data-root", str(DATA), "--output", str(OUT)])

    result = json.loads((OUT / "RESULT.json").read_text(encoding="utf-8"))
    assert result["claim_id"] == "CLM-20260726-2139-DONCHIAN-2024H1-001"
    assert result["opened_periods"] == ["2024H1"]
    assert result["unopened_periods"] == ["2024H2", "2025H1", "2025H2", "2026H1"]
    assert result["evaluation"]["elapsed_time_liquidation"] is False
    assert result["evaluation"]["forced_boundary_close"] is False
    assert result["orders_submitted"] is False
    assert result["paper_live_started"] is False

    summary = compact_result(result)
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False)
    MARKER.write_text(encoded + "\n", encoding="utf-8")
    print("DONCHIAN_2024H1_RESULT_BEGIN")
    print(encoded)
    print("DONCHIAN_2024H1_RESULT_END")
    print("DONCHIAN_2024H1_HOOK_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
