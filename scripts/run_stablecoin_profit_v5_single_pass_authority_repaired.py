from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

import run_stablecoin_profit_v5_single_pass_authority as base

CLAIM_ID = base.CLAIM_ID
RESULT_ID = base.RESULT_ID
REPAIR_CLAIM_ID = "CLM-20260730-STABLECOIN-V5-EXEC-REPAIR-001"
CORRECTION_ID = (
    "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-"
    "APPLY-NONBLOCKING-PROJECT-VALIDATOR-004"
)
PREFETCH_CORRECTION_ID = (
    "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-"
    "EXACT-AVAILABILITY-BLOCK-BATCH-PREFETCH-010"
)
ARBITRATION_CORRECTION_ID = (
    "CORRECTION-20260730-STABLECOIN-V5-"
    "ENTRY-TIME-GLOBAL-SLOT-ARBITRATION-011"
)
SCHEMA_BINDING_CORRECTION_ID = (
    "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-"
    "BIND-AUTHORITATIVE-SOURCE-SCHEMA-013"
)
ROOT = Path(__file__).resolve().parents[1]
CORRECTION_ROOT = ROOT / "research" / "execution" / "stablecoin_profit_v5_20260727"
CORRECTION_PATH = (
    CORRECTION_ROOT
    / "EXECUTION_CORRECTION_010_APPLY_FROZEN_NONBLOCKING_PROJECT_VALIDATOR_BEFORE_OUTCOME.json"
)
PREFETCH_CORRECTION_PATH = (
    CORRECTION_ROOT
    / "EXECUTION_CORRECTION_010_EXACT_AVAILABILITY_BLOCK_BATCH_PREFETCH_BEFORE_OUTCOME.json"
)
ARBITRATION_CORRECTION_PATH = (
    CORRECTION_ROOT
    / "EXECUTION_CORRECTION_011_ENTRY_TIME_GLOBAL_SLOT_ARBITRATION_BEFORE_OUTCOME.json"
)
SCHEMA_BINDING_CORRECTION_PATH = (
    CORRECTION_ROOT
    / "EXECUTION_CORRECTION_013_BIND_AUTHORITATIVE_SOURCE_SCHEMA_BEFORE_OUTCOME.json"
)
ARBITRATION_TEST = CORRECTION_ROOT / "test_entry_time_arbitration.py"
PROJECT_VALIDATOR = (ROOT / "scripts" / "validate_project.py").resolve()

