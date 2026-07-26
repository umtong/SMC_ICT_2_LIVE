from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "73aac90eacdc0ddcc34f4e45f0ff8d9369e5b539"
STRICT_SHA = "209a0fbe6e2f61d2c58b3eb7910b8c0c139cd46c"
CLAIM_ID = "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
SOURCE_SCHEMA = "STABLECOIN_SUPPLY_USDT_ISSUE_REDEEM_USDC_ZERO_TRANSFER_V1"
SOURCE_CORRECTION = "CORRECTION-20260726-ML-STABLECOIN-USDT-ISSUE-REDEEM-010"
TRANSPORT_CORRECTION = "CORRECTION-20260727-ML-STABLECOIN-BLOCKSCOUT-STATUS0-FAIL-CLOSED-019"
STRICT_CORRECTION = "CORRECTION-20260727-ML-STABLECOIN-PREENTRY-INFORMATION-BOUNDARY-002"
V4_CORRECTION = "CORRECTION-20260727-ML-STABLECOIN-SIMULTANEOUS-EVENT-LIQUIDATION-DISTANCE-004"


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    log: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if env:
        environment.update(env)
    print("STABLECOIN_V4_AUTHORITY_COMMAND", stable_json(command), flush=True)
    if log is None:
        return subprocess.run(command, cwd=ROOT, env=environment, text=True, check=check)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            handle.write(line)
        return_code = process.wait()
    completed = subprocess.CompletedProcess(command, return_code)
    if check and return_code:
        raise subprocess.CalledProcessError(return_code, command)
    return completed


def materialize(commit: str, paths: list[str], destination: Path) -> None:
    run(["git", "fetch", "--no-tags", "--depth=1", "origin", commit])
    observed = git("rev-parse", "FETCH_HEAD")
    if observed != commit:
        raise RuntimeError(f"fetched {observed}, expected {commit}")
    archive = subprocess.Popen(
        ["git", "archive", commit, *paths],
        cwd=ROOT,
        stdout=subprocess.PIPE,
    )
    assert archive.stdout is not None
    destination.mkdir(parents=True, exist_ok=True)
    extract = subprocess.run(["tar", "-x", "-C", str(destination)], stdin=archive.stdout, check=True)
    archive.stdout.close()
    archive_code = archive.wait()
    if archive_code != 0 or extract.returncode != 0:
        raise RuntimeError(f"git archive failed: archive={archive_code}, extract={extract.returncode}")


