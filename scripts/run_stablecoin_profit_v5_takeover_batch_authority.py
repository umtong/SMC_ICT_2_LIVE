from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

import run_stablecoin_profit_v5_takeover_authority as prior

ROOT = Path(__file__).resolve().parents[1]
CORRECTION_ID = (
    "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-"
    "EXACT-AVAILABILITY-BLOCK-BATCH-PREFETCH-010"
)
ARBITRATION_CORRECTION_ID = (
    "CORRECTION-20260730-STABLECOIN-V5-"
    "ENTRY-TIME-GLOBAL-SLOT-ARBITRATION-011"
)
CORRECTION_ROOT = ROOT / "research" / "execution" / "stablecoin_profit_v5_20260727"
CORRECTION_FILE = (
    CORRECTION_ROOT
    / "EXECUTION_CORRECTION_010_EXACT_AVAILABILITY_BLOCK_BATCH_PREFETCH_BEFORE_OUTCOME.json"
)
ARBITRATION_CORRECTION_FILE = (
    CORRECTION_ROOT
    / "EXECUTION_CORRECTION_011_ENTRY_TIME_GLOBAL_SLOT_ARBITRATION_BEFORE_OUTCOME.json"
)
ARBITRATION_TEST = CORRECTION_ROOT / "test_entry_time_arbitration.py"

_OLD_SOURCE_LOOP = '''    events: list[auth.Event] = []
    for row in sorted(unique.values(), key=lambda x: (x["block_number"], x["log_index"])):
'''
_NEW_SOURCE_LOOP = '''    ordered_rows = sorted(
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
'''
_OLD_ROUTE = '''    candidates.sort(key=lambda t: (t.decision_ms, -t.ev_bps, t.symbol, t.event_id))
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
'''
_NEW_ROUTE = '''    candidates.sort(
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
'''
_ORIGINAL_PATCH = prior._patch_materialized_files
_PRIOR_ORIGINAL_RUN = prior._ORIGINAL_RUN
_PATCHED: set[Path] = set()


def _load_outcome_sealed_correction(path: Path, expected_id: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("correction_id") != expected_id:
        raise AssertionError(value.get("correction_id"))
    if value.get("timing") != (
        "BEFORE_ANY_SOURCE_DECISION_MARKET_ROW_LABEL_MODEL_TRADE_PNL_OR_OFFICIAL_INTERVAL"
    ):
        raise AssertionError(value.get("timing"))
    observed = value.get("observed_failure", {})
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
            raise AssertionError(f"outcome seal failed: {key}={observed.get(key)!r}")
    return value


def _load_corrections() -> None:
    _load_outcome_sealed_correction(CORRECTION_FILE, CORRECTION_ID)
    _load_outcome_sealed_correction(
        ARBITRATION_CORRECTION_FILE, ARBITRATION_CORRECTION_ID
    )


def _replace_exact(path: Path, old: str, new: str) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == 1 and new_count == 0:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
    elif old_count == 0 and new_count == 1:
        pass
    else:
        raise RuntimeError(
            "unexpected materialized source identity: "
            f"old={old_count}, new={new_count}, path={path}"
        )
    return old_count, new_count


def _patch_source_prefetch(command: list[str]) -> None:
    for value in command:
        path = Path(value)
        if path.name != "source_gate_blockscout.py" or not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in _PATCHED:
            continue
        old_count, new_count = _replace_exact(
            resolved, _OLD_SOURCE_LOOP, _NEW_SOURCE_LOOP
        )
        _PATCHED.add(resolved)
        print(
            "STABLECOIN_V5_EXACT_AVAILABILITY_BATCH_PREFETCH_APPLIED",
            json.dumps(
                {
                    "path": str(resolved),
                    "correction_id": CORRECTION_ID,
                    "batch_size": 40,
                    "old_count": old_count,
                    "new_count": new_count,
                    "exact_timestamp_semantics_changed": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )


def _patch_entry_time_route(command: list[str]) -> None:
    for value in command:
        path = Path(value)
        if path.name != "run.py" or not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in _PATCHED:
            continue
        old_count, new_count = _replace_exact(resolved, _OLD_ROUTE, _NEW_ROUTE)
        _PATCHED.add(resolved)
        print(
            "STABLECOIN_V5_ENTRY_TIME_ARBITRATION_APPLIED",
            json.dumps(
                {
                    "path": str(resolved),
                    "correction_id": ARBITRATION_CORRECTION_ID,
                    "old_count": old_count,
                    "new_count": new_count,
                    "model_or_payoff_changed": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )


def _combined_patch(command: list[str]) -> None:
    _ORIGINAL_PATCH(command)
    _patch_source_prefetch(command)
    _patch_entry_time_route(command)


def _run_with_arbitration_test(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    log: Path | None = None,
):
    amended = list(command)
    is_internal_economic_pytest = (
        len(amended) >= 3
        and amended[1:3] == ["-m", "pytest"]
        and any(Path(value).name == "test_run.py" for value in amended)
    )
    if is_internal_economic_pytest and str(ARBITRATION_TEST) not in amended:
        amended.append(str(ARBITRATION_TEST))
    return _PRIOR_ORIGINAL_RUN(amended, env=env, check=check, log=log)


def execute(work_dir: Path, publish_dir: Path) -> int:
    _load_corrections()
    prior._patch_materialized_files = _combined_patch
    prior._ORIGINAL_RUN = _run_with_arbitration_test
    return prior.execute(work_dir, publish_dir)


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
        failure = {
            "schema_version": 1,
            "claim_id": "CLM-20260730-STABLECOIN-V5-TAKEOVER-001",
            "original_claim_id": prior.original.CLAIM_ID,
            "status": "EXECUTION_FAILURE_NOT_SCIENTIFIC_RESULT",
            "error_type": type(error).__name__,
            "error": repr(error),
            "traceback": traceback.format_exc(),
            "source_sha": prior.original.v4auth.SOURCE_SHA,
            "strict_sha": prior.original.v4auth.STRICT_SHA,
            "profit_first_correction_id": prior.original.PROFIT_CORRECTION,
            "takeover_execution_correction_id": prior.CORRECTION_ID,
            "takeover_validation_correction_id": prior.VALIDATION_CORRECTION_ID,
            "takeover_deferred_validator_correction_id": (
                prior.DEFERRED_VALIDATOR_CORRECTION_ID
            ),
            "takeover_batch_prefetch_correction_id": CORRECTION_ID,
            "takeover_entry_time_arbitration_correction_id": (
                ARBITRATION_CORRECTION_ID
            ),
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        }
        prior.original.v4auth.write_json(
            publish_dir / "EXECUTION_FAILURE.json", failure
        )
        prior.original.v4auth.freeze_hashes(publish_dir)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
