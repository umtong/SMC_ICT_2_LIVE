from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

import run_stablecoin_profit_v5_single_pass_authority as original

ROOT = Path(__file__).resolve().parents[1]
CORRECTION_ID = (
    "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-"
    "PINNED-SELFTEST-ALIAS-AND-FAILURE-PATH-007"
)
VALIDATION_CORRECTION_ID = (
    "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-"
    "STRICT-VALIDATION-CONTRACT-ALIGNMENT-008"
)
CORRECTION_ROOT = ROOT / "research" / "execution" / "stablecoin_profit_v5_20260727"
CORRECTION_FILE = (
    CORRECTION_ROOT
    / "EXECUTION_CORRECTION_007_PINNED_SELFTEST_ALIAS_AND_FAILURE_PATH_BEFORE_OUTCOME.json"
)
VALIDATION_CORRECTION_FILE = (
    CORRECTION_ROOT
    / "EXECUTION_CORRECTION_008_STRICT_VALIDATION_CONTRACT_ALIGNMENT_BEFORE_OUTCOME.json"
)
_SELF_TEST_REPLACEMENTS = (
    ("authority.base.decode_log(", "authority.base.auth.decode_log(", 1),
    ("authority.base.CONTRACTS", "authority.base.auth.CONTRACTS", 2),
    ("authority.base.ISSUE_TOPIC", "authority.base.auth.ISSUE_TOPIC", 1),
)
_OLD_CAUSAL_TEST = '''    entry_index = int(rows.iloc[0]["entry_index"])
    assert int(rows.iloc[0]["completed_feature_index"]) == entry_index - 1
'''
_NEW_CAUSAL_TEST = '''    entry_index = int(rows.iloc[0]["entry_index"])
    decision_ms = int(rows.iloc[0]["decision_ms"])
    times = base_frame["open_time_ms"].to_numpy(np.int64)
    expected_completed = int(
        np.searchsorted(times + 60_000, decision_ms, side="right") - 1
    )
    assert int(rows.iloc[0]["completed_feature_index"]) == expected_completed
    assert expected_completed < entry_index
'''
_OLD_GAP_SELF_TEST = '''    gap_trade = strict_trade_from_row(
        changed_row,
        0.99,
        24.0,
'''
_NEW_GAP_SELF_TEST = '''    gap_trade = strict_trade_from_row(
        changed_row,
        1.0,
        24.0,
'''
_ORIGINAL_RUN = original.v4auth.run
_PATCHED_PATHS: set[Path] = set()


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
        VALIDATION_CORRECTION_FILE, VALIDATION_CORRECTION_ID
    )


def _replace_exact(
    path: Path,
    old: str,
    new: str,
    expected_old: int,
    expected_new: int,
) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == expected_old and new_count == 0:
        path.write_text(text.replace(old, new), encoding="utf-8")
    elif old_count == 0 and new_count == expected_new:
        pass
    else:
        raise RuntimeError(
            "unexpected materialized validation identity: "
            f"old_count={old_count}, new_count={new_count}, "
            f"expected_old={expected_old}, expected_new={expected_new}, path={path}"
        )
    return old_count, new_count


def _patch_materialized_files(command: list[str]) -> None:
    candidates = [Path(value) for value in command if Path(value).is_file()]
    for path in candidates:
        resolved = path.resolve()
        if resolved in _PATCHED_PATHS:
            continue
        counts: dict[str, Any] = {}
        applied_id: str | None = None
        if path.name == "run_pinned_snapshot_source.py":
            for old, new, expected in _SELF_TEST_REPLACEMENTS:
                old_count, new_count = _replace_exact(
                    resolved, old, new, expected, expected
                )
                counts[old] = {
                    "old": old_count,
                    "new": new_count,
                    "expected": expected,
                }
            applied_id = CORRECTION_ID
        elif path.name == "test_run_causal.py":
            old_count, new_count = _replace_exact(
                resolved, _OLD_CAUSAL_TEST, _NEW_CAUSAL_TEST, 1, 1
            )
            counts["source_decision_completed_bar_assertion"] = {
                "old": old_count,
                "new": new_count,
            }
            applied_id = VALIDATION_CORRECTION_ID
        elif path.name == "strict_guard.py":
            old_count, new_count = _replace_exact(
                resolved, _OLD_GAP_SELF_TEST, _NEW_GAP_SELF_TEST, 1, 1
            )
            counts["positive_ev_synthetic_gap_probability"] = {
                "old": old_count,
                "new": new_count,
            }
            applied_id = VALIDATION_CORRECTION_ID
        if applied_id is None:
            continue
        _PATCHED_PATHS.add(resolved)
        print(
            "STABLECOIN_V5_TAKEOVER_COMPATIBILITY_APPLIED",
            json.dumps(
                {
                    "path": str(resolved),
                    "correction_id": applied_id,
                    "replacement_counts": counts,
                    "production_scientific_behavior_changed": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )


def _patched_run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    log: Path | None = None,
):
    _patch_materialized_files(command)
    return _ORIGINAL_RUN(command, env=env, check=check, log=log)


def execute(work_dir: Path, publish_dir: Path) -> int:
    _load_corrections()
    original.v4auth.run = _patched_run
    return original.execute(work_dir, publish_dir)


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
            "original_claim_id": original.CLAIM_ID,
            "status": "EXECUTION_FAILURE_NOT_SCIENTIFIC_RESULT",
            "error_type": type(error).__name__,
            "error": repr(error),
            "traceback": traceback.format_exc(),
            "source_sha": original.v4auth.SOURCE_SHA,
            "strict_sha": original.v4auth.STRICT_SHA,
            "profit_first_correction_id": original.PROFIT_CORRECTION,
            "takeover_execution_correction_id": CORRECTION_ID,
            "takeover_validation_correction_id": VALIDATION_CORRECTION_ID,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        }
        original.v4auth.write_json(publish_dir / "EXECUTION_FAILURE.json", failure)
        original.v4auth.freeze_hashes(publish_dir)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
