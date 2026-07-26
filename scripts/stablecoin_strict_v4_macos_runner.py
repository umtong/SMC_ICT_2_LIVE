from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

CLAIM_ID = "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
SOURCE_SHA = "73aac90eacdc0ddcc34f4e45f0ff8d9369e5b539"
STRICT_SHA = "209a0fbe6e2f61d2c58b3eb7910b8c0c139cd46c"
SOURCE_SCHEMA = "STABLECOIN_SUPPLY_USDT_ISSUE_REDEEM_USDC_ZERO_TRANSFER_V1"
SOURCE_CORRECTION = "CORRECTION-20260726-ML-STABLECOIN-USDT-ISSUE-REDEEM-010"
TRANSPORT_CORRECTION = "CORRECTION-20260727-ML-STABLECOIN-BLOCKSCOUT-STATUS0-FAIL-CLOSED-019"
V3_CORRECTION = "CORRECTION-20260727-ML-STABLECOIN-PREENTRY-INFORMATION-BOUNDARY-002"
V4_CORRECTION = "CORRECTION-20260727-ML-STABLECOIN-SIMULTANEOUS-EVENT-LIQUIDATION-DISTANCE-004"
ENGINE = "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_STRICT_CAUSAL_V3"

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
RUN_ROOT = RUNNER_TEMP / "stablecoin_strict_v4_macos"
SOURCE_SNAPSHOT = RUN_ROOT / "source_snapshot"
STRICT_SNAPSHOT = RUN_ROOT / "strict_snapshot"
SOURCE_ROOT = SOURCE_SNAPSHOT / "research" / "ml_stablecoin_issuance_20260726"
ECON_ROOT = STRICT_SNAPSHOT / "research" / "ml_stablecoin_issuance_economic_20260726"
GUARD_ROOT = STRICT_SNAPSHOT / "sourcefix" / "ml_stablecoin_causal_guard_20260726"
V4_ROOT = REPO_ROOT / "research" / "execution" / "stablecoin_strict_v4_20260727"
SOURCE_OUT = RUN_ROOT / "output" / "source"
ECON_OUT = RUN_ROOT / "output" / "economic"
MARKET_CACHE = RUN_ROOT / "market_cache"
SUMMARY_PATH = RUN_ROOT / "STABLECOIN_STRICT_V4_SUMMARY.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def execute(
    command: list[str],
    *,
    python_paths: list[Path] | None = None,
    expected: set[int] | None = None,
) -> int:
    env = os.environ.copy()
    if python_paths:
        env["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths)
    print("STRICT_V4_COMMAND", json.dumps(command))
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env, check=False)
    allowed = expected if expected is not None else {0}
    if completed.returncode not in allowed:
        raise subprocess.CalledProcessError(completed.returncode, command)
    return completed.returncode


