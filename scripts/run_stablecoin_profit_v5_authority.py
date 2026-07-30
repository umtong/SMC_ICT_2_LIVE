from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

import run_stablecoin_strict_v4_authority as v4auth

ROOT = Path(__file__).resolve().parents[1]
CLAIM_ID = v4auth.CLAIM_ID
ENGINE = "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_PROFIT_FIRST_V5"
PROFIT_CORRECTION = "CORRECTION-20260727-ML-STABLECOIN-PROFIT-FIRST-ADVANCEMENT-005"
RESULT_ID = "RES-20260727-ML-STABLECOIN-PROFIT-FIRST-V5-001"


def validate_profit_result(
    economic_out: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = json.loads(
        (economic_out / "RESULT.json").read_text(encoding="utf-8")
    )
    full = json.loads(
        (economic_out / "FULL_RESULT.json").read_text(encoding="utf-8")
    )
    if result["claim_id"] != CLAIM_ID:
        raise AssertionError(result["claim_id"])
    if result["engine"] != ENGINE:
        raise AssertionError(result["engine"])
    if result["status"] not in {
        "PRE2024_MODEL_POPULATION_FAILURE",
        "PRE2024_BELOW_GATE",
        "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1",
    }:
        raise AssertionError(result["status"])
    for key in (
        "official_2024h1_opened",
        "official_2024_2026_opened",
        "orders_submitted",
    ):
        if result.get(key) is not False:
            raise AssertionError(f"{key}={result.get(key)!r}")

    strict = result["strict_causal_guard"]
    if (
        strict.get("correction_id") != v4auth.STRICT_CORRECTION
        or strict.get("fatal_validity_violation") is not False
    ):
        raise AssertionError(strict)
    v4 = result["simultaneous_event_and_liquidation_guard"]
    if (
        v4.get("correction_id") != v4auth.V4_CORRECTION
        or v4.get("fatal_validity_violation") is not False
    ):
        raise AssertionError(v4)
    profit = result["profit_first_advancement_guard"]
    if profit.get("correction_id") != PROFIT_CORRECTION:
        raise AssertionError(profit)
    if profit.get("confirmation_opens_calendar_2023") is not True:
        raise AssertionError(profit)
    if profit.get("winner_removal_is_diagnostic_and_tiebreak_only") is not True:
        raise AssertionError(profit)
    if profit.get("fatal_validity_violation") is not False:
        raise AssertionError(profit)

    serialized = json.dumps(full, sort_keys=True)
    if '"exit_reason": "SOURCE_BOUNDARY"' in serialized:
        raise AssertionError("synthetic source-boundary exit present")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("forced_boundary_close") is True:
                raise AssertionError("forced boundary close present")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(full)
    search = result.get("risk_search")
    if search is not None and int(search["candidate_count"]) != 99:
        raise AssertionError(
            f"risk/notional grid changed: {search['candidate_count']} != 99"
        )
    if result["status"] == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1":
        gate = result["development_gate"]
        if gate.get("all") is not True:
            raise AssertionError(gate)
        selected = result["risk_search"]["selected"]
        if selected is None:
            raise AssertionError("survivor has no selected risk path")
        if (
            float(selected["growth"]) <= 0.0
            or selected["liquidation"] is not False
        ):
            raise AssertionError(selected)
    return result, full


def primary_development_metrics(
    result: dict[str, Any],
) -> dict[str, Any] | None:
    development = result.get("development")
    if not isinstance(development, dict):
        return None
    return development.get("costs", {}).get("24")


def build_profit_decision(
    *,
    source: dict[str, Any],
    result: dict[str, Any],
    checkout_sha: str,
    source_out: Path,
    economic_out: Path,
    strict_v4_decision: dict[str, Any] | None,
    strict_v4_execution_error: str | None,
) -> dict[str, Any]:
    survivor = (
        result["status"]
        == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
    )
    primary = primary_development_metrics(result)
    selected = (result.get("risk_search") or {}).get("selected")
    return {
        "schema_version": 1,
        "result_id": RESULT_ID,
        "claim_id": CLAIM_ID,
        "status": result["status"],
        "hard_validity_status": "PASS_STRICT_V4_PROFIT_FIRST_V5",
        "economic_status": result["status"],
        "ranking_role": "NONE_PRE2024_DECISION",
        "source": {
            "status": source["status"],
            "event_count": source.get("event_count"),
            "event_bearing_months": len(
                source.get("months_with_events", [])
            ),
            "tokens": source.get("distinct_tokens"),
            "source_schema_id": source.get("source_schema_id"),
            "source_correction_id": source.get("source_correction_id"),
            "transport_response_policy_correction": source.get(
                "transport_response_policy_correction"
            ),
            "source_result_sha256": v4auth.sha256_file(
                source_out / "SOURCE_GATE_RESULT.json"
            ),
            "source_manifest_sha256": (
                v4auth.sha256_file(source_out / "SOURCE_MANIFEST.json")
                if (source_out / "SOURCE_MANIFEST.json").exists()
                else None
            ),
        },
        "economic": {
            "engine": result["engine"],
            "profit_first_correction_id": PROFIT_CORRECTION,
            "risk_notional_grid_candidate_count": (
                result.get("risk_search") or {}
            ).get("candidate_count"),
            "confirmation_diagnostics_not_gate": result.get(
                "confirmation_diagnostics_not_gate"
            ),
            "development_diagnostics_not_gate": result.get(
                "development_diagnostics_not_gate"
            ),
            "development_gate": result.get("development_gate"),
            "development_24bps": primary,
            "risk_search": result.get("risk_search"),
            "strict_causal_guard": result.get("strict_causal_guard"),
            "simultaneous_event_and_liquidation_guard": result.get(
                "simultaneous_event_and_liquidation_guard"
            ),
            "profit_first_advancement_guard": result.get(
                "profit_first_advancement_guard"
            ),
            "result_sha256": v4auth.sha256_file(
                economic_out / "RESULT.json"
            ),
            "full_result_sha256": v4auth.sha256_file(
                economic_out / "FULL_RESULT.json"
            ),
        },
        "strict_v4_diagnostic": strict_v4_decision,
        "strict_v4_execution_error_before_v5": strict_v4_execution_error,
        "source_sha": v4auth.SOURCE_SHA,
        "strict_sha": v4auth.STRICT_SHA,
        "execution_checkout_sha": checkout_sha,
        "next_action": (
            "EXACT_BYBIT_RECONSTRUCTION_AND_OFFICIAL_2024H1_IMMEDIATELY"
            if survivor
            else "CHANGE_ALPHA"
        ),
        "official_2024h1_authorized": survivor,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "selected_risk_path": selected,
    }


def execute(work_dir: Path, publish_dir: Path) -> int:
    checkout_sha = v4auth.git("rev-parse", "HEAD")
    strict_v4_execution_error: str | None = None
    try:
        v4auth.execute(work_dir, publish_dir)
    except Exception as error:
        strict_v4_execution_error = repr(error)
        if not (work_dir / "source" / "SOURCE_GATE_RESULT.json").is_file():
            raise

    strict_v4_decision_path = publish_dir / "DECISION.json"
    strict_v4_decision = (
        json.loads(
            strict_v4_decision_path.read_text(encoding="utf-8")
        )
        if strict_v4_decision_path.exists()
        else None
    )
    source_out = work_dir / "source"
    source = json.loads(
        (source_out / "SOURCE_GATE_RESULT.json").read_text(encoding="utf-8")
    )
    if source["status"] != "PASS":
        decision = dict(strict_v4_decision or {})
        decision.update(
            {
                "result_id": RESULT_ID,
                "claim_id": CLAIM_ID,
                "status": source["status"],
                "hard_validity_status": (
                    "PASS_OUTCOME_SEALED_SOURCE_DECISION"
                ),
                "economic_status": "NOT_OPENED",
                "ranking_role": "NONE_SOURCE_DECISION",
                "profit_first_correction_id": PROFIT_CORRECTION,
                "strict_v4_execution_error_before_v5": (
                    strict_v4_execution_error
                ),
                "execution_checkout_sha": checkout_sha,
                "next_action": (
                    "CHANGE_ALPHA"
                    if source["status"]
                    == "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE"
                    else "CLOSE_SOURCE_OR_REPAIR_TRANSPORT_ONLY"
                ),
                "official_2024_2026_opened": False,
                "orders_submitted": False,
            }
        )
        v4auth.write_json(publish_dir / "DECISION.json", decision)
        v4auth.freeze_hashes(publish_dir)
        print("STABLECOIN_PROFIT_V5_DECISION_BEGIN")
        print(v4auth.stable_json(decision))
        print("STABLECOIN_PROFIT_V5_DECISION_END")
        return 0

    repository = work_dir / "repository"
    base_root = (
        repository
        / "research"
        / "ml_stablecoin_issuance_economic_20260726"
    )
    guard_root = (
        repository
        / "sourcefix"
        / "ml_stablecoin_causal_guard_20260726"
    )
    v4_root = (
        ROOT / "research" / "execution" / "stablecoin_strict_v4_20260727"
    )
    v5_root = (
        ROOT / "research" / "execution" / "stablecoin_profit_v5_20260727"
    )
    market_cache = work_dir / "market"
    economic_out = work_dir / "economic_profit_v5"
    shutil.rmtree(economic_out, ignore_errors=True)
    economic_out.mkdir(parents=True, exist_ok=True)
    environment = {
        "PYTHONPATH": os.pathsep.join(
            [str(base_root), str(guard_root), str(v4_root), str(v5_root)]
        )
    }
    v4auth.run(
        [
            sys.executable,
            "-m",
            "json.tool",
            str(
                v5_root
                / "CORRECTION_005_PROFIT_FIRST_ADVANCEMENT_BEFORE_OUTCOME.json"
            ),
        ]
    )
    v4auth.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(v5_root / "profit_guard_v5.py"),
            str(v5_root / "profit_guard_v5_exact.py"),
        ]
    )
    v4auth.run(
        [
            sys.executable,
            str(v5_root / "profit_guard_v5_exact.py"),
            "self-test",
        ],
        env=environment,
        log=work_dir / "PROFIT_V5_SELF_TEST.log",
    )
    process = v4auth.run(
        [
            sys.executable,
            str(v5_root / "profit_guard_v5_exact.py"),
            "run",
            "--events",
            str(source_out / "EVENTS.jsonl"),
            "--market-cache",
            str(market_cache),
            "--output",
            str(economic_out),
        ],
        env=environment,
        check=False,
        log=economic_out / "RUN.log",
    )
    (economic_out / "RUN_EXIT_CODE.txt").write_text(
        f"{process.returncode}\n", encoding="utf-8"
    )
    if process.returncode not in {0, 2}:
        raise RuntimeError(
            f"profit-first V5 process failed: {process.returncode}"
        )
    result, _ = validate_profit_result(economic_out)

    if (publish_dir / "RESULT.json").exists():
        shutil.copy2(
            publish_dir / "RESULT.json",
            publish_dir / "STRICT_V4_DIAGNOSTIC_RESULT.json",
        )
    v4auth.copy_if_exists(
        economic_out / "RESULT.json", publish_dir / "RESULT.json"
    )
    v4auth.copy_if_exists(
        economic_out / "FULL_RESULT.json",
        publish_dir / "FULL_RESULT.json",
    )
    v4auth.copy_if_exists(
        economic_out / "SHA256SUMS.txt",
        publish_dir / "PROFIT_V5_ECONOMIC_SHA256SUMS.txt",
    )
    v4auth.copy_if_exists(
        v5_root
        / "CORRECTION_005_PROFIT_FIRST_ADVANCEMENT_BEFORE_OUTCOME.json",
        publish_dir
        / "CORRECTION_005_PROFIT_FIRST_ADVANCEMENT_BEFORE_OUTCOME.json",
    )
    decision = build_profit_decision(
        source=source,
        result=result,
        checkout_sha=checkout_sha,
        source_out=source_out,
        economic_out=economic_out,
        strict_v4_decision=strict_v4_decision,
        strict_v4_execution_error=strict_v4_execution_error,
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
            "strict_v4_diagnostic_completed": (
                strict_v4_decision is not None
            ),
            "strict_v4_execution_error_before_v5": (
                strict_v4_execution_error
            ),
            "profit_first_v5_completed": True,
            "profit_first_correction_id": PROFIT_CORRECTION,
            "risk_notional_grid_candidate_count": 99,
            "source_outcome_seal_passed": True,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        },
    )
    v4auth.freeze_hashes(publish_dir)
    v4auth.freeze_hashes(work_dir)
    print("STABLECOIN_PROFIT_V5_DECISION_BEGIN")
    print(v4auth.stable_json(decision))
    print("STABLECOIN_PROFIT_V5_DECISION_END")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--publish-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        return execute(
            args.work_dir.resolve(), args.publish_dir.resolve()
        )
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
        v4auth.write_json(
            args.publish_dir / "EXECUTION_FAILURE.json", failure
        )
        v4auth.freeze_hashes(args.publish_dir)
        print(
            json.dumps(failure, indent=2, sort_keys=True),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
