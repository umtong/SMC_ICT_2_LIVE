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
TRIGGER = CLAIM_ROOT / "RUN_VIA_VALIDATE_PROJECT_20260727T0020KST.txt"
RUNNER_TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
OUT = RUNNER_TEMP / "binance_liquidation_executed_source_result"
MARKER = RUNNER_TEMP / "binance_liquidation_executed_source_summary.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def subprocess_env() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(CLAIM_ROOT)
    return environment


def checked(command: list[str], *, accepted: set[int] = {0}) -> int:
    print("BINANCE_LIQ_EXECUTED_SOURCE_COMMAND", json.dumps(command))
    completed = subprocess.run(command, cwd=ROOT, env=subprocess_env(), check=False)
    if completed.returncode not in accepted:
        raise RuntimeError(f"command failed rc={completed.returncode}: {command}")
    return int(completed.returncode)


def compact_result(result: dict) -> dict:
    return {
        "schema_version": 1,
        "claim_id": result["claim_id"],
        "status": result["status"],
        "source_gate_pass": result["source_gate_pass"],
        "scientific_decision": result["scientific_decision"],
        "market_scope": result["market_scope"],
        "layout": result.get("layout"),
        "source_semantics": result.get("source_semantics", {}),
        "authoritative_corrections": result.get("authoritative_corrections", []),
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


def emit(summary: dict) -> None:
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False)
    MARKER.write_text(encoded + "\n", encoding="utf-8")
    print("BINANCE_LIQ_EXECUTED_SOURCE_RESULT_BEGIN")
    print(encoded)
    print("BINANCE_LIQ_EXECUTED_SOURCE_RESULT_END")


def main() -> int:
    if not TRIGGER.exists():
        return 0
    if MARKER.exists():
        print("BINANCE_LIQ_EXECUTED_SOURCE_RESULT_BEGIN")
        print(MARKER.read_text(encoding="utf-8").strip())
        print("BINANCE_LIQ_EXECUTED_SOURCE_RESULT_END")
        return 0

    print("BINANCE_LIQ_EXECUTED_SOURCE_HOOK_BEGIN")
    checked([
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "requests==2.32.4",
        "pytest==8.3.5",
    ])
    checked([
        sys.executable,
        "-m",
        "py_compile",
        str(CLAIM_ROOT / "source_gate_coinm.py"),
        str(CLAIM_ROOT / "source_gate_coinm_executed.py"),
        str(CLAIM_ROOT / "test_source_gate_coinm.py"),
        str(CLAIM_ROOT / "test_source_gate_coinm_executed.py"),
    ])
    checked([
        sys.executable,
        "-m",
        "pytest",
        "-q",
        str(CLAIM_ROOT / "test_source_gate_coinm.py"),
        str(CLAIM_ROOT / "test_source_gate_coinm_executed.py"),
    ])
    checked([sys.executable, str(CLAIM_ROOT / "source_gate_coinm_executed.py"), "--self-test"])

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    checked(
        [sys.executable, str(CLAIM_ROOT / "source_gate_coinm_executed.py"), "--output", str(OUT)],
        accepted={0, 2},
    )

    required = [
        OUT / "SOURCE_GATE_RESULT.json",
        OUT / "SOURCE_MANIFEST.json",
        OUT / "SAMPLE_ROWS.jsonl.gz",
    ]
    if not all(path.is_file() for path in required):
        raise RuntimeError("source gate did not emit required evidence")
    result = json.loads(required[0].read_text(encoding="utf-8"))
    assert result["claim_id"] == "CLM-20260726-2020-ML-BINANCE-LIQ-DENSE-001"
    assert result["market_scope"] == "COIN_M_EXTERNAL_SIGNAL"
    assert result["status"] in {"PASS", "BELOW_SOURCE_GATE", "SOURCE_ERROR"}
    assert result["source_semantics"]["coverage"].startswith("censored lower-bound")
    assert "CORRECTION-20260726-ML-BINANCE-LIQ-SNAPSHOT-CENSORING-EXECUTED-FILL-004" in result["authoritative_corrections"]
    assert result["checks"]["original_quantity_fallback_prohibited"] is True
    assert result["checks"]["only_positive_executed_snapshots_enter_signal_rows"] is True
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
    print("BINANCE_LIQ_EXECUTED_SOURCE_HOOK_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