def copy_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def validate_source(source_out: Path) -> tuple[dict[str, Any], bool]:
    result_path = source_out / "SOURCE_GATE_RESULT.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result["claim_id"] != CLAIM_ID:
        raise AssertionError(result["claim_id"])
    if result["status"] not in {
        "PASS",
        "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE",
        "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE",
    }:
        raise AssertionError(result["status"])
    for key in (
        "market_outcome_opened",
        "model_fit",
        "trade_or_pnl_opened",
        "official_2024_2026_opened",
        "orders_submitted",
    ):
        if result[key] is not False:
            raise AssertionError(f"source outcome seal failed: {key}={result[key]!r}")
    if result["status"] != "PASS":
        return result, False

    manifest = json.loads((source_out / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    events_path = source_out / "EVENTS.jsonl"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if result.get("source_schema_id") != SOURCE_SCHEMA or manifest.get("source_schema_id") != SOURCE_SCHEMA:
        raise AssertionError("source schema mismatch")
    if result.get("source_correction_id") != SOURCE_CORRECTION or manifest.get("source_correction_id") != SOURCE_CORRECTION:
        raise AssertionError("source correction mismatch")
    if result.get("transport_response_policy_correction") != TRANSPORT_CORRECTION:
        raise AssertionError("transport correction mismatch")
    if manifest.get("transport_response_policy_correction") != TRANSPORT_CORRECTION:
        raise AssertionError("manifest transport correction mismatch")
    if result.get("status_zero_empty_policy") != "EXPLICIT_NO_RECORDS_ONLY":
        raise AssertionError("status-zero empty policy mismatch")
    if result.get("status_zero_range_policy") != "EXPLICIT_RANGE_LIMIT_ONLY":
        raise AssertionError("status-zero range policy mismatch")
    if result.get("unrecognized_status_zero_policy") != "FAIL_CLOSED_SOURCE_UNAVAILABLE":
        raise AssertionError("status-zero fail-closed policy mismatch")
    checks = result.get("pass_checks", {})
    if not checks or not all(value is True for value in checks.values()):
        raise AssertionError(f"source pass checks failed: {checks}")
    if result.get("event_semantics", {}).get("ordinary_usdt_transfer_excluded") is not True:
        raise AssertionError("ordinary USDT transfers were not excluded")
    if int(result["event_count"]) < 120 or len(result["months_with_events"]) < 24:
        raise AssertionError("source density below frozen gate despite PASS")
    if sorted(result["distinct_tokens"]) != ["USDC", "USDT"]:
        raise AssertionError(result["distinct_tokens"])
    if {row["token"] for row in rows} != {"USDC", "USDT"}:
        raise AssertionError("event token population mismatch")
    if not {row["direction"] for row in rows}.issubset({"MINT", "BURN"}):
        raise AssertionError("invalid source direction")
    if not all(int(row["block_timestamp"]) < 1_704_067_200 for row in rows):
        raise AssertionError("2024+ block timestamp leaked")
    if not all(int(row["available_timestamp_12"]) < 1_704_067_200 for row in rows):
        raise AssertionError("2024+ 12-block availability leaked")
    if not all(int(row["available_timestamp_64"]) < 1_704_067_200 for row in rows):
        raise AssertionError("2024+ 64-block availability leaked")
    if sha256_file(events_path) != manifest["events_sha256"]:
        raise AssertionError("event file hash mismatch")
    return result, True


def validate_economic(economic_out: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    result = json.loads((economic_out / "RESULT.json").read_text(encoding="utf-8"))
    full = json.loads((economic_out / "FULL_RESULT.json").read_text(encoding="utf-8"))
    if result["claim_id"] != CLAIM_ID:
        raise AssertionError(result["claim_id"])
    if result["engine"] != "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_STRICT_CAUSAL_V3":
        raise AssertionError(result["engine"])
    if result["status"] not in {"PRE2024_BELOW_GATE", "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"}:
        raise AssertionError(result["status"])
    if result["orders_submitted"] is not False:
        raise AssertionError("orders submitted")
    if result["official_2024h1_opened"] is not False or result["official_2024_2026_opened"] is not False:
        raise AssertionError("official period opened inside pre-2024 screen")

    strict = result["strict_causal_guard"]
    expected_strict = {
        "correction_id": STRICT_CORRECTION,
        "source_decision_second_respected": True,
        "latest_completed_bar_cutoff_enforced": True,
        "decision_reference_price_pre_entry": True,
        "future_entry_open_used_for_model_or_action": False,
        "entry_open_used_for_realized_execution_only": True,
        "stage_boundary_positions_marked_not_closed": True,
        "fatal_validity_violation": False,
    }
    for key, expected in expected_strict.items():
        if strict.get(key) != expected:
            raise AssertionError(f"strict guard {key}: {strict.get(key)!r} != {expected!r}")

    v4 = result["simultaneous_event_and_liquidation_guard"]
    expected_v4 = {
        "correction_id": V4_CORRECTION,
        "simultaneous_event_prior_rule": "STRICTLY_EARLIER_AVAILABILITY_SECOND_GROUPED_BEFORE_APPEND",
        "planned_quantity_rule": "PREENTRY_EXPECTED_STOP_DISTANCE_PLUS_COST",
        "liquidation_test_rule": "ACTUAL_FILL_TO_STRUCTURAL_STOP_OR_ADVERSE_STOP_GAP",
        "entry_gap_cost_only_liquidation_distance": 0.0,
        "fatal_validity_violation": False,
    }
    for key, expected in expected_v4.items():
        if v4.get(key) != expected:
            raise AssertionError(f"V4 guard {key}: {v4.get(key)!r} != {expected!r}")

    serialized = json.dumps(full, sort_keys=True)
    if '"exit_reason": "SOURCE_BOUNDARY"' in serialized:
        raise AssertionError("synthetic source-boundary exit present")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "forced_boundary_close" in value and value["forced_boundary_close"] is not False:
                raise AssertionError("forced boundary close present")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(full)
    if result["status"] == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1":
        if result["development_gate"]["all"] is not True:
            raise AssertionError("survivor lacks development gate")
        selected = result["risk_search"]["selected"]
        if selected is None or selected["growth"] <= 0 or selected["liquidation"] is not False:
            raise AssertionError(f"invalid survivor risk path: {selected}")
    return result, full


def build_decision(
    *,
    source: dict[str, Any],
    economic: dict[str, Any] | None,
    checkout_sha: str,
    source_out: Path,
    economic_out: Path,
) -> dict[str, Any]:
    source_status = source["status"]
    next_action = "CLOSE_SOURCE_OR_REPAIR_TRANSPORT_ONLY"
    if source_status == "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE":
        next_action = "CHANGE_ALPHA"
    if economic is not None:
        next_action = (
            "OFFICIAL_2024H1_IMMEDIATELY"
            if economic["status"] == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
            else "CHANGE_ALPHA"
        )
    return {
        "schema_version": 1,
        "result_id": "RES-20260727-ML-STABLECOIN-STRICT-V4-001",
        "claim_id": CLAIM_ID,
        "status": economic["status"] if economic is not None else source_status,
        "hard_validity_status": "PASS_STRICT_V4" if economic is not None else "PASS_OUTCOME_SEALED_SOURCE_DECISION",
        "economic_status": economic["status"] if economic is not None else "NOT_OPENED",
        "ranking_role": "NONE_PRE2024_DECISION" if economic is not None else "NONE_SOURCE_DECISION",
        "source": {
            "status": source_status,
            "event_count": source.get("event_count"),
            "event_bearing_months": len(source.get("months_with_events", [])),
            "tokens": source.get("distinct_tokens"),
            "source_schema_id": source.get("source_schema_id"),
            "source_correction_id": source.get("source_correction_id"),
            "transport_response_policy_correction": source.get("transport_response_policy_correction"),
            "source_result_sha256": sha256_file(source_out / "SOURCE_GATE_RESULT.json"),
            "source_manifest_sha256": sha256_file(source_out / "SOURCE_MANIFEST.json") if (source_out / "SOURCE_MANIFEST.json").exists() else None,
        },
        "economic": (
            {
                "status": economic["status"],
                "engine": economic["engine"],
                "development_gate": economic.get("development_gate"),
                "risk_search": economic.get("risk_search"),
                "strict_causal_guard": economic.get("strict_causal_guard"),
                "simultaneous_event_and_liquidation_guard": economic.get("simultaneous_event_and_liquidation_guard"),
                "result_sha256": sha256_file(economic_out / "RESULT.json"),
                "full_result_sha256": sha256_file(economic_out / "FULL_RESULT.json"),
            }
            if economic is not None
            else None
        ),
        "source_sha": SOURCE_SHA,
        "strict_sha": STRICT_SHA,
        "execution_checkout_sha": checkout_sha,
        "next_action": next_action,
        "official_2024h1_authorized": next_action == "OFFICIAL_2024H1_IMMEDIATELY",
        "official_2024_2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
    }


def freeze_hashes(root: Path) -> None:
    rows: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "OUTPUT_SHA256SUMS.txt"):
        rows.append(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}\n")
    (root / "OUTPUT_SHA256SUMS.txt").write_text("".join(rows), encoding="utf-8")


def execute(work_dir: Path, publish_dir: Path) -> int:
    checkout_sha = git("rev-parse", "HEAD")
    shutil.rmtree(work_dir, ignore_errors=True)
    shutil.rmtree(publish_dir, ignore_errors=True)
    repository = work_dir / "repository"
    repository.mkdir(parents=True, exist_ok=True)
    publish_dir.mkdir(parents=True, exist_ok=True)

    source_root = repository / "research" / "ml_stablecoin_issuance_20260726"
    base_root = repository / "research" / "ml_stablecoin_issuance_economic_20260726"
    guard_root = repository / "sourcefix" / "ml_stablecoin_causal_guard_20260726"
    v4_root = ROOT / "research" / "execution" / "stablecoin_strict_v4_20260727"
    source_out = work_dir / "source"
    economic_out = work_dir / "economic"
    market_cache = work_dir / "market"
    source_out.mkdir(parents=True, exist_ok=True)
    economic_out.mkdir(parents=True, exist_ok=True)
    market_cache.mkdir(parents=True, exist_ok=True)

    materialize(SOURCE_SHA, ["research/ml_stablecoin_issuance_20260726"], repository)
    materialize(
        STRICT_SHA,
        ["research/ml_stablecoin_issuance_economic_20260726", "sourcefix/ml_stablecoin_causal_guard_20260726"],
        repository,
    )

    for path in (
        source_root / "CORRECTION_010_USDT_ISSUE_REDEEM_EVENT_SCHEMA_BEFORE_OUTCOME.json",
        source_root / "CORRECTION_011_BLOCKSCOUT_NULL_TOPIC_PADDING_BEFORE_OUTCOME.json",
        source_root / "CORRECTION_013_BIND_CORRECTED_SOURCE_SCHEMA_BEFORE_OUTCOME.json",
        source_root / "CORRECTION_019_BLOCKSCOUT_STATUS0_FAIL_CLOSED_BEFORE_OUTCOME.json",
        guard_root / "CORRECTION_002_PREENTRY_INFORMATION_BOUNDARY_BEFORE_OUTCOME.json",
        v4_root / "CORRECTION_004_SIMULTANEOUS_EVENT_AND_LIQUIDATION_DISTANCE_BEFORE_OUTCOME.json",
    ):
        run([sys.executable, "-m", "json.tool", str(path)])

    run([sys.executable, str(base_root / "reconstruct.py")])
    compile_paths = [
        *source_root.glob("source_gate*.py"),
        source_root / "run_pinned_snapshot_source.py",
        source_root / "test_source_gate.py",
        source_root / "write_transport_failure.py",
        base_root / "run.py",
        base_root / "run_causal.py",
        base_root / "test_run.py",
        base_root / "test_run_causal.py",
        guard_root / "causal_guard.py",
        guard_root / "strict_guard.py",
        guard_root / "test_causal_guard.py",
        v4_root / "strict_guard_v4.py",
    ]
    run([sys.executable, "-m", "py_compile", *[str(path) for path in compile_paths]])
    source_env = {"PYTHONPATH": str(source_root)}
    strict_env = {"PYTHONPATH": os.pathsep.join([str(base_root), str(guard_root), str(v4_root)])}
    run([sys.executable, "-m", "pytest", "-q", str(source_root / "test_source_gate.py")], env=source_env, log=work_dir / "SOURCE_PYTEST.log")
    run([sys.executable, str(source_root / "run_pinned_snapshot_source.py"), "--self-test"], env=source_env, log=work_dir / "SOURCE_SELF_TEST.log")
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(base_root / "test_run.py"),
            str(base_root / "test_run_causal.py"),
            str(guard_root / "test_causal_guard.py"),
        ],
        env=strict_env,
        log=work_dir / "STRICT_TESTS.log",
    )
    run([sys.executable, str(v4_root / "strict_guard_v4.py"), "self-test"], env=strict_env, log=work_dir / "STRICT_V4_SELF_TEST.log")
    run([sys.executable, str(ROOT / "scripts" / "validate_project.py")], log=work_dir / "PROJECT_VALIDATION.log")

    source_process = run(
        [sys.executable, str(source_root / "run_pinned_snapshot_source.py"), "--output", str(source_out)],
        env=source_env,
        check=False,
        log=source_out / "RUN.log",
    )
    (source_out / "RUN_EXIT_CODE.txt").write_text(f"{source_process.returncode}\n", encoding="utf-8")
    if not (source_out / "SOURCE_GATE_RESULT.json").exists():
        run(
            [
                sys.executable,
                str(source_root / "write_transport_failure.py"),
                "--output",
                str(source_out),
                "--transport",
                "TRANSPORT-20260727-ML-STABLECOIN-STRICT-V4-BRANCH-PUSH",
                "--exit-code",
                str(source_process.returncode),
            ],
            env=source_env,
        )
    source, authorized = validate_source(source_out)
    economic: dict[str, Any] | None = None
    if authorized:
        economic_process = run(
            [
                sys.executable,
                str(v4_root / "strict_guard_v4.py"),
                "run",
                "--events",
                str(source_out / "EVENTS.jsonl"),
                "--market-cache",
                str(market_cache),
                "--output",
                str(economic_out),
            ],
            env=strict_env,
            check=False,
            log=economic_out / "RUN.log",
        )
        (economic_out / "RUN_EXIT_CODE.txt").write_text(f"{economic_process.returncode}\n", encoding="utf-8")
        if economic_process.returncode not in {0, 2}:
            raise RuntimeError(f"strict V4 economic process failed: {economic_process.returncode}")
        economic, _ = validate_economic(economic_out)

    copy_if_exists(source_out / "SOURCE_GATE_RESULT.json", publish_dir / "SOURCE_GATE_RESULT.json")
    copy_if_exists(source_out / "SOURCE_MANIFEST.json", publish_dir / "SOURCE_MANIFEST.json")
    copy_if_exists(source_out / "OUTPUT_SHA256SUMS.txt", publish_dir / "SOURCE_OUTPUT_SHA256SUMS.txt")
    if economic is not None:
        copy_if_exists(economic_out / "RESULT.json", publish_dir / "RESULT.json")
        copy_if_exists(economic_out / "MODEL_CONTRACT.json", publish_dir / "MODEL_CONTRACT.json")
        copy_if_exists(economic_out / "OUTPUT_SHA256SUMS.txt", publish_dir / "ECONOMIC_OUTPUT_SHA256SUMS.txt")

    decision = build_decision(
        source=source,
        economic=economic,
        checkout_sha=checkout_sha,
        source_out=source_out,
        economic_out=economic_out,
    )
    write_json(publish_dir / "DECISION.json", decision)
    write_json(
        publish_dir / "VALIDATION_ATTESTATION.json",
        {
            "schema_version": 1,
            "claim_id": CLAIM_ID,
            "source_sha": SOURCE_SHA,
            "strict_sha": STRICT_SHA,
            "checkout_sha": checkout_sha,
            "source_authorized_economic_stage": authorized,
            "strict_v4_economic_result_present": economic is not None,
            "source_outcome_seal_passed": True,
            "strict_v4_validation_passed": economic is not None or not authorized,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        },
    )
    freeze_hashes(publish_dir)
    freeze_hashes(work_dir)
    print("STABLECOIN_STRICT_V4_DECISION_BEGIN")
    print(stable_json(decision))
    print("STABLECOIN_STRICT_V4_DECISION_END")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--publish-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        return execute(args.work_dir.resolve(), args.publish_dir.resolve())
    except Exception as exc:
        args.publish_dir.mkdir(parents=True, exist_ok=True)
        failure = {
            "schema_version": 1,
            "claim_id": CLAIM_ID,
            "status": "EXECUTION_FAILURE_NOT_SCIENTIFIC_RESULT",
            "error_type": type(exc).__name__,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "source_sha": SOURCE_SHA,
            "strict_sha": STRICT_SHA,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        }
        write_json(args.publish_dir / "EXECUTION_FAILURE.json", failure)
        freeze_hashes(args.publish_dir)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
