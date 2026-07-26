from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIGGER = ROOT / "research" / "execution" / "stablecoin_causal_visible_20260727" / "RUN_TRIGGER_20260727T0024KST.txt"
RUNNER_TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
WORK = RUNNER_TEMP / "stablecoin_strict_v3_validation_hook"
SOURCE_ROOT = WORK / "repository" / "research" / "ml_stablecoin_issuance_20260726"
ECON_ROOT = WORK / "repository" / "research" / "ml_stablecoin_issuance_economic_20260726"
GUARD_ROOT = WORK / "repository" / "sourcefix" / "ml_stablecoin_causal_guard_20260726"
SOURCE_OUT = WORK / "source"
ECON_OUT = WORK / "economic"
MARKET_CACHE = WORK / "market"
MARKER = RUNNER_TEMP / "stablecoin_strict_v3_validation_hook_summary.json"
SOURCE_SHA = "3631cf01a2a2b91d690b81160e14ba033a298f75"
STRICT_SHA = "209a0fbe6e2f61d2c58b3eb7910b8c0c139cd46c"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("STABLECOIN_STRICT_V3_HOOK_COMMAND", json.dumps(command), flush=True)
    environment = os.environ.copy()
    if env:
        environment.update(env)
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=check,
        text=True,
    )


def materialize(commit: str, paths: list[str]) -> None:
    run(["git", "fetch", "--no-tags", "--depth=1", "origin", commit])
    observed = subprocess.check_output(["git", "rev-parse", "FETCH_HEAD"], cwd=ROOT, text=True).strip()
    if observed != commit:
        raise RuntimeError(f"fetched {observed}, expected {commit}")
    archive = subprocess.Popen(
        ["git", "archive", commit, *paths],
        cwd=ROOT,
        stdout=subprocess.PIPE,
    )
    assert archive.stdout is not None
    extract = subprocess.run(
        ["tar", "-x", "-C", str(WORK / "repository")],
        stdin=archive.stdout,
        check=True,
    )
    archive.stdout.close()
    archive_rc = archive.wait()
    if archive_rc != 0 or extract.returncode != 0:
        raise RuntimeError(f"archive failed: {archive_rc}, {extract.returncode}")


def compact_source(source: dict) -> dict:
    return {
        "status": source.get("status"),
        "event_count": source.get("event_count"),
        "months_with_events": len(source.get("months_with_events", [])),
        "distinct_tokens": source.get("distinct_tokens"),
        "source_schema_id": source.get("source_schema_id"),
        "source_correction_id": source.get("source_correction_id"),
        "transport_response_policy_correction": source.get("transport_response_policy_correction"),
        "fatal_error": source.get("fatal_error"),
    }


