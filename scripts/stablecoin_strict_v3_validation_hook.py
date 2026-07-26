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
TRIGGER = ROOT / "research" / "triggers" / "stablecoin_strict_v3" / "RUN_20260727T0030KST.txt"
CORRECTION = ROOT / "research" / "triggers" / "stablecoin_strict_v3" / "EXECUTION_CORRECTION_001_VALIDATOR_HOOK_BEFORE_OUTCOME.json"
RUNNER_TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
RUN_ROOT = RUNNER_TEMP / "stablecoin_strict_v3"
SOURCE_SNAPSHOT = RUN_ROOT / "source_snapshot"
STRICT_SNAPSHOT = RUN_ROOT / "strict_snapshot"
SOURCE_ROOT = SOURCE_SNAPSHOT / "research" / "ml_stablecoin_issuance_20260726"
ECON_ROOT = STRICT_SNAPSHOT / "research" / "ml_stablecoin_issuance_economic_20260726"
GUARD_ROOT = STRICT_SNAPSHOT / "sourcefix" / "ml_stablecoin_causal_guard_20260726"
SOURCE_OUT = RUN_ROOT / "source" / "run"
ECON_OUT = RUN_ROOT / "economic" / "run"
MARKET_CACHE = RUN_ROOT / "market_cache"
SUMMARY = RUN_ROOT / "STABLECOIN_STRICT_V3_SUMMARY.json"
SOURCE_SHA = "73aac90eacdc0ddcc34f4e45f0ff8d9369e5b539"
STRICT_SHA = "209a0fbe6e2f61d2c58b3eb7910b8c0c139cd46c"
CLAIM_ID = "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, env_paths: list[Path] | None = None, expected: set[int] | None = None) -> int:
    print("STABLECOIN_STRICT_V3_COMMAND", json.dumps(command))
    environment = os.environ.copy()
    if env_paths:
        environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in env_paths)
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    allowed = expected if expected is not None else {0}
    if completed.returncode not in allowed:
        raise subprocess.CalledProcessError(completed.returncode, command)
    return completed.returncode


def materialize(commit_sha: str, paths: list[str], destination: Path) -> None:
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    run(["git", "fetch", "--no-tags", "--depth=1", "origin", commit_sha])
    resolved = subprocess.check_output(["git", "rev-parse", "FETCH_HEAD"], cwd=ROOT, text=True).strip()
    if resolved != commit_sha:
        raise AssertionError((resolved, commit_sha))
    archive = subprocess.Popen(
        ["git", "archive", commit_sha, *paths],
        cwd=ROOT,
        stdout=subprocess.PIPE,
    )
    assert archive.stdout is not None
    extract = subprocess.run(["tar", "-x", "-C", str(destination)], stdin=archive.stdout, check=False)
    archive.stdout.close()
    archive_rc = archive.wait()
    if archive_rc != 0 or extract.returncode != 0:
        raise RuntimeError(f"archive materialization failed: git={archive_rc}, tar={extract.returncode}")