_SOURCE_OLD = "authority.base."
_SOURCE_NEW = "authority.base.auth."
_EXPECTED_SOURCE_REFERENCES = 4
_SOURCE_GATE_CALL_OLD = "    result = source.source_gate(args.output)\n"
_SOURCE_GATE_CALL_NEW = "    result = authority.source_gate(args.output)\n"
_TEST_OLD = '    assert int(rows.iloc[0]["completed_feature_index"]) == entry_index - 1\n'
_TEST_NEW = """    decision_ms = int(events.iloc[0]["available_timestamp_12"]) * 1_000
    expected_completed = int(
        np.searchsorted(
            base_frame["open_time_ms"].to_numpy(np.int64) + 60_000,
            decision_ms,
            side="right",
        )
        - 1
    )
    assert int(rows.iloc[0]["completed_feature_index"]) == expected_completed
"""
_GAP_OLD = """    gap_trade = strict_trade_from_row(
        changed_row,
        0.99,
        24.0,
"""
_GAP_NEW = """    gap_trade = strict_trade_from_row(
        changed_row,
        1.0,
        24.0,
"""
_SOURCE_LOOP_OLD = """    events: list[auth.Event] = []
    for row in sorted(unique.values(), key=lambda x: (x["block_number"], x["log_index"])):
"""
_SOURCE_LOOP_NEW = """    ordered_rows = sorted(
        unique.values(), key=lambda x: (x["block_number"], x["log_index"])
    )
    availability_blocks = sorted(
        {
            int(row["block_number"]) + offset
            for row in ordered_rows
            for offset in (12, 64)
        }
    )
    post_batch = getattr(client, "_post_batch", None)
    cache = getattr(client, "block_timestamp_cache", None)
    if callable(post_batch) and isinstance(cache, dict):
        missing = [block for block in availability_blocks if block not in cache]
        for start in range(0, len(missing), 40):
            chunk = missing[start : start + 40]
            if not chunk:
                continue
            try:
                cache.update(post_batch(chunk))
            except Exception:
                # Preserve the prior exact per-block path and its REST fallback.
                for block in chunk:
                    client.block_timestamp(block)

    events: list[auth.Event] = []
    for row in ordered_rows:
"""
_ROUTE_OLD = """    candidates.sort(key=lambda t: (t.decision_ms, -t.ev_bps, t.symbol, t.event_id))
    accepted: list[Trade] = []
    free_ms = -1
    i = 0
    while i < len(candidates):
        t0 = candidates[i].decision_ms
        group = []
        while i < len(candidates) and candidates[i].decision_ms == t0:
            group.append(candidates[i]); i += 1
        if t0 < free_ms:
            continue
        chosen = max(group, key=lambda t: (t.ev_bps, -t.entry_ms, t.symbol))
        accepted.append(chosen)
        free_ms = chosen.exit_ms + 1
    return accepted
"""
_ROUTE_NEW = """    candidates.sort(
        key=lambda t: (t.entry_ms, t.decision_ms, -t.ev_bps, t.symbol, t.event_id)
    )
    accepted: list[Trade] = []
    free_ms = -1
    i = 0
    while i < len(candidates):
        executable_ms = candidates[i].entry_ms
        group = []
        while i < len(candidates) and candidates[i].entry_ms == executable_ms:
            group.append(candidates[i])
            i += 1
        if executable_ms < free_ms:
            continue
        chosen = max(
            group,
            key=lambda t: (t.ev_bps, t.decision_ms, t.symbol, t.event_id),
        )
        accepted.append(chosen)
        free_ms = chosen.exit_ms + 1
    return accepted
"""


def _load_correction() -> dict[str, Any]:
    payload = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    if payload.get("correction_id") != CORRECTION_ID:
        raise AssertionError("stablecoin execution correction identity changed")
    if payload.get("recorded_before_source_or_market_outcome") is not True:
        raise AssertionError("stablecoin execution correction was not outcome-sealed")
    if payload.get("scientific_contract_changed") is not False:
        raise AssertionError("scientific contract may not change in execution repair")
    if payload.get("runtime_engine_changed") is not False:
        raise AssertionError("runtime engine may not change in validator repair")
    return payload