def write_summary(source: dict, economic: dict | None) -> dict:
    summary: dict[str, object] = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001",
        "source_sha": SOURCE_SHA,
        "strict_sha": STRICT_SHA,
        "source": compact_source(source),
        "source_result_sha256": sha256_file(SOURCE_OUT / "SOURCE_GATE_RESULT.json"),
        "economic": None,
        "next_stage": "CLOSE_SOURCE_OR_REPAIR_TRANSPORT_ONLY",
        "official_2024h1_opened": False,
        "orders_submitted": False,
    }
    if economic is not None:
        summary["economic"] = {
            "status": economic.get("status"),
            "engine": economic.get("engine"),
            "development_gate": economic.get("development_gate"),
            "risk_search": economic.get("risk_search"),
            "strict_causal_guard": economic.get("strict_causal_guard"),
            "result_sha256": sha256_file(ECON_OUT / "RESULT.json"),
            "full_result_sha256": sha256_file(ECON_OUT / "FULL_RESULT.json"),
        }
        summary["next_stage"] = (
            "OFFICIAL_2024H1_IMMEDIATELY"
            if economic.get("status") == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
            else "CHANGE_ALPHA"
        )
    MARKER.write_text(json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    return summary


def validate_source(source: dict) -> bool:
    assert source["claim_id"] == "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
    assert source["status"] in {
        "PASS",
        "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE",
        "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE",
    }
    assert source["market_outcome_opened"] is False
    assert source["model_fit"] is False
    assert source["trade_or_pnl_opened"] is False
    assert source["official_2024_2026_opened"] is False
    assert source["orders_submitted"] is False
    if source["status"] != "PASS":
        return False

    manifest = json.loads((SOURCE_OUT / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    events_path = SOURCE_OUT / "EVENTS.jsonl"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected_schema = "STABLECOIN_SUPPLY_USDT_ISSUE_REDEEM_USDC_ZERO_TRANSFER_V1"
    expected_correction = "CORRECTION-20260726-ML-STABLECOIN-USDT-ISSUE-REDEEM-010"
    expected_policy = "CORRECTION-20260727-ML-STABLECOIN-BLOCKSCOUT-STATUS0-FAIL-CLOSED-019"
    checks = source.get("pass_checks", {})
    assert checks and all(value is True for value in checks.values())
    assert source.get("source_schema_id") == expected_schema
    assert source.get("source_correction_id") == expected_correction
    assert manifest.get("source_schema_id") == expected_schema
    assert manifest.get("source_correction_id") == expected_correction
    assert source.get("transport_response_policy_correction") == expected_policy
    assert manifest.get("transport_response_policy_correction") == expected_policy
    assert source.get("status_zero_empty_policy") == "EXPLICIT_NO_RECORDS_ONLY"
    assert source.get("unrecognized_status_zero_policy") == "FAIL_CLOSED_SOURCE_UNAVAILABLE"
    assert source.get("event_semantics", {}).get("ordinary_usdt_transfer_excluded") is True
    assert int(source["event_count"]) >= 120
    assert len(source["months_with_events"]) >= 24
    assert sorted(source["distinct_tokens"]) == ["USDC", "USDT"]
    assert {row["token"] for row in rows} == {"USDC", "USDT"}
    assert {row["direction"] for row in rows}.issubset({"MINT", "BURN"})
    assert all(int(row["block_timestamp"]) < 1704067200 for row in rows)
    assert all(int(row["available_timestamp_12"]) < 1704067200 for row in rows)
    assert all(int(row["available_timestamp_64"]) < 1704067200 for row in rows)
    assert hashlib.sha256(events_path.read_bytes()).hexdigest() == manifest["events_sha256"]
    return True


def validate_economic(result: dict, full: dict) -> None:
    assert result["claim_id"] == "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
    assert result["engine"] == "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_STRICT_CAUSAL_V3"
    assert result["orders_submitted"] is False
    assert result["official_2024h1_opened"] is False
    assert result["official_2024_2026_opened"] is False
    assert result["status"] in {
        "PRE2024_BELOW_GATE",
        "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1",
    }
    guard = result["strict_causal_guard"]
    assert guard["correction_id"] == "CORRECTION-20260727-ML-STABLECOIN-PREENTRY-INFORMATION-BOUNDARY-002"
    assert guard["source_decision_second_respected"] is True
    assert guard["latest_completed_bar_cutoff_enforced"] is True
    assert guard["decision_reference_price_pre_entry"] is True
    assert guard["future_entry_open_used_for_model_or_action"] is False
    assert guard["entry_open_used_for_realized_execution_only"] is True
    assert guard["stage_boundary_positions_marked_not_closed"] is True
    assert guard["fatal_validity_violation"] is False
    serialized = json.dumps(full, sort_keys=True)
    assert '"exit_reason": "SOURCE_BOUNDARY"' not in serialized

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if "forced_boundary_close" in value:
                assert value["forced_boundary_close"] is False
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(full)
    if result["status"] == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1":
        assert result["development_gate"]["all"] is True
        selected = result["risk_search"]["selected"]
        assert selected is not None
        assert selected["growth"] > 0
        assert selected["liquidation"] is False


def main() -> int:
    if not TRIGGER.exists():
        return 0
    if MARKER.exists():
        print("STABLECOIN_STRICT_V3_RESULT_BEGIN")
        print(MARKER.read_text(encoding="utf-8").strip())
        print("STABLECOIN_STRICT_V3_RESULT_END")
        return 0

    print("STABLECOIN_STRICT_V3_HOOK_BEGIN", flush=True)
    shutil.rmtree(WORK, ignore_errors=True)
    (WORK / "repository").mkdir(parents=True, exist_ok=True)
    SOURCE_OUT.mkdir(parents=True, exist_ok=True)
    ECON_OUT.mkdir(parents=True, exist_ok=True)
    MARKET_CACHE.mkdir(parents=True, exist_ok=True)

    run([
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
    ])
    materialize(SOURCE_SHA, ["research/ml_stablecoin_issuance_20260726"])
    materialize(
        STRICT_SHA,
        [
            "research/ml_stablecoin_issuance_economic_20260726",
            "sourcefix/ml_stablecoin_causal_guard_20260726",
        ],
    )

    run([sys.executable, "-m", "json.tool", str(SOURCE_ROOT / "CORRECTION_010_USDT_ISSUE_REDEEM_EVENT_SCHEMA_BEFORE_OUTCOME.json")])
    run([sys.executable, "-m", "json.tool", str(SOURCE_ROOT / "CORRECTION_011_BLOCKSCOUT_NULL_TOPIC_PADDING_BEFORE_OUTCOME.json")])
    run([sys.executable, "-m", "json.tool", str(SOURCE_ROOT / "CORRECTION_019_BLOCKSCOUT_STATUS0_FAIL_CLOSED_BEFORE_OUTCOME.json")])
    run([sys.executable, "-m", "py_compile", *[str(path) for path in SOURCE_ROOT.glob("source_gate*.py")], str(SOURCE_ROOT / "run_pinned_snapshot_source.py"), str(SOURCE_ROOT / "test_source_gate.py"), str(SOURCE_ROOT / "write_transport_failure.py")])
    source_env = {"PYTHONPATH": str(SOURCE_ROOT)}
    run([sys.executable, "-m", "pytest", "-q", str(SOURCE_ROOT / "test_source_gate.py")], env=source_env)
    run([sys.executable, str(SOURCE_ROOT / "run_pinned_snapshot_source.py"), "--self-test"], env=source_env)

    source_process = run(
        [sys.executable, str(SOURCE_ROOT / "run_pinned_snapshot_source.py"), "--output", str(SOURCE_OUT)],
        env=source_env,
        check=False,
    )
    (SOURCE_OUT / "RUN_EXIT_CODE.txt").write_text(f"{source_process.returncode}\n", encoding="utf-8")
    if not (SOURCE_OUT / "SOURCE_GATE_RESULT.json").exists():
        run([
            sys.executable,
            str(SOURCE_ROOT / "write_transport_failure.py"),
            "--output",
            str(SOURCE_OUT),
            "--transport",
            "TRANSPORT-20260727-ML-STABLECOIN-STRICT-V3-HOOK",
            "--exit-code",
            str(source_process.returncode),
        ], env=source_env)
    source = json.loads((SOURCE_OUT / "SOURCE_GATE_RESULT.json").read_text(encoding="utf-8"))
    if not validate_source(source):
        summary = write_summary(source, None)
        print("STABLECOIN_STRICT_V3_RESULT_BEGIN")
        print(json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False))
        print("STABLECOIN_STRICT_V3_RESULT_END")
        print("STABLECOIN_STRICT_V3_HOOK_END")
        return 0

    run([sys.executable, str(ECON_ROOT / "reconstruct.py")])
    run([
        sys.executable,
        "-m",
        "py_compile",
        str(ECON_ROOT / "run.py"),
        str(ECON_ROOT / "run_causal.py"),
        str(ECON_ROOT / "test_run.py"),
        str(ECON_ROOT / "test_run_causal.py"),
        str(ECON_ROOT / "reconstruct.py"),
        str(GUARD_ROOT / "causal_guard.py"),
        str(GUARD_ROOT / "strict_guard.py"),
        str(GUARD_ROOT / "test_causal_guard.py"),
    ])
    strict_env = {"PYTHONPATH": os.pathsep.join([str(ECON_ROOT), str(GUARD_ROOT)])}
    run([
        sys.executable,
        "-m",
        "pytest",
        "-q",
        str(ECON_ROOT / "test_run.py"),
        str(ECON_ROOT / "test_run_causal.py"),
        str(GUARD_ROOT / "test_causal_guard.py"),
    ], env=strict_env)
    run([sys.executable, str(GUARD_ROOT / "strict_guard.py"), "self-test"], env=strict_env)
    economic_process = run([
        sys.executable,
        str(GUARD_ROOT / "strict_guard.py"),
        "run",
        "--events",
        str(SOURCE_OUT / "EVENTS.jsonl"),
        "--market-cache",
        str(MARKET_CACHE),
        "--output",
        str(ECON_OUT),
    ], env=strict_env, check=False)
    (ECON_OUT / "RUN_EXIT_CODE.txt").write_text(f"{economic_process.returncode}\n", encoding="utf-8")
    if economic_process.returncode not in {0, 2}:
        raise RuntimeError(f"strict economic process failed: {economic_process.returncode}")
    result = json.loads((ECON_OUT / "RESULT.json").read_text(encoding="utf-8"))
    full = json.loads((ECON_OUT / "FULL_RESULT.json").read_text(encoding="utf-8"))
    validate_economic(result, full)
    summary = write_summary(source, result)
    print("STABLECOIN_STRICT_V3_RESULT_BEGIN")
    print(json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False))
    print("STABLECOIN_STRICT_V3_RESULT_END")
    print("STABLECOIN_STRICT_V3_HOOK_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
