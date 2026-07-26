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
SOURCE_SHA = "3631cf01a2a2b91d690b81160e14ba033a298f75"
STRICT_SHA = "209a0fbe6e2f61d2c58b3eb7910b8c0c139cd46c"
RUNNER_TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
WORK = RUNNER_TEMP / "stablecoin_strict_source3631_r22"
TREE = WORK / "tree"
OUTPUT = ROOT / "research_runs" / "stablecoin_strict_source3631_r22"
MARKET = WORK / "market"

SOURCE_REL = Path("research/ml_stablecoin_issuance_20260726")
ECON_REL = Path("research/ml_stablecoin_issuance_economic_20260726")
FIX_REL = Path("sourcefix/ml_stablecoin_causal_guard_20260726")

CLAIM_ID = "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
SOURCE_SCHEMA = "STABLECOIN_SUPPLY_USDT_ISSUE_REDEEM_USDC_ZERO_TRANSFER_V1"
SOURCE_CORRECTION = "CORRECTION-20260726-ML-STABLECOIN-USDT-ISSUE-REDEEM-010"
RESPONSE_CORRECTION = (
    "CORRECTION-20260727-ML-STABLECOIN-BLOCKSCOUT-STATUS0-FAIL-CLOSED-019"
)
ENGINE = "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_STRICT_CAUSAL_V3"
GUARD_CORRECTION = (
    "CORRECTION-20260727-ML-STABLECOIN-PREENTRY-INFORMATION-BOUNDARY-002"
)


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    allowed: tuple[int, ...] = (0,),
) -> int:
    print("STABLECOIN_SOURCE3631_COMMAND", json.dumps(command), flush=True)
    merged = os.environ.copy()
    if env:
        merged.update(env)
    completed = subprocess.run(command, cwd=cwd, env=merged, check=False)
    if completed.returncode not in allowed:
        raise RuntimeError(
            f"command returned {completed.returncode}, allowed={allowed}: {command}"
        )
    return completed.returncode


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materialize(commit: str, paths: list[Path]) -> None:
    run(["git", "fetch", "--no-tags", "--depth=1", "origin", commit])
    observed = subprocess.check_output(
        ["git", "rev-parse", "FETCH_HEAD"], cwd=ROOT, text=True
    ).strip()
    if observed != commit:
        raise AssertionError(f"fetched {observed}, expected {commit}")
    quoted = " ".join(str(path) for path in paths)
    run(
        [
            "bash",
            "-lc",
            f"set -euo pipefail; git archive {commit} {quoted} | tar -x -C {TREE}",
        ]
    )


def summarize_source(result: dict[str, Any]) -> dict[str, Any]:
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
        "fatal_error": result.get("fatal_error"),
    }