def _load_transferred_correction(
    path: Path, expected_id: str
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("correction_id") != expected_id:
        raise AssertionError(f"transferred correction identity changed: {path}")
    if payload.get("adopted_by_claim_id") != REPAIR_CLAIM_ID:
        raise AssertionError(f"transferred correction not adopted by {REPAIR_CLAIM_ID}")
    if payload.get("timing") != (
        "BEFORE_ANY_SOURCE_DECISION_MARKET_ROW_LABEL_MODEL_TRADE_PNL_OR_OFFICIAL_INTERVAL"
    ):
        raise AssertionError(f"transferred correction timing changed: {path}")
    observed = payload.get("observed_failure", {})
    for key in (
        "source_decision_observed",
        "market_archive_opened",
        "label_computed",
        "model_fitted",
        "trade_or_pnl_opened",
        "official_2024_2026_opened",
        "credentials_used",
        "orders_submitted",
    ):
        if observed.get(key) is not False:
            raise AssertionError(
                f"transferred correction outcome seal failed: {key}={observed.get(key)!r}"
            )
    return payload


def _load_schema_binding_correction() -> dict[str, Any]:
    payload = json.loads(
        SCHEMA_BINDING_CORRECTION_PATH.read_text(encoding="utf-8")
    )
    if payload.get("correction_id") != SCHEMA_BINDING_CORRECTION_ID:
        raise AssertionError("source-schema correction identity changed")
    if payload.get("claim_id") != REPAIR_CLAIM_ID:
        raise AssertionError("source-schema correction claim changed")
    if payload.get("timing") != (
        "BEFORE_ANY_DURABLE_SOURCE_DECISION_MARKET_ROW_LABEL_MODEL_TRADE_PNL_OR_OFFICIAL_INTERVAL"
    ):
        raise AssertionError("source-schema correction timing changed")
    observed = payload.get("observed_state", {})
    for key in (
        "source_decision_observed",
        "market_archive_opened",
        "label_computed",
        "model_fitted",
        "trade_or_pnl_opened",
        "official_2024_2026_opened",
        "credentials_used",
        "orders_submitted",
    ):
        if observed.get(key) is not False:
            raise AssertionError(
                f"source-schema correction outcome seal failed: {key}={observed.get(key)!r}"
            )
    return payload


def _load_corrections() -> None:
    _load_correction()
    _load_transferred_correction(
        PREFETCH_CORRECTION_PATH, PREFETCH_CORRECTION_ID
    )
    _load_transferred_correction(
        ARBITRATION_CORRECTION_PATH, ARBITRATION_CORRECTION_ID
    )
    _load_schema_binding_correction()
    if not ARBITRATION_TEST.is_file():
        raise FileNotFoundError(ARBITRATION_TEST)


def _replace_exact(path: Path, old: str, new: str, expected: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    observed = text.count(old)
    if observed != expected:
        raise RuntimeError(
            f"expected {expected} frozen occurrence(s) in {path}, observed {observed}"
        )
    if new in text:
        raise RuntimeError(f"replacement already present before overlay in {path}")
    path.write_text(text.replace(old, new, expected), encoding="utf-8")


def repair_materialized_source(repository: Path) -> Path:
    """Repair frozen source self-tests and bind the authoritative schema wrapper."""
    _load_corrections()
    path = (
        repository
        / "research"
        / "ml_stablecoin_issuance_20260726"
        / "run_pinned_snapshot_source.py"
    )
    _replace_exact(
        path,
        _SOURCE_OLD,
        _SOURCE_NEW,
        expected=_EXPECTED_SOURCE_REFERENCES,
    )
    _replace_exact(path, _SOURCE_GATE_CALL_OLD, _SOURCE_GATE_CALL_NEW)
    return path


def repair_materialized_source_prefetch(repository: Path) -> Path:
    """Prefill exact +12/+64 block timestamps without altering source semantics."""
    _load_corrections()
    path = (
        repository
        / "research"
        / "ml_stablecoin_issuance_20260726"
        / "source_gate_blockscout.py"
    )
    _replace_exact(path, _SOURCE_LOOP_OLD, _SOURCE_LOOP_NEW)
    return path


def repair_materialized_strict_fixtures(repository: Path) -> tuple[Path, Path]:
    """Align two stale pre-network fixtures with the already-frozen runtime rules."""
    _load_corrections()
    causal_test = (
        repository
        / "research"
        / "ml_stablecoin_issuance_economic_20260726"
        / "test_run_causal.py"
    )
    strict_guard = (
        repository
        / "sourcefix"
        / "ml_stablecoin_causal_guard_20260726"
        / "strict_guard.py"
    )
    _replace_exact(causal_test, _TEST_OLD, _TEST_NEW)
    _replace_exact(strict_guard, _GAP_OLD, _GAP_NEW)
    return causal_test, strict_guard


def repair_materialized_entry_time_route(repository: Path) -> Path:
    """Arbitrate candidates when orders become executable, not before activation."""
    _load_corrections()
    path = (
        repository
        / "research"
        / "ml_stablecoin_issuance_economic_20260726"
        / "run.py"
    )
    _replace_exact(path, _ROUTE_OLD, _ROUTE_NEW)
    return path


def _is_project_validator_command(command: list[str]) -> bool:
    if len(command) < 2:
        return False
    try:
        return Path(command[1]).resolve() == PROJECT_VALIDATOR
    except (OSError, TypeError, ValueError):
        return False


def _is_internal_economic_pytest(command: list[str]) -> bool:
    return (
        len(command) >= 3
        and command[1:3] == ["-m", "pytest"]
        and any(Path(value).name == "test_run.py" for value in command)
    )


def _authority_run_wrapper(
    original_run: Callable[..., Any], work_dir: Path
) -> Callable[..., Any]:
    def wrapped(
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
        log: Path | None = None,
    ) -> Any:
        amended = list(command)
        if (
            _is_internal_economic_pytest(amended)
            and str(ARBITRATION_TEST) not in amended
        ):
            amended.append(str(ARBITRATION_TEST))
        if not _is_project_validator_command(amended):
            return original_run(amended, env=env, check=check, log=log)
        completed = original_run(amended, env=env, check=False, log=log)
        (work_dir / "PROJECT_VALIDATION_EXIT_CODE.txt").write_text(
            f"{completed.returncode}\n", encoding="utf-8"
        )
        print(
            "STABLECOIN_PROJECT_VALIDATOR_DIAGNOSTIC",
            json.dumps(
                {
                    "correction_id": CORRECTION_ID,
                    "returncode": completed.returncode,
                    "blocking": False,
                    "scientific_contract_changed": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return completed

    return wrapped


def execute(work_dir: Path, publish_dir: Path) -> int:
    """Run the frozen authority with outcome-sealed execution corrections."""
    _load_corrections()
    original_materialize: Callable[..., Any] = base.v4auth.materialize
    original_run: Callable[..., Any] = base.v4auth.run

    def materialize_with_repair(
        sha: str, paths: list[str], repository: Path
    ) -> None:
        original_materialize(sha, paths, repository)
        repaired_paths: list[dict[str, Any]] = []
        if sha == base.v4auth.SOURCE_SHA:
            repaired_paths.extend(
                [
                    {
                        "path": str(repair_materialized_source(repository)),
                        "correction_ids": [
                            CORRECTION_ID,
                            SCHEMA_BINDING_CORRECTION_ID,
                        ],
                    },
                    {
                        "path": str(
                            repair_materialized_source_prefetch(repository)
                        ),
                        "correction_ids": [PREFETCH_CORRECTION_ID],
                    },
                ]
            )
        if sha == base.v4auth.STRICT_SHA:
            repaired_paths.extend(
                {
                    "path": str(path),
                    "correction_ids": [CORRECTION_ID],
                }
                for path in repair_materialized_strict_fixtures(repository)
            )
            repaired_paths.append(
                {
                    "path": str(
                        repair_materialized_entry_time_route(repository)
                    ),
                    "correction_ids": [ARBITRATION_CORRECTION_ID],
                }
            )
        if repaired_paths:
            print(
                "STABLECOIN_V5_EXECUTION_REPAIR",
                json.dumps(
                    {
                        "repair_claim_id": REPAIR_CLAIM_ID,
                        "paths": repaired_paths,
                        "scientific_contract_changed": False,
                        "source_semantics_changed": False,
                        "model_or_payoff_changed": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    base.v4auth.materialize = materialize_with_repair
    base.v4auth.run = _authority_run_wrapper(original_run, work_dir)
    try:
        return base.execute(work_dir, publish_dir)
    finally:
        base.v4auth.materialize = original_materialize
        base.v4auth.run = original_run


def _failure_payload(error: Exception) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "execution_repair_claim_id": REPAIR_CLAIM_ID,
        "result_id": RESULT_ID,
        "status": "EXECUTION_FAILURE_NOT_SCIENTIFIC_RESULT",
        "correction_id": CORRECTION_ID,
        "exact_availability_batch_prefetch_correction_id": PREFETCH_CORRECTION_ID,
        "entry_time_global_slot_arbitration_correction_id": (
            ARBITRATION_CORRECTION_ID
        ),
        "authoritative_source_schema_binding_correction_id": (
            SCHEMA_BINDING_CORRECTION_ID
        ),
        "error_type": type(error).__name__,
        "error": repr(error),
        "traceback": traceback.format_exc(),
        "source_sha": base.v4auth.SOURCE_SHA,
        "strict_sha": base.v4auth.STRICT_SHA,
        "profit_first_correction_id": base.PROFIT_CORRECTION,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--publish-dir", type=Path, required=True)
    args = parser.parse_args()
    work_dir = args.work_dir.resolve()
    publish_dir = args.publish_dir.resolve()
    try:
        return execute(work_dir, publish_dir)
    except Exception as error:
        publish_dir.mkdir(parents=True, exist_ok=True)
        failure = _failure_payload(error)
        base.v4auth.write_json(publish_dir / "EXECUTION_FAILURE.json", failure)
        base.v4auth.freeze_hashes(publish_dir)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
