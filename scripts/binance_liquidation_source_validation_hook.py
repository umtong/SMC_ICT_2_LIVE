from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIM_ROOT = ROOT / "research" / "ml_binance_liquidation_dense_20260726"
TRIGGER = CLAIM_ROOT / "RUN_VIA_VALIDATE_PROJECT_20260727T0015KST.txt"
RUNNER_TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
OUT = RUNNER_TEMP / "binance_liquidation_dense_source_result"
MARKER = RUNNER_TEMP / "binance_liquidation_dense_source_summary.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, accept: set[int] | None = None) -> int:
    print("BINANCE_LIQ_SOURCE_HOOK_COMMAND", json.dumps(command))
    completed = subprocess.run(command, cwd=ROOT, check=False)
    accepted = {0} if accept is None else accept
    if completed.returncode not in accepted:
        raise RuntimeError(f"command failed rc={completed.returncode}: {command}")
    return int(completed.returncode)


def compact_result(result: dict) -> dict:
    payload = {
        "schema_version": 1,
        "claim_id": result["claim_id"],
        "status": result["status"],
        "source_gate_pass": result["source_gate_pass"],
        "scientific_decision": result["scientific_decision"],
        "market_scope": result["market_scope"],
        "layout": result.get("layout"),
        "checks": result.get("checks", {}),
        "totals": result.get("totals", {}),
        "symbol_coverage": result.get("symbol_coverage", {}),
        "sample_dates": result.get("sample_dates", []),
        "fatal_error": result.get("fatal_error"),
        "market_outcome_opened": result["market_outcome_opened"],
        "model_fit": result["model_fit"],
        "trade_or_pnl_opened": result["trade_or_pnl_opened"],
        "official_2024_2026_opened": result["official_2024_2026_opened"],
        "credentials_used": result["credentials_used"],
        "orders_submitted": result["orders_submitted"],
        "result_sha256": sha256_file(OUT / "SOURCE_GATE_RESULT.json"),
        "manifest_sha256": sha256_file(OUT / "SOURCE_MANIFEST.json"),
        "sample_rows_sha256": sha256_file(OUT / "SAMPLE_ROWS.jsonl.gz"),
    }
    return payload


def emit(summary: dict) -> None:
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False)
    MARKER.write_text(encoded + "\n", encoding="utf-8")
    print("BINANCE_LIQ_SOURCE_RESULT_BEGIN")
    print(encoded)
    print("BINANCE_LIQ_SOURCE_RESULT_END")


def main() -> int:
    if not TRIGGER.exists():
        return 0
    if MARKER.exists():
        print("BINANCE_LIQ_SOURCE_RESULT_BEGIN")
        print(MARKER.read_text(encoding="utf-8").strip())
        print("BINANCE_LIQ_SOURCE_RESULT_END")
        return 0

    print("BINANCE_LIQ_SOURCE_HOOK_BEGIN")
    run([
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "requests==2.32.4",
        "pytest==8.3.5",
    ])
    run([
        sys.executable,
        "-m",
        "py_compile",
        str(CLAIM_ROOT / "source_gate_coinm.py"),
        str(CLAIM_ROOT / "test_source_gate_coinm.py"),
    ])
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(CLAIM_ROOT)
    test = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(CLAIM_ROOT / "test_source_gate_coinm.py")],
        cwd=ROOT,
        env=environment,
        check=False,
    )
    if test.returncode != 0:
        raise RuntimeError(f"source tests failed rc={test.returncode}")
    self_test = subprocess.run(
        [sys.executable, str(CLAIM_ROOT / "source_gate_coinm.py"), "--self-test"],
        cwd=ROOT,
        env=environment,
        check=False,
    )
    if self_test.returncode != 0:
        raise RuntimeError(f"source self-test failed rc={self_test.returncode}")

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    execution = subprocess.run(
        [sys.executable, str(CLAIM_ROOT / "source_gate_coinm.py"), "--output", str(OUT)],
        cwd=ROOT,
        env=environment,
        check=False,
    )
    if execution.returncode not in {0, 2}:
        raise RuntimeError(f"source gate failed mechanically rc={execution.returncode}")

    result_path = OUT / "SOURCE_GATE_RESULT.json"
    manifest_path = OUT / "SOURCE_MANIFEST.json"
    sample_path = OUT / "SAMPLE_ROWS.jsonl.gz"
    if not result_path.is_file() or not manifest_path.is_file() or not sample_path.is_file():
        raise RuntimeError("source gate did not emit required evidence")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["claim_id"] == "CLM-20260726-2020-ML-BINANCE-LIQ-DENSE-001"
    assert result["market_scope"] == "COIN_M_EXTERNAL_SIGNAL"
    assert result["status"] in {"PASS", "BELOW_SOURCE_GATE", "SOURCE_ERROR"}
    assert result["market_outcome_opened"] is False
    assert result["model_fit"] is False
    assert result["trade_or_pnl_opened"] is False
    assert result["official_2024_2026_opened"] is False
    assert result["credentials_used"] is False
    assert result["orders_submitted"] is False
    if result["status"] == "PASS":
        assert result["source_gate_pass"] is True
        assert all(result["checks"].values())
    else:
        assert result["source_gate_pass"] is False

    emit(compact_result(result))
    print("BINANCE_LIQ_SOURCE_HOOK_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
