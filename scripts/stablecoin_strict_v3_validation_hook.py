from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "3631cf01a2a2b91d690b81160e14ba033a298f75"
STRICT_SHA = "209a0fbe6e2f61d2c58b3eb7910b8c0c139cd46c"
TRIGGER = (
    ROOT
    / "research"
    / "execution"
    / "stablecoin_strict_validator_hook_20260727"
    / "RUN.txt"
)
CORRECTION = (
    ROOT
    / "research"
    / "execution"
    / "stablecoin_strict_validator_hook_20260727"
    / "EXECUTION_CORRECTION.json"
)
RUNNER_TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
WORK = RUNNER_TEMP / "stablecoin_strict_v3_validation_hook"
OUT = WORK / "output"
MARKET = WORK / "market"
MARKER = RUNNER_TEMP / "stablecoin_strict_v3_validation_hook_summary.json"


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    allowed: tuple[int, ...] = (0,),
) -> int:
    print("STABLECOIN_STRICT_V3_COMMAND", json.dumps(command), flush=True)
    merged = os.environ.copy()
    if env:
        merged.update(env)
    completed = subprocess.run(command, cwd=cwd, env=merged, check=False)
    if completed.returncode not in allowed:
        raise RuntimeError(
            f"command returned {completed.returncode}, allowed={allowed}: {command}"
        )
    return completed.returncode


def materialize(commit: str, relative_paths: list[str]) -> None:
    run(["git", "fetch", "--no-tags", "--depth=1", "origin", commit])
    observed = subprocess.check_output(
        ["git", "rev-parse", "FETCH_HEAD"], cwd=ROOT, text=True
    ).strip()
    if observed != commit:
        raise AssertionError(f"fetched {observed}, expected {commit}")
    command = (
        "set -euo pipefail; "
        f"git archive {commit} {' '.join(relative_paths)} | tar -x -C {WORK}"
    )
    run(["bash", "-lc", command])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sanitize(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def source_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "event_count": result.get("event_count"),
        "event_month_count": len(result.get("months_with_events", [])),
        "distinct_tokens": result.get("distinct_tokens"),
        "token_counts": result.get("token_counts"),
        "pass_checks": result.get("pass_checks"),
        "source_schema_id": result.get("source_schema_id"),
        "source_correction_id": result.get("source_correction_id"),
        "transport_response_policy_correction": result.get(
            "transport_response_policy_correction"
        ),
        "status_zero_empty_policy": result.get("status_zero_empty_policy"),
        "unrecognized_status_zero_policy": result.get(
            "unrecognized_status_zero_policy"
        ),
    }


def economic_summary(result: dict[str, Any]) -> dict[str, Any]:
    development = result.get("development", {})
    costs = development.get("costs", {}) if isinstance(development, dict) else {}
    primary = costs.get("24", {}) if isinstance(costs, dict) else {}
    confirmation = result.get("confirmation", {})
    return {
        "status": result.get("status"),
        "engine": result.get("engine"),
        "source_event_count": result.get("source_event_count"),
        "row_count_12": result.get("row_count_12"),
        "row_count_64": result.get("row_count_64"),
        "strict_causal_guard": result.get("strict_causal_guard"),
        "confirmation": {
            "resolved_labels": confirmation.get("resolved_labels"),
            "model_auc": confirmation.get("model_auc"),
            "distance_baseline_auc": confirmation.get("distance_baseline_auc"),
            "brier_skill": confirmation.get("brier_skill"),
        },
        "development_24bp": {
            "total_return": primary.get("total_return"),
            "geometric_calendar_day_growth": primary.get(
                "geometric_calendar_day_growth"
            ),
            "trade_count": primary.get("trade_count"),
            "median_trade_bps": primary.get("median_trade_bps"),
            "profit_factor": primary.get("profit_factor"),
            "maximum_drawdown": primary.get("maximum_drawdown"),
            "liquidation": primary.get("liquidation"),
            "winner_removed": primary.get("winner_removed"),
        },
        "development_gate": result.get("development_gate"),
        "selected_risk_path": (
            result.get("risk_search", {}).get("selected")
            if isinstance(result.get("risk_search"), dict)
            else None
        ),
        "official_2024h1_opened": result.get("official_2024h1_opened"),
        "orders_submitted": result.get("orders_submitted"),
    }


