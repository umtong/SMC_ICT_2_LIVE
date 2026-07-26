from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

import run_stablecoin_profit_v5_authority as v5auth

v4auth = v5auth.v4auth
ROOT = Path(__file__).resolve().parents[1]
CLAIM_ID = v5auth.CLAIM_ID
RESULT_ID = v5auth.RESULT_ID
PROFIT_CORRECTION = v5auth.PROFIT_CORRECTION
PROFIT_ROOT = ROOT / "research" / "execution" / "stablecoin_profit_v5_20260727"
PROFIT_ENTRY = PROFIT_ROOT / "profit_guard_v5_frozen_grid.py"


def execute(work_dir: Path, publish_dir: Path) -> int:
    checkout_sha = v4auth.git("rev-parse", "HEAD")
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
    economic_out = work_dir / "economic_profit_v5"
    market_cache = work_dir / "market"
    source_out.mkdir(parents=True, exist_ok=True)
    economic_out.mkdir(parents=True, exist_ok=True)
    market_cache.mkdir(parents=True, exist_ok=True)

    v4auth.materialize(
        v4auth.SOURCE_SHA,
        ["research/ml_stablecoin_issuance_20260726"],
        repository,
    )
    v4auth.materialize(
        v4auth.STRICT_SHA,
        [
            "research/ml_stablecoin_issuance_economic_20260726",
            "sourcefix/ml_stablecoin_causal_guard_20260726",
        ],
        repository,
    )

    required_json = (
        source_root / "CORRECTION_010_USDT_ISSUE_REDEEM_EVENT_SCHEMA_BEFORE_OUTCOME.json",
        source_root / "CORRECTION_011_BLOCKSCOUT_NULL_TOPIC_PADDING_BEFORE_OUTCOME.json",
        source_root / "CORRECTION_013_BIND_CORRECTED_SOURCE_SCHEMA_BEFORE_OUTCOME.json",
        source_root / "CORRECTION_019_BLOCKSCOUT_STATUS0_FAIL_CLOSED_BEFORE_OUTCOME.json",
        guard_root / "CORRECTION_002_PREENTRY_INFORMATION_BOUNDARY_BEFORE_OUTCOME.json",
        v4_root / "CORRECTION_004_SIMULTANEOUS_EVENT_AND_LIQUIDATION_DISTANCE_BEFORE_OUTCOME.json",
        PROFIT_ROOT / "CORRECTION_005_PROFIT_FIRST_ADVANCEMENT_BEFORE_OUTCOME.json",
    )
    for path in required_json:
        v4auth.run([sys.executable, "-m", "json.tool", str(path)])

    v4auth.run([sys.executable, str(base_root / "reconstruct.py")])
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
        PROFIT_ROOT / "profit_guard_v5.py",
        PROFIT_ENTRY,
    ]
    v4auth.run(
        [sys.executable, "-m", "py_compile", *[str(path) for path in compile_paths]]
    )
    source_env = {"PYTHONPATH": str(source_root)}
    economic_env = {
        "PYTHONPATH": os.pathsep.join(
            [str(base_root), str(guard_root), str(v4_root), str(PROFIT_ROOT)]
        )
    }
    v4auth.run(
        [sys.executable, "-m", "pytest", "-q", str(source_root / "test_source_gate.py")],
        env=source_env,
        log=work_dir / "SOURCE_PYTEST.log",
    )
    v4auth.run(
        [sys.executable, str(source_root / "run_pinned_snapshot_source.py"), "--self-test"],
        env=source_env,
        log=work_dir / "SOURCE_SELF_TEST.log",
    )
    v4auth.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(base_root / "test_run.py"),
            str(base_root / "test_run_causal.py"),
            str(guard_root / "test_causal_guard.py"),
        ],
        env=economic_env,
        log=work_dir / "STRICT_TESTS.log",
    )
    v4auth.run(
        [sys.executable, str(PROFIT_ENTRY), "self-test"],
        env=economic_env,
        log=work_dir / "PROFIT_FIRST_V5_SELF_TEST.log",
    )
    v4auth.run(
        [sys.executable, str(ROOT / "scripts" / "validate_project.py")],
        log=work_dir / "PROJECT_VALIDATION.log",
    )

    source_process = v4auth.run(
        [
            sys.executable,
            str(source_root / "run_pinned_snapshot_source.py"),
            "--output",
            str(source_out),
        ],
        env=source_env,
        check=False,
        log=source_out / "RUN.log",
    )
    (source_out / "RUN_EXIT_CODE.txt").write_text(
        f"{source_process.returncode}\n", encoding="utf-8"
    )
    if not (source_out / "SOURCE_GATE_RESULT.json").exists():
        v4auth.run(
            [
                sys.executable,
                str(source_root / "write_transport_failure.py"),
                "--output",
                str(source_out),
                "--transport",
                "TRANSPORT-20260727-ML-STABLECOIN-PROFIT-FIRST-V5-SINGLE-PASS",
                "--exit-code",
                str(source_process.returncode),
            ],
            env=source_env,
        )
    source, authorized = v4auth.validate_source(source_out)

    result: dict[str, Any] | None = None
    if authorized:
        economic_process = v4auth.run(
            [
                sys.executable,
                str(PROFIT_ENTRY),
                "run",
                "--events",
                str(source_out / "EVENTS.jsonl"),
                "--market-cache",
                str(market_cache),
                "--output",
                str(economic_out),
            ],
            env=economic_env,
            check=False,
            log=economic_out / "RUN.log",
        )
        (economic_out / "RUN_EXIT_CODE.txt").write_text(
            f"{economic_process.returncode}\n", encoding="utf-8"
        )
        if economic_process.returncode not in {0, 2}:
            raise RuntimeError(
                f"profit-first V5 economic process failed: {economic_process.returncode}"
            )
        result, _ = v5auth.validate_profit_result(economic_out)

    v4auth.copy_if_exists(
        source_out / "SOURCE_GATE_RESULT.json",
        publish_dir / "SOURCE_GATE_RESULT.json",
    )
    v4auth.copy_if_exists(
        source_out / "SOURCE_MANIFEST.json",
        publish_dir / "SOURCE_MANIFEST.json",
    )
    v4auth.copy_if_exists(
        source_out / "OUTPUT_SHA256SUMS.txt",
        publish_dir / "SOURCE_OUTPUT_SHA256SUMS.txt",
    )

    if result is None:
        decision = {
            "schema_version": 1,
            "result_id": RESULT_ID,
            "claim_id": CLAIM_ID,
            "status": source["status"],
            "hard_validity_status": "PASS_OUTCOME_SEALED_SOURCE_DECISION",
            "economic_status": "NOT_OPENED",
            "ranking_role": "NONE_SOURCE_DECISION",
            "source": {
                "status": source["status"],
                "event_count": source.get("event_count"),
                "event_bearing_months": len(source.get("months_with_events", [])),
                "tokens": source.get("distinct_tokens"),
                "source_schema_id": source.get("source_schema_id"),
                "source_correction_id": source.get("source_correction_id"),
                "transport_response_policy_correction": source.get(
                    "transport_response_policy_correction"
                ),
            },
            "economic": None,
            "source_sha": v4auth.SOURCE_SHA,
            "strict_sha": v4auth.STRICT_SHA,
            "profit_first_correction_id": PROFIT_CORRECTION,
            "execution_checkout_sha": checkout_sha,
            "next_action": (
                "CHANGE_ALPHA"
                if source["status"] == "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE"
                else "CLOSE_SOURCE_OR_REPAIR_TRANSPORT_ONLY"
            ),
            "official_2024h1_authorized": False,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
            "paper_live_started": False,
        }
    else:
        for name in (
            "RESULT.json",
            "FULL_RESULT.json",
            "MODEL_CONTRACT.json",
            "SHA256SUMS.txt",
            "CORRECTION_005_PROFIT_FIRST_ADVANCEMENT_BEFORE_OUTCOME.json",
        ):
            source_path = (
                PROFIT_ROOT / name
                if name == "CORRECTION_005_PROFIT_FIRST_ADVANCEMENT_BEFORE_OUTCOME.json"
                else economic_out / name
            )
            destination_name = (
                "PROFIT_V5_ECONOMIC_SHA256SUMS.txt"
                if name == "SHA256SUMS.txt"
                else name
            )
            v4auth.copy_if_exists(source_path, publish_dir / destination_name)
        decision = v5auth.build_profit_decision(
            source=source,
            result=result,
            checkout_sha=checkout_sha,
            source_out=source_out,
            economic_out=economic_out,
            strict_v4_decision=None,
            strict_v4_execution_error=None,
        )

    v4auth.write_json(publish_dir / "DECISION.json", decision)
    v4auth.write_json(
        publish_dir / "VALIDATION_ATTESTATION.json",
        {
            "schema_version": 1,
            "claim_id": CLAIM_ID,
            "source_sha": v4auth.SOURCE_SHA,
            "strict_sha": v4auth.STRICT_SHA,
            "execution_checkout_sha": checkout_sha,
            "profit_first_correction_id": PROFIT_CORRECTION,
            "registered_risk_grid_size": 99,
            "single_source_execution": True,
            "single_economic_execution": result is not None,
            "source_authorized_economic_stage": authorized,
            "profit_first_v5_result_present": result is not None,
            "source_outcome_seal_passed": True,
            "strict_v4_profit_first_validation_passed": result is not None or not authorized,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        },
    )
    v4auth.freeze_hashes(publish_dir)
    v4auth.freeze_hashes(work_dir)
    print("STABLECOIN_PROFIT_V5_SINGLE_PASS_DECISION_BEGIN")
    print(v4auth.stable_json(decision))
    print("STABLECOIN_PROFIT_V5_SINGLE_PASS_DECISION_END")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--publish-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        return execute(args.work_dir.resolve(), args.publish_dir.resolve())
    except Exception as error:
        args.publish_dir.mkdir(parents=True, exist_ok=True)
        failure = {
            "schema_version": 1,
            "claim_id": CLAIM_ID,
            "status": "EXECUTION_FAILURE_NOT_SCIENTIFIC_RESULT",
            "error_type": type(error).__name__,
            "error": repr(error),
            "traceback": traceback.format_exc(),
            "source_sha": v4auth.SOURCE_SHA,
            "strict_sha": v4auth.STRICT_SHA,
            "profit_first_correction_id": PROFIT_CORRECTION,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        }
        v4auth.write_json(publish_dir / "EXECUTION_FAILURE.json", failure)
        v4auth.freeze_hashes(publish_dir)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