def summarize_economic(result: dict[str, Any]) -> dict[str, Any]:
    development = result.get("development", {})
    costs = development.get("costs", {}) if isinstance(development, dict) else {}
    primary = costs.get("24", {}) if isinstance(costs, dict) else {}
    confirmation = result.get("confirmation", {})
    risk_search = result.get("risk_search")
    return {
        "status": result.get("status"),
        "engine": result.get("engine"),
        "source_event_count": result.get("source_event_count"),
        "row_count_12": result.get("row_count_12"),
        "row_count_64": result.get("row_count_64"),
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
            risk_search.get("selected") if isinstance(risk_search, dict) else None
        ),
        "official_2024h1_opened": result.get("official_2024h1_opened"),
        "orders_submitted": result.get("orders_submitted"),
    }


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(OUTPUT, ignore_errors=True)
    TREE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    MARKET.mkdir(parents=True, exist_ok=True)

    materialize(SOURCE_SHA, [SOURCE_REL])
    materialize(STRICT_SHA, [ECON_REL, FIX_REL])

    source_root = TREE / SOURCE_REL
    econ_root = TREE / ECON_REL
    fix_root = TREE / FIX_REL
    source_out = OUTPUT / "source"
    econ_out = OUTPUT / "economic"
    source_out.mkdir(parents=True, exist_ok=True)
    econ_out.mkdir(parents=True, exist_ok=True)

    for path in (
        source_root
        / "CORRECTION_010_USDT_ISSUE_REDEEM_EVENT_SCHEMA_BEFORE_OUTCOME.json",
        source_root / "CORRECTION_011_BLOCKSCOUT_NULL_TOPIC_PADDING_BEFORE_OUTCOME.json",
        source_root / "CORRECTION_019_BLOCKSCOUT_STATUS0_FAIL_CLOSED_BEFORE_OUTCOME.json",
        fix_root / "CORRECTION_002_PREENTRY_INFORMATION_BOUNDARY_BEFORE_OUTCOME.json",
    ):
        load_json(path)

    source_env = {"PYTHONPATH": str(source_root)}
    strict_env = {
        "PYTHONPATH": os.pathsep.join((str(econ_root), str(fix_root)))
    }

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
        [
            sys.executable,
            str(source_root / "run_pinned_snapshot_source.py"),
            "--self-test",
        ],
        env=source_env,
    )
    run([sys.executable, str(econ_root / "reconstruct.py")])
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(econ_root / "test_run.py"),
            str(econ_root / "test_run_causal.py"),
            str(fix_root / "test_causal_guard.py"),
        ],
        env=strict_env,
    )
    run(
        [sys.executable, str(fix_root / "causal_guard.py"), "self-test"],
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
    source_result_path = source_out / "SOURCE_GATE_RESULT.json"
    if not source_result_path.exists():
        run(
            [
                sys.executable,
                str(source_root / "write_transport_failure.py"),
                "--output",
                str(source_out),
                "--transport",
                "TRANSPORT-20260727-ML-STABLECOIN-SOURCE3631-R22-001",
                "--exit-code",
                str(source_rc),
            ]
        )

    source = load_json(source_result_path)
    if source.get("claim_id") != CLAIM_ID:
        raise AssertionError("claim changed")
    if source.get("status") not in {
        "PASS",
        "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE",
        "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE",
    }:
        raise AssertionError(f"unexpected source status: {source.get('status')}")
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
        "claim_id": CLAIM_ID,
        "source_sha": SOURCE_SHA,
        "strict_sha": STRICT_SHA,
        "source": summarize_source(source),
        "economic": {"status": "NOT_OPENED"},
        "next_stage": "CLOSE_SOURCE_OR_CHANGE_TRANSPORT_ONLY",
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
        if source.get("source_schema_id") != SOURCE_SCHEMA:
            raise AssertionError("wrong source schema")
        if source.get("source_correction_id") != SOURCE_CORRECTION:
            raise AssertionError("wrong source correction")
        if source.get("transport_response_policy_correction") != RESPONSE_CORRECTION:
            raise AssertionError("wrong transport response correction")
        if source.get("status_zero_empty_policy") != "EXPLICIT_NO_RECORDS_ONLY":
            raise AssertionError("wrong status=0 empty policy")
        if source.get("unrecognized_status_zero_policy") != (
            "FAIL_CLOSED_SOURCE_UNAVAILABLE"
        ):
            raise AssertionError("wrong unrecognized status=0 policy")
        if manifest.get("source_schema_id") != SOURCE_SCHEMA:
            raise AssertionError("manifest source schema mismatch")
        if manifest.get("source_correction_id") != SOURCE_CORRECTION:
            raise AssertionError("manifest source correction mismatch")
        if (
            source.get("event_semantics", {}).get("ordinary_usdt_transfer_excluded")
            is not True
        ):
            raise AssertionError("ordinary USDT transfer exclusion changed")
        if len(rows) < 120 or len(source.get("months_with_events", [])) < 24:
            raise AssertionError("source PASS below frozen density gate")
        if {row["token"] for row in rows} != {"USDT", "USDC"}:
            raise AssertionError("source PASS missing token")
        if any(int(row["available_timestamp_12"]) >= 1704067200 for row in rows):
            raise AssertionError("post-2023 block+12 event")
        if any(int(row["available_timestamp_64"]) >= 1704067200 for row in rows):
            raise AssertionError("post-2023 block+64 event")
        if sha256_file(events) != manifest.get("events_sha256"):
            raise AssertionError("event hash mismatch")

        run(
            [
                sys.executable,
                str(fix_root / "causal_guard.py"),
                "run",
                "--events",
                str(events),
                "--market-cache",
                str(MARKET),
                "--output",
                str(econ_out),
            ],
            env=strict_env,
            allowed=(0, 2),
        )
        economic = load_json(econ_out / "RESULT.json")
        full = load_json(econ_out / "FULL_RESULT.json")
        if economic.get("claim_id") != CLAIM_ID:
            raise AssertionError("economic claim changed")
        if economic.get("engine") != ENGINE:
            raise AssertionError("economic engine changed")
        guard = economic.get("strict_causal_guard", {})
        if guard.get("correction_id") != GUARD_CORRECTION:
            raise AssertionError("guard correction changed")
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
        if guard.get("legacy_source_boundary_paths") != []:
            raise AssertionError("legacy source boundary path")
        if guard.get("forced_boundary_close_true_paths") != []:
            raise AssertionError("forced boundary close path")
        if economic.get("orders_submitted") is not False:
            raise AssertionError("order authority changed")
        if economic.get("official_2024h1_opened") is not False:
            raise AssertionError("official 2024H1 opened inside pre-2024 screen")
        if economic.get("status") not in {
            "PRE2024_BELOW_GATE",
            "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1",
        }:
            raise AssertionError(
                f"unexpected economic status: {economic.get('status')}"
            )
        serialized = json.dumps(full, sort_keys=True)
        if '"exit_reason": "SOURCE_BOUNDARY"' in serialized:
            raise AssertionError("legacy source boundary exit")

        payload["economic"] = summarize_economic(economic)
        if economic.get("status") == (
            "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
        ):
            selected = economic.get("risk_search", {}).get("selected")
            if economic.get("development_gate", {}).get("all") is not True:
                raise AssertionError("development gate not complete")
            if not selected or selected.get("growth", 0) <= 0:
                raise AssertionError("no positive selected risk path")
            if selected.get("liquidation") is not False:
                raise AssertionError("selected risk path liquidates")
            payload["next_stage"] = "OFFICIAL_2024H1_IMMEDIATELY"
        else:
            payload["next_stage"] = "CHANGE_ALPHA"

    summary = OUTPUT / "RESULT_SUMMARY.json"
    summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    hashes: list[str] = []
    for path in sorted(
        item
        for item in OUTPUT.rglob("*")
        if item.is_file() and item.name != "OUTPUT_SHA256SUMS.txt"
    ):
        hashes.append(f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}\n")
    (OUTPUT / "OUTPUT_SHA256SUMS.txt").write_text(
        "".join(hashes), encoding="utf-8"
    )

    print("STABLECOIN_SOURCE3631_RESULT_BEGIN", flush=True)
    print(json.dumps(payload, sort_keys=True, allow_nan=False), flush=True)
    print("STABLECOIN_SOURCE3631_RESULT_END", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