def write_marker(payload: dict[str, Any]) -> None:
    MARKER.write_text(
        json.dumps(sanitize(payload), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def emit(payload: dict[str, Any]) -> None:
    print("STABLECOIN_STRICT_V3_RESULT_BEGIN", flush=True)
    print(json.dumps(sanitize(payload), sort_keys=True), flush=True)
    print("STABLECOIN_STRICT_V3_RESULT_END", flush=True)


def main() -> int:
    if not TRIGGER.exists():
        return 0
    if MARKER.exists():
        emit(load_json(MARKER))
        return 0

    correction = load_json(CORRECTION)
    if correction.get("source_sha") != SOURCE_SHA:
        raise AssertionError("validator-hook source pin changed")
    if correction.get("strict_sha") != STRICT_SHA:
        raise AssertionError("validator-hook strict pin changed")
    if correction.get("recorded_before_source_decision") is not True:
        raise AssertionError("hook not frozen before source decision")
    if correction.get("recorded_before_market_outcome") is not True:
        raise AssertionError("hook not frozen before market outcome")

    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    MARKET.mkdir(parents=True, exist_ok=True)

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
    materialize(SOURCE_SHA, ["research/ml_stablecoin_issuance_20260726"])
    materialize(
        STRICT_SHA,
        [
            "research/ml_stablecoin_issuance_economic_20260726",
            "sourcefix/ml_stablecoin_causal_guard_20260726",
        ],
    )

    source_root = WORK / "research" / "ml_stablecoin_issuance_20260726"
    economic_root = WORK / "research" / "ml_stablecoin_issuance_economic_20260726"
    guard_root = WORK / "sourcefix" / "ml_stablecoin_causal_guard_20260726"
    source_out = OUT / "source"
    economic_out = OUT / "economic"
    source_out.mkdir(parents=True, exist_ok=True)
    economic_out.mkdir(parents=True, exist_ok=True)

    for path in (
        source_root / "CORRECTION_010_USDT_ISSUE_REDEEM_EVENT_SCHEMA_BEFORE_OUTCOME.json",
        source_root / "CORRECTION_011_BLOCKSCOUT_NULL_TOPIC_PADDING_BEFORE_OUTCOME.json",
        source_root / "CORRECTION_019_BLOCKSCOUT_STATUS0_FAIL_CLOSED_BEFORE_OUTCOME.json",
        guard_root / "CORRECTION_002_PREENTRY_INFORMATION_BOUNDARY_BEFORE_OUTCOME.json",
    ):
        load_json(path)

    source_env = {"PYTHONPATH": str(source_root)}
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(source_root / "test_source_gate.py"),
        ],
        env=source_env,
    )
    run(
        [sys.executable, str(source_root / "run_pinned_snapshot_source.py"), "--self-test"],
        env=source_env,
    )

    run([sys.executable, str(economic_root / "reconstruct.py")])
    strict_env = {
        "PYTHONPATH": os.pathsep.join((str(economic_root), str(guard_root)))
    }
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(economic_root / "test_run.py"),
            str(economic_root / "test_run_causal.py"),
            str(guard_root / "test_causal_guard.py"),
        ],
        env=strict_env,
    )
    run(
        [sys.executable, str(guard_root / "strict_guard.py"), "self-test"],
        env=strict_env,
    )

    source_rc = run(
        [
            sys.executable,
            str(source_root / "run_pinned_snapshot_source.py"),
            "--output",
            str(source_out),
        ],
        env=source_env,
        allowed=(0, 1, 2),
    )
    result_path = source_out / "SOURCE_GATE_RESULT.json"
    if not result_path.exists():
        run(
            [
                sys.executable,
                str(source_root / "write_transport_failure.py"),
                "--output",
                str(source_out),
                "--transport",
                "TRANSPORT-20260727-ML-STABLECOIN-STRICT-VALIDATOR-HOOK-005",
                "--exit-code",
                str(source_rc),
            ]
        )
    if not result_path.exists():
        raise AssertionError("transport failure writer did not create source result")

    source = load_json(result_path)
    for key in (
        "market_outcome_opened",
        "model_fit",
        "trade_or_pnl_opened",
        "official_2024_2026_opened",
        "orders_submitted",
    ):
        if source.get(key) is not False:
            raise AssertionError(f"source outcome seal failed: {key}")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001",
        "source_sha": SOURCE_SHA,
        "strict_sha": STRICT_SHA,
        "execution_correction": correction["correction_id"],
        "source": source_summary(source),
        "economic": {"status": "NOT_OPENED"},
        "next_stage": (
            "CHANGE_ALPHA"
            if source.get("status") == "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE"
            else "CLOSE_SOURCE_OR_CHANGE_TRANSPORT_ONLY"
        ),
    }

    if source.get("status") == "PASS":
        events = source_out / "EVENTS.jsonl"
        manifest = load_json(source_out / "SOURCE_MANIFEST.json")
        rows = [
            json.loads(line)
            for line in events.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        checks = source.get("pass_checks", {})
        if not checks or not all(value is True for value in checks.values()):
            raise AssertionError(f"source PASS checks failed: {checks}")
        if source.get("source_schema_id") != (
            "STABLECOIN_SUPPLY_USDT_ISSUE_REDEEM_USDC_ZERO_TRANSFER_V1"
        ):
            raise AssertionError("wrong source schema")
        if source.get("source_correction_id") != (
            "CORRECTION-20260726-ML-STABLECOIN-USDT-ISSUE-REDEEM-010"
        ):
            raise AssertionError("wrong source correction")
        if source.get("transport_response_policy_correction") != (
            "CORRECTION-20260727-ML-STABLECOIN-BLOCKSCOUT-STATUS0-FAIL-CLOSED-019"
        ):
            raise AssertionError("wrong fail-closed policy")
        if source.get("status_zero_empty_policy") != "EXPLICIT_NO_RECORDS_ONLY":
            raise AssertionError("wrong empty-source policy")
        if source.get("unrecognized_status_zero_policy") != (
            "FAIL_CLOSED_SOURCE_UNAVAILABLE"
        ):
            raise AssertionError("wrong unrecognized-status policy")
        if len(rows) < 120 or len(source.get("months_with_events", [])) < 24:
            raise AssertionError("source PASS below frozen gate")
        if {row["token"] for row in rows} != {"USDT", "USDC"}:
            raise AssertionError("source PASS missing token")
        if any(int(row["available_timestamp_64"]) >= 1_704_067_200 for row in rows):
            raise AssertionError("post-2023 source event entered the pre-2024 gate")
        if sha256_file(events) != manifest.get("events_sha256"):
            raise AssertionError("event hash mismatch")

        run(
            [
                sys.executable,
                str(guard_root / "strict_guard.py"),
                "run",
                "--events",
                str(events),
                "--market-cache",
                str(MARKET),
                "--output",
                str(economic_out),
            ],
            env=strict_env,
            allowed=(0, 2),
        )
        economic = load_json(economic_out / "RESULT.json")
        full = load_json(economic_out / "FULL_RESULT.json")
        if economic.get("engine") != (
            "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_STRICT_CAUSAL_V3"
        ):
            raise AssertionError("wrong economic engine")
        guard = economic.get("strict_causal_guard", {})
        required_true = (
            "source_decision_second_respected",
            "latest_completed_bar_cutoff_enforced",
            "decision_reference_price_pre_entry",
            "entry_open_used_for_realized_execution_only",
            "stage_boundary_positions_marked_not_closed",
        )
        if not all(guard.get(key) is True for key in required_true):
            raise AssertionError(f"strict guard failed: {guard}")
        if guard.get("future_entry_open_used_for_model_or_action") is not False:
            raise AssertionError("future entry open leaked")
        if guard.get("fatal_validity_violation") is not False:
            raise AssertionError("fatal validity violation")
        serialized = json.dumps(full, sort_keys=True)
        if '"exit_reason": "SOURCE_BOUNDARY"' in serialized:
            raise AssertionError("legacy source-boundary exit")
        if economic.get("orders_submitted") is not False:
            raise AssertionError("order authority changed")

        payload["economic"] = economic_summary(economic)
        if economic.get("status") == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1":
            payload["next_stage"] = "OFFICIAL_2024H1_IMMEDIATELY"
        else:
            payload["next_stage"] = "CHANGE_ALPHA"

    payload["output_root"] = str(OUT)
    write_marker(payload)
    emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