def assert_false(payload: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        if payload.get(key) is not False:
            raise AssertionError(f"{key} must be false, got {payload.get(key)!r}")


def walk_no_forced_close(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("forced_boundary_close") is True:
            raise AssertionError("forced_boundary_close=true")
        if value.get("exit_reason") == "SOURCE_BOUNDARY":
            raise AssertionError("legacy SOURCE_BOUNDARY exit")
        for child in value.values():
            walk_no_forced_close(child)
    elif isinstance(value, list):
        for child in value:
            walk_no_forced_close(child)


def verify_source() -> tuple[dict[str, Any], Path | None]:
    result_path = SOURCE_OUT / "SOURCE_GATE_RESULT.json"
    if not result_path.is_file():
        raise FileNotFoundError(result_path)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("claim_id") != CLAIM_ID:
        raise AssertionError(result.get("claim_id"))
    if result.get("status") not in {
        "PASS",
        "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE",
        "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE",
    }:
        raise AssertionError(result.get("status"))
    assert_false(
        result,
        (
            "market_outcome_opened",
            "model_fit",
            "trade_or_pnl_opened",
            "official_2024_2026_opened",
            "orders_submitted",
        ),
    )
    if result["status"] != "PASS":
        return result, None

    manifest_path = SOURCE_OUT / "SOURCE_MANIFEST.json"
    events_path = SOURCE_OUT / "EVENTS.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected_schema = "STABLECOIN_SUPPLY_USDT_ISSUE_REDEEM_USDC_ZERO_TRANSFER_V1"
    expected_correction = "CORRECTION-20260726-ML-STABLECOIN-USDT-ISSUE-REDEEM-010"
    if result.get("source_schema_id") != expected_schema or manifest.get("source_schema_id") != expected_schema:
        raise AssertionError("source schema mismatch")
    if result.get("source_correction_id") != expected_correction or manifest.get("source_correction_id") != expected_correction:
        raise AssertionError("source correction mismatch")
    checks = result.get("pass_checks", {})
    if not checks or not all(value is True for value in checks.values()):
        raise AssertionError(checks)
    if result.get("event_semantics", {}).get("ordinary_usdt_transfer_excluded") is not True:
        raise AssertionError("ordinary USDT transfer exclusion missing")
    if int(result.get("event_count", 0)) < 120:
        raise AssertionError(result.get("event_count"))
    if len(result.get("months_with_events", [])) < 24:
        raise AssertionError(result.get("months_with_events"))
    if sorted(result.get("distinct_tokens", [])) != ["USDC", "USDT"]:
        raise AssertionError(result.get("distinct_tokens"))
    if {row["token"] for row in rows} != {"USDC", "USDT"}:
        raise AssertionError("token set mismatch")
    if not {row["direction"] for row in rows}.issubset({"MINT", "BURN"}):
        raise AssertionError("direction set mismatch")
    if not all(int(row["available_timestamp_12"]) < 1_704_067_200 for row in rows):
        raise AssertionError("12-block availability leaked into 2024")
    if not all(int(row["available_timestamp_64"]) < 1_704_067_200 for row in rows):
        raise AssertionError("64-block availability leaked into 2024")
    if sha256_file(events_path) != manifest["events_sha256"]:
        raise AssertionError("event hash mismatch")
    return result, events_path


def verify_economic() -> tuple[dict[str, Any], dict[str, Any]]:
    result_path = ECON_OUT / "RESULT.json"
    full_path = ECON_OUT / "FULL_RESULT.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    full = json.loads(full_path.read_text(encoding="utf-8"))
    if result.get("claim_id") != CLAIM_ID:
        raise AssertionError(result.get("claim_id"))
    if result.get("engine") != "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_STRICT_CAUSAL_V3":
        raise AssertionError(result.get("engine"))
    if result.get("status") not in {"PRE2024_BELOW_GATE", "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"}:
        raise AssertionError(result.get("status"))
    assert_false(result, ("orders_submitted", "official_2024h1_opened", "official_2024_2026_opened"))
    guard = result.get("strict_causal_guard", {})
    expected_guard = {
        "correction_id": "CORRECTION-20260727-ML-STABLECOIN-PREENTRY-INFORMATION-BOUNDARY-002",
        "source_decision_second_respected": True,
        "latest_completed_bar_cutoff_enforced": True,
        "decision_reference_price_pre_entry": True,
        "future_entry_open_used_for_model_or_action": False,
        "entry_open_used_for_realized_execution_only": True,
        "stage_boundary_positions_marked_not_closed": True,
        "fatal_validity_violation": False,
    }
    for key, expected in expected_guard.items():
        if guard.get(key) != expected:
            raise AssertionError((key, guard.get(key), expected))
    walk_no_forced_close(full)
    if result["status"] == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1":
        if result.get("development_gate", {}).get("all") is not True:
            raise AssertionError("survivor without development gate")
        selected = result.get("risk_search", {}).get("selected")
        if not selected or float(selected.get("growth", 0.0)) <= 0 or selected.get("liquidation") is not False:
            raise AssertionError(selected)
    return result, full


def write_summary(source: dict[str, Any], economic: dict[str, Any] | None) -> dict[str, Any]:
    next_stage = "CLOSE_SOURCE_OR_REPAIR_TRANSPORT_ONLY"
    if source.get("status") == "PASS":
        next_stage = "CHANGE_ALPHA"
        if economic and economic.get("status") == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1":
            next_stage = "OFFICIAL_2024H1_IMMEDIATELY"
    summary: dict[str, Any] = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "pinned_source_sha": SOURCE_SHA,
        "pinned_strict_sha": STRICT_SHA,
        "source_status": source.get("status"),
        "source_event_count": source.get("event_count"),
        "source_month_count": len(source.get("months_with_events", [])),
        "source_tokens": source.get("distinct_tokens"),
        "economic_status": economic.get("status") if economic else "NOT_OPENED",
        "development_gate": economic.get("development_gate", {}).get("all") if economic else None,
        "selected_risk_path": economic.get("risk_search", {}).get("selected") if economic else None,
        "next_stage": next_stage,
        "official_2024h1_opened": False,
        "orders_submitted": False,
    }
    if SOURCE_OUT.joinpath("SOURCE_GATE_RESULT.json").is_file():
        summary["source_result_sha256"] = sha256_file(SOURCE_OUT / "SOURCE_GATE_RESULT.json")
    if ECON_OUT.joinpath("RESULT.json").is_file():
        summary["economic_result_sha256"] = sha256_file(ECON_OUT / "RESULT.json")
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def refresh_hashes() -> None:
    rows: list[str] = []
    for path in sorted(item for item in RUN_ROOT.rglob("*") if item.is_file() and item.name != "OUTPUT_SHA256SUMS.txt"):
        rows.append(f"{sha256_file(path)}  {path.relative_to(RUN_ROOT).as_posix()}")
    (RUN_ROOT / "OUTPUT_SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    if not TRIGGER.exists():
        return 0
    if SUMMARY.exists():
        print("STABLECOIN_STRICT_V3_RESULT_BEGIN")
        print(SUMMARY.read_text(encoding="utf-8").strip())
        print("STABLECOIN_STRICT_V3_RESULT_END")
        return 0

    if not CORRECTION.is_file():
        raise FileNotFoundError(CORRECTION)
    json.loads(CORRECTION.read_text(encoding="utf-8"))
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    print("STABLECOIN_STRICT_V3_HOOK_BEGIN")

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
    materialize(SOURCE_SHA, ["research/ml_stablecoin_issuance_20260726"], SOURCE_SNAPSHOT)
    materialize(
        STRICT_SHA,
        [
            "research/ml_stablecoin_issuance_economic_20260726",
            "sourcefix/ml_stablecoin_causal_guard_20260726",
        ],
        STRICT_SNAPSHOT,
    )
    (RUN_ROOT / "PINNED_SOURCE_SHA.txt").write_text(SOURCE_SHA + "\n", encoding="utf-8")
    (RUN_ROOT / "PINNED_STRICT_SHA.txt").write_text(STRICT_SHA + "\n", encoding="utf-8")

    for path in (
        SOURCE_ROOT / "CORRECTION_010_USDT_ISSUE_REDEEM_EVENT_SCHEMA_BEFORE_OUTCOME.json",
        SOURCE_ROOT / "CORRECTION_011_BLOCKSCOUT_NULL_TOPIC_PADDING_BEFORE_OUTCOME.json",
        SOURCE_ROOT / "CORRECTION_013_BIND_CORRECTED_SOURCE_SCHEMA_BEFORE_OUTCOME.json",
        SOURCE_ROOT / "CORRECTION_019_BLOCKSCOUT_STATUS0_FAIL_CLOSED_BEFORE_OUTCOME.json",
        GUARD_ROOT / "CORRECTION_002_PREENTRY_INFORMATION_BOUNDARY_BEFORE_OUTCOME.json",
    ):
        json.loads(path.read_text(encoding="utf-8"))

    run([sys.executable, str(ECON_ROOT / "reconstruct.py")])
    run([sys.executable, "-m", "pytest", "-q", str(SOURCE_ROOT / "test_source_gate.py")], env_paths=[SOURCE_ROOT])
    run([sys.executable, str(SOURCE_ROOT / "run_pinned_snapshot_source.py"), "--self-test"], env_paths=[SOURCE_ROOT])
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(ECON_ROOT / "test_run.py"),
            str(ECON_ROOT / "test_run_causal.py"),
            str(GUARD_ROOT / "test_causal_guard.py"),
        ],
        env_paths=[ECON_ROOT, GUARD_ROOT],
    )
    run([sys.executable, str(GUARD_ROOT / "strict_guard.py"), "self-test"], env_paths=[ECON_ROOT, GUARD_ROOT])

    shutil.rmtree(SOURCE_OUT, ignore_errors=True)
    SOURCE_OUT.mkdir(parents=True, exist_ok=True)
    source_rc = run(
        [sys.executable, str(SOURCE_ROOT / "run_pinned_snapshot_source.py"), "--output", str(SOURCE_OUT)],
        env_paths=[SOURCE_ROOT],
        expected={0, 2},
    )
    (SOURCE_OUT / "RUN_EXIT_CODE.txt").write_text(str(source_rc) + "\n", encoding="utf-8")
    if not (SOURCE_OUT / "SOURCE_GATE_RESULT.json").is_file():
        run(
            [
                sys.executable,
                str(SOURCE_ROOT / "write_transport_failure.py"),
                "--output",
                str(SOURCE_OUT),
                "--transport",
                "TRANSPORT-20260727-ML-STABLECOIN-STRICT-V3-VALIDATOR",
                "--exit-code",
                str(source_rc),
            ],
            env_paths=[SOURCE_ROOT],
        )
    source, events = verify_source()

    economic: dict[str, Any] | None = None
    if events is not None:
        shutil.rmtree(ECON_OUT, ignore_errors=True)
        ECON_OUT.mkdir(parents=True, exist_ok=True)
        MARKET_CACHE.mkdir(parents=True, exist_ok=True)
        economic_rc = run(
            [
                sys.executable,
                str(GUARD_ROOT / "strict_guard.py"),
                "run",
                "--events",
                str(events),
                "--market-cache",
                str(MARKET_CACHE),
                "--output",
                str(ECON_OUT),
            ],
            env_paths=[ECON_ROOT, GUARD_ROOT],
            expected={0, 2},
        )
        (ECON_OUT / "RUN_EXIT_CODE.txt").write_text(str(economic_rc) + "\n", encoding="utf-8")
        economic, _ = verify_economic()

    summary = write_summary(source, economic)
    refresh_hashes()
    print("STABLECOIN_STRICT_V3_RESULT_BEGIN")
    print(json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False))
    print("STABLECOIN_STRICT_V3_RESULT_END")
    print("STABLECOIN_STRICT_V3_HOOK_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