def materialize(commit_sha: str, repo_paths: list[str], destination: Path) -> None:
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    execute(["git", "fetch", "--no-tags", "--depth=1", "origin", commit_sha])
    resolved = subprocess.check_output(
        ["git", "rev-parse", "FETCH_HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    if resolved != commit_sha:
        raise AssertionError((resolved, commit_sha))
    archive = subprocess.Popen(
        ["git", "archive", commit_sha, *repo_paths],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
    )
    assert archive.stdout is not None
    extract = subprocess.run(
        ["tar", "-x", "-C", str(destination)],
        stdin=archive.stdout,
        check=False,
    )
    archive.stdout.close()
    archive_code = archive.wait()
    if archive_code != 0 or extract.returncode != 0:
        raise RuntimeError(
            f"snapshot extraction failed git={archive_code} tar={extract.returncode}"
        )


def assert_json_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def verify_source() -> tuple[dict[str, Any], Path | None]:
    result_path = SOURCE_OUT / "SOURCE_GATE_RESULT.json"
    result = assert_json_file(result_path)
    if result.get("claim_id") != CLAIM_ID:
        raise AssertionError(result.get("claim_id"))
    allowed = {
        "PASS",
        "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE",
        "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE",
    }
    if result.get("status") not in allowed:
        raise AssertionError(result.get("status"))
    for key in (
        "market_outcome_opened",
        "model_fit",
        "trade_or_pnl_opened",
        "official_2024_2026_opened",
        "orders_submitted",
    ):
        if result.get(key) is not False:
            raise AssertionError((key, result.get(key)))
    if result["status"] != "PASS":
        return result, None

    manifest = assert_json_file(SOURCE_OUT / "SOURCE_MANIFEST.json")
    events = SOURCE_OUT / "EVENTS.jsonl"
    rows = [
        json.loads(line)
        for line in events.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if result.get("source_schema_id") != SOURCE_SCHEMA:
        raise AssertionError(result.get("source_schema_id"))
    if result.get("source_correction_id") != SOURCE_CORRECTION:
        raise AssertionError(result.get("source_correction_id"))
    if result.get("transport_response_policy_correction") != TRANSPORT_CORRECTION:
        raise AssertionError(result.get("transport_response_policy_correction"))
    if result.get("status_zero_empty_policy") != "EXPLICIT_NO_RECORDS_ONLY":
        raise AssertionError(result.get("status_zero_empty_policy"))
    if result.get("status_zero_range_policy") != "EXPLICIT_RANGE_LIMIT_ONLY":
        raise AssertionError(result.get("status_zero_range_policy"))
    if result.get("unrecognized_status_zero_policy") != "FAIL_CLOSED_SOURCE_UNAVAILABLE":
        raise AssertionError(result.get("unrecognized_status_zero_policy"))
    if manifest.get("source_schema_id") != SOURCE_SCHEMA:
        raise AssertionError("manifest source schema")
    if manifest.get("source_correction_id") != SOURCE_CORRECTION:
        raise AssertionError("manifest source correction")
    if manifest.get("transport_response_policy_correction") != TRANSPORT_CORRECTION:
        raise AssertionError("manifest transport correction")
    checks = result.get("pass_checks", {})
    if not checks or not all(value is True for value in checks.values()):
        raise AssertionError(checks)
    if result.get("event_semantics", {}).get("ordinary_usdt_transfer_excluded") is not True:
        raise AssertionError("ordinary USDT transfers not excluded")
    if int(result.get("event_count", 0)) < 120:
        raise AssertionError(result.get("event_count"))
    if len(result.get("months_with_events", [])) < 24:
        raise AssertionError(result.get("months_with_events"))
    if sorted(result.get("distinct_tokens", [])) != ["USDC", "USDT"]:
        raise AssertionError(result.get("distinct_tokens"))
    if {row["token"] for row in rows} != {"USDC", "USDT"}:
        raise AssertionError("event token set")
    if not {row["direction"] for row in rows}.issubset({"MINT", "BURN"}):
        raise AssertionError("event direction set")
    if not all(int(row["available_timestamp_12"]) < 1_704_067_200 for row in rows):
        raise AssertionError("12-block availability leaked into 2024")
    if not all(int(row["available_timestamp_64"]) < 1_704_067_200 for row in rows):
        raise AssertionError("64-block availability leaked into 2024")
    if sha256_file(events) != manifest.get("events_sha256"):
        raise AssertionError("event digest mismatch")
    return result, events


def walk_result(value: Any, ledger_rows: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if value.get("exit_reason") == "SOURCE_BOUNDARY":
            raise AssertionError("legacy SOURCE_BOUNDARY exit")
        if value.get("forced_boundary_close") is True:
            raise AssertionError("forced boundary close")
        if {"event_id", "leverage", "account_return", "stop_fraction"}.issubset(value):
            ledger_rows.append(value)
        for child in value.values():
            walk_result(child, ledger_rows)
    elif isinstance(value, list):
        for child in value:
            walk_result(child, ledger_rows)


def verify_economic() -> tuple[dict[str, Any], dict[str, Any]]:
    result = assert_json_file(ECON_OUT / "RESULT.json")
    full = assert_json_file(ECON_OUT / "FULL_RESULT.json")
    if result.get("claim_id") != CLAIM_ID or result.get("engine") != ENGINE:
        raise AssertionError((result.get("claim_id"), result.get("engine")))
    if result.get("status") not in {
        "PRE2024_BELOW_GATE",
        "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1",
    }:
        raise AssertionError(result.get("status"))
    for key in ("orders_submitted", "official_2024h1_opened", "official_2024_2026_opened"):
        if result.get(key) is not False:
            raise AssertionError((key, result.get(key)))

    guard = result.get("strict_causal_guard", {})
    expected_v3 = {
        "correction_id": V3_CORRECTION,
        "source_decision_second_respected": True,
        "latest_completed_bar_cutoff_enforced": True,
        "decision_reference_price_pre_entry": True,
        "future_entry_open_used_for_model_or_action": False,
        "entry_open_used_for_realized_execution_only": True,
        "stage_boundary_positions_marked_not_closed": True,
        "fatal_validity_violation": False,
    }
    for key, expected in expected_v3.items():
        if guard.get(key) != expected:
            raise AssertionError((key, guard.get(key), expected))

    v4 = result.get("simultaneous_event_and_liquidation_guard", {})
    expected_v4 = {
        "correction_id": V4_CORRECTION,
        "simultaneous_event_prior_rule": "STRICTLY_EARLIER_AVAILABILITY_SECOND_GROUPED_BEFORE_APPEND",
        "planned_quantity_rule": "PREENTRY_EXPECTED_STOP_DISTANCE_PLUS_COST",
        "liquidation_test_rule": "ACTUAL_FILL_TO_STRUCTURAL_STOP_OR_ADVERSE_STOP_GAP",
        "fatal_validity_violation": False,
    }
    for key, expected in expected_v4.items():
        if v4.get(key) != expected:
            raise AssertionError((key, v4.get(key), expected))

    ledger_rows: list[dict[str, Any]] = []
    walk_result(full, ledger_rows)
    for row in ledger_rows:
        for key in (
            "planned_stop_fraction",
            "actual_structural_stop_fraction",
            "liquidation_test_distance",
        ):
            if key not in row:
                raise AssertionError((row.get("event_id"), key))
        if row.get("liquidation_distance_rule") != "ACTUAL_FILL_TO_STRUCTURAL_STOP_OR_ADVERSE_GAP":
            raise AssertionError(row.get("liquidation_distance_rule"))

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
        "source_sha": SOURCE_SHA,
        "strict_sha": STRICT_SHA,
        "account_correction": V4_CORRECTION,
        "source": {
            "status": source.get("status"),
            "event_count": source.get("event_count"),
            "month_count": len(source.get("months_with_events", [])),
            "tokens": source.get("distinct_tokens"),
            "source_schema_id": source.get("source_schema_id"),
            "source_correction_id": source.get("source_correction_id"),
            "transport_response_policy_correction": source.get(
                "transport_response_policy_correction"
            ),
        },
        "economic": (
            {
                "status": economic.get("status"),
                "engine": economic.get("engine"),
                "development_gate": economic.get("development_gate", {}).get("all"),
                "selected_risk_path": economic.get("risk_search", {}).get("selected")
                if economic.get("risk_search")
                else None,
                "official_2024h1_opened": economic.get("official_2024h1_opened"),
                "orders_submitted": economic.get("orders_submitted"),
            }
            if economic
            else {"status": "NOT_OPENED"}
        ),
        "next_stage": next_stage,
        "official_2024h1_opened": False,
        "orders_submitted": False,
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return summary


def refresh_hashes() -> None:
    rows: list[str] = []
    for path in sorted(
        item
        for item in RUN_ROOT.rglob("*")
        if item.is_file() and item.name != "SHA256SUMS.txt"
    ):
        rows.append(f"{sha256_file(path)}  {path.relative_to(RUN_ROOT).as_posix()}\n")
    (RUN_ROOT / "SHA256SUMS.txt").write_text("".join(rows), encoding="utf-8")


def run() -> int:
    shutil.rmtree(RUN_ROOT, ignore_errors=True)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    print("STABLECOIN_STRICT_V4_MACOS_BEGIN")
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
        V4_ROOT / "CORRECTION_004_SIMULTANEOUS_EVENT_AND_LIQUIDATION_DISTANCE_BEFORE_OUTCOME.json",
    ):
        assert_json_file(path)

    execute([sys.executable, str(ECON_ROOT / "reconstruct.py")])
    execute(
        [sys.executable, "-m", "pytest", "-q", str(SOURCE_ROOT / "test_source_gate.py")],
        python_paths=[SOURCE_ROOT],
    )
    execute(
        [sys.executable, str(SOURCE_ROOT / "run_pinned_snapshot_source.py"), "--self-test"],
        python_paths=[SOURCE_ROOT],
    )
    execute(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(ECON_ROOT / "test_run.py"),
            str(ECON_ROOT / "test_run_causal.py"),
            str(GUARD_ROOT / "test_causal_guard.py"),
        ],
        python_paths=[ECON_ROOT, GUARD_ROOT, V4_ROOT],
    )
    execute(
        [sys.executable, str(V4_ROOT / "strict_guard_v4.py"), "self-test"],
        python_paths=[ECON_ROOT, GUARD_ROOT, V4_ROOT],
    )
    execute([sys.executable, str(REPO_ROOT / "scripts" / "validate_project.py")])

    SOURCE_OUT.mkdir(parents=True, exist_ok=True)
    source_code = execute(
        [
            sys.executable,
            str(SOURCE_ROOT / "run_pinned_snapshot_source.py"),
            "--output",
            str(SOURCE_OUT),
        ],
        python_paths=[SOURCE_ROOT],
        expected={0, 2},
    )
    (SOURCE_OUT / "RUN_EXIT_CODE.txt").write_text(str(source_code) + "\n", encoding="utf-8")
    if not (SOURCE_OUT / "SOURCE_GATE_RESULT.json").is_file():
        execute(
            [
                sys.executable,
                str(SOURCE_ROOT / "write_transport_failure.py"),
                "--output",
                str(SOURCE_OUT),
                "--transport",
                "TRANSPORT-20260727-ML-STABLECOIN-STRICT-V4-MACOS",
                "--exit-code",
                str(source_code),
            ],
            python_paths=[SOURCE_ROOT],
        )
    source, events = verify_source()

    economic: dict[str, Any] | None = None
    if events is not None:
        ECON_OUT.mkdir(parents=True, exist_ok=True)
        MARKET_CACHE.mkdir(parents=True, exist_ok=True)
        economic_code = execute(
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
            python_paths=[ECON_ROOT, GUARD_ROOT, V4_ROOT],
            expected={0, 2},
        )
        (ECON_OUT / "RUN_EXIT_CODE.txt").write_text(
            str(economic_code) + "\n", encoding="utf-8"
        )
        economic, _ = verify_economic()

    summary = write_summary(source, economic)
    refresh_hashes()
    print("STABLECOIN_STRICT_V4_DECISION", json.dumps(summary, sort_keys=True))
    print("STABLECOIN_STRICT_V4_MACOS_END")
    return 0


def self_test() -> int:
    assert SOURCE_SHA.startswith("73aac90")
    assert STRICT_SHA.startswith("209a0f")
    assert V4_CORRECTION.endswith("004")
    print("STABLECOIN_STRICT_V4_MACOS_RUNNER_SELF_TEST_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "self-test"))
    args = parser.parse_args()
    return self_test() if args.command == "self-test" else run()


if __name__ == "__main__":
    raise SystemExit(main())
