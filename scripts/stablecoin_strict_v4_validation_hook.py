from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "73aac90eacdc0ddcc34f4e45f0ff8d9369e5b539"
STRICT_SHA = "209a0fbe6e2f61d2c58b3eb7910b8c0c139cd46c"
V4_AUTHORITY = "3532417885505da08c6664a107cf63957e80d922"
SOURCE_ROOT = ROOT / "research" / "ml_stablecoin_issuance_20260726"
ECON_ROOT = ROOT / "research" / "ml_stablecoin_issuance_economic_20260726"
GUARD_ROOT = ROOT / "sourcefix" / "ml_stablecoin_causal_guard_20260726"
V4_ROOT = ROOT / "research" / "execution" / "stablecoin_strict_v4_20260727"
EXEC_ROOT = ROOT / "research" / "execution" / "stablecoin_strict_v4_validator_hook_20260727"
OUT_ROOT = ROOT / "research_runs" / "stablecoin_strict_v4_validator_hook_20260727"
SOURCE_OUT = OUT_ROOT / "source"
ECON_OUT = OUT_ROOT / "economic"
MARKET_CACHE = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "stablecoin-market-v4-hook"


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    allowed: tuple[int, ...] = (0,),
) -> int:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    if completed.returncode not in allowed:
        raise subprocess.CalledProcessError(completed.returncode, command)
    return completed.returncode


def _archive(sha: str, paths: list[str]) -> None:
    _run(["git", "fetch", "--no-tags", "--depth=1", "origin", sha])
    observed = subprocess.check_output(["git", "rev-parse", "FETCH_HEAD"], cwd=ROOT, text=True).strip()
    if observed != sha:
        raise AssertionError(f"fetched {observed}, expected {sha}")
    payload = subprocess.check_output(["git", "archive", sha, *paths], cwd=ROOT)
    subprocess.run(["tar", "-x"], cwd=ROOT, input=payload, check=True)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_hashes(root: Path) -> None:
    rows: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "OUTPUT_SHA256SUMS.txt"):
        rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}\n")
    (root / "OUTPUT_SHA256SUMS.txt").write_text("".join(rows), encoding="utf-8")


def _emit(payload: dict[str, Any]) -> None:
    print("STABLECOIN_STRICT_V4_DECISION_BEGIN", flush=True)
    print(json.dumps(payload, sort_keys=True, default=str), flush=True)
    print("STABLECOIN_STRICT_V4_DECISION_END", flush=True)


def _validate_correction() -> None:
    correction = _json(EXEC_ROOT / "EXECUTION_CORRECTION.json")
    assert correction["source_sha"] == SOURCE_SHA
    assert correction["strict_model_sha"] == STRICT_SHA
    assert correction["v4_authority_commit"] == V4_AUTHORITY
    assert correction["recorded_before_source_decision"] is True
    assert correction["recorded_before_market_outcome"] is True
    assert correction["orders_submitted"] is False


def _materialize() -> None:
    for path in (SOURCE_ROOT, ECON_ROOT, GUARD_ROOT):
        shutil.rmtree(path, ignore_errors=True)
    _archive(SOURCE_SHA, ["research/ml_stablecoin_issuance_20260726"])
    _archive(
        STRICT_SHA,
        [
            "research/ml_stablecoin_issuance_economic_20260726",
            "sourcefix/ml_stablecoin_causal_guard_20260726",
        ],
    )


def _validate_engines() -> None:
    _run(
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
    required_json = [
        SOURCE_ROOT / "CORRECTION_010_USDT_ISSUE_REDEEM_EVENT_SCHEMA_BEFORE_OUTCOME.json",
        SOURCE_ROOT / "CORRECTION_011_BLOCKSCOUT_NULL_TOPIC_PADDING_BEFORE_OUTCOME.json",
        SOURCE_ROOT / "CORRECTION_013_BIND_CORRECTED_SOURCE_SCHEMA_BEFORE_OUTCOME.json",
        SOURCE_ROOT / "CORRECTION_019_BLOCKSCOUT_STATUS0_FAIL_CLOSED_BEFORE_OUTCOME.json",
        GUARD_ROOT / "CORRECTION_002_PREENTRY_INFORMATION_BOUNDARY_BEFORE_OUTCOME.json",
        V4_ROOT / "CORRECTION_004_SIMULTANEOUS_EVENT_AND_LIQUIDATION_DISTANCE_BEFORE_OUTCOME.json",
    ]
    for path in required_json:
        _json(path)
    _run([sys.executable, str(ECON_ROOT / "reconstruct.py")])
    source_env = os.environ.copy()
    source_env["PYTHONPATH"] = str(SOURCE_ROOT)
    strict_env = os.environ.copy()
    strict_env["PYTHONPATH"] = os.pathsep.join([str(ECON_ROOT), str(GUARD_ROOT), str(V4_ROOT)])
    _run([sys.executable, "-m", "pytest", "-q", str(SOURCE_ROOT / "test_source_gate.py")], env=source_env)
    _run([sys.executable, str(SOURCE_ROOT / "run_pinned_snapshot_source.py"), "--self-test"], env=source_env)
    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(ECON_ROOT / "test_run.py"),
            str(ECON_ROOT / "test_run_causal.py"),
            str(GUARD_ROOT / "test_causal_guard.py"),
        ],
        env=strict_env,
    )
    _run([sys.executable, str(V4_ROOT / "strict_guard_v4.py"), "self-test"], env=strict_env)


def _run_source() -> dict[str, Any]:
    shutil.rmtree(SOURCE_OUT, ignore_errors=True)
    SOURCE_OUT.mkdir(parents=True, exist_ok=True)
    source_env = os.environ.copy()
    source_env["PYTHONPATH"] = str(SOURCE_ROOT)
    rc = _run(
        [sys.executable, str(SOURCE_ROOT / "run_pinned_snapshot_source.py"), "--output", str(SOURCE_OUT)],
        env=source_env,
        allowed=(0, 1, 2),
    )
    (SOURCE_OUT / "RUN_EXIT_CODE.txt").write_text(f"{rc}\n", encoding="utf-8")
    result_path = SOURCE_OUT / "SOURCE_GATE_RESULT.json"
    if not result_path.is_file():
        _run(
            [
                sys.executable,
                str(SOURCE_ROOT / "write_transport_failure.py"),
                "--output",
                str(SOURCE_OUT),
                "--transport",
                "TRANSPORT-20260727-STABLECOIN-STRICT-V4-VALIDATOR-CARRIER-001",
                "--exit-code",
                str(rc),
            ],
            env=source_env,
        )
    result = _json(result_path)
    assert result["claim_id"] == "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
    assert result["status"] in {
        "PASS",
        "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE",
        "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE",
    }
    for key in (
        "market_outcome_opened",
        "model_fit",
        "trade_or_pnl_opened",
        "official_2024_2026_opened",
        "orders_submitted",
    ):
        assert result[key] is False
    if result["status"] == "PASS":
        manifest = _json(SOURCE_OUT / "SOURCE_MANIFEST.json")
        events = SOURCE_OUT / "EVENTS.jsonl"
        rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert result["source_schema_id"] == "STABLECOIN_SUPPLY_USDT_ISSUE_REDEEM_USDC_ZERO_TRANSFER_V1"
        assert result["source_correction_id"] == "CORRECTION-20260726-ML-STABLECOIN-USDT-ISSUE-REDEEM-010"
        assert result["transport_response_policy_correction"] == "CORRECTION-20260727-ML-STABLECOIN-BLOCKSCOUT-STATUS0-FAIL-CLOSED-019"
        assert result["pass_checks"] and all(result["pass_checks"].values())
        assert int(result["event_count"]) >= 120
        assert len(result["months_with_events"]) >= 24
        assert sorted(result["distinct_tokens"]) == ["USDC", "USDT"]
        assert {row["token"] for row in rows} == {"USDC", "USDT"}
        assert all(int(row["available_timestamp_12"]) < 1704067200 for row in rows)
        assert all(int(row["available_timestamp_64"]) < 1704067200 for row in rows)
        assert hashlib.sha256(events.read_bytes()).hexdigest() == manifest["events_sha256"]
    return result


def _run_economic(events: Path) -> dict[str, Any]:
    shutil.rmtree(ECON_OUT, ignore_errors=True)
    ECON_OUT.mkdir(parents=True, exist_ok=True)
    MARKET_CACHE.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ECON_ROOT), str(GUARD_ROOT), str(V4_ROOT)])
    rc = _run(
        [
            sys.executable,
            str(V4_ROOT / "strict_guard_v4.py"),
            "run",
            "--events",
            str(events),
            "--market-cache",
            str(MARKET_CACHE),
            "--output",
            str(ECON_OUT),
        ],
        env=env,
        allowed=(0, 2),
    )
    (ECON_OUT / "RUN_EXIT_CODE.txt").write_text(f"{rc}\n", encoding="utf-8")
    result = _json(ECON_OUT / "RESULT.json")
    full = _json(ECON_OUT / "FULL_RESULT.json")
    assert result["claim_id"] == "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
    assert result["status"] in {"PRE2024_BELOW_GATE", "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"}
    assert result["orders_submitted"] is False
    assert result["official_2024h1_opened"] is False
    guard = result["strict_causal_guard"]
    assert guard["fatal_validity_violation"] is False
    v4 = result["simultaneous_event_and_liquidation_guard"]
    assert v4["fatal_validity_violation"] is False
    assert v4["simultaneous_event_prior_rule"] == "STRICTLY_EARLIER_AVAILABILITY_SECOND_GROUPED_BEFORE_APPEND"
    assert v4["liquidation_test_rule"] == "ACTUAL_FILL_TO_STRUCTURAL_STOP_OR_ADVERSE_STOP_GAP"
    serialized = json.dumps(full, sort_keys=True)
    assert '"exit_reason": "SOURCE_BOUNDARY"' not in serialized
    return result


def main() -> int:
    _validate_correction()
    shutil.rmtree(OUT_ROOT, ignore_errors=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    _materialize()
    _validate_engines()
    source = _run_source()
    payload: dict[str, Any] = {
        "claim_id": "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001",
        "source_sha": SOURCE_SHA,
        "strict_sha": STRICT_SHA,
        "v4_authority": V4_AUTHORITY,
        "source_status": source["status"],
        "source_event_count": source.get("event_count"),
        "source_month_count": len(source.get("months_with_events", [])),
        "source_tokens": source.get("distinct_tokens"),
        "orders_submitted": False,
    }
    if source["status"] == "PASS":
        economic = _run_economic(SOURCE_OUT / "EVENTS.jsonl")
        payload["economic_status"] = economic["status"]
        payload["development_gate"] = economic.get("development_gate")
        payload["risk_search_selected"] = economic.get("risk_search", {}).get("selected")
        payload["next_stage"] = (
            "OFFICIAL_2024H1_IMMEDIATELY"
            if economic["status"] == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
            else "CHANGE_ALPHA"
        )
        payload["economic_result"] = economic
    else:
        payload["economic_status"] = "NOT_OPENED"
        payload["next_stage"] = "CLOSE_SOURCE_OR_REPAIR_TRANSPORT_ONLY"
        payload["source_result"] = source
    (OUT_ROOT / "DECISION.json").write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (OUT_ROOT / "EXECUTION_CORRECTION.json").write_bytes((EXEC_ROOT / "EXECUTION_CORRECTION.json").read_bytes())
    _write_hashes(OUT_ROOT)
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
