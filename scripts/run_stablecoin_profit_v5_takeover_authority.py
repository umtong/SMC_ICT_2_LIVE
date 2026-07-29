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
CORRECTION_FILE = (
    ROOT
    / "research"
    / "execution"
    / "stablecoin_profit_v5_20260727"
    / "EXECUTION_CORRECTION_007_PINNED_SELFTEST_ALIAS_AND_FAILURE_PATH_BEFORE_OUTCOME.json"
)
_SELF_TEST_REPLACEMENTS = (
    ("authority.base.decode_log(", "authority.base.auth.decode_log(", 1),
    ("authority.base.CONTRACTS", "authority.base.auth.CONTRACTS", 2),
    ("authority.base.ISSUE_TOPIC", "authority.base.auth.ISSUE_TOPIC", 1),
)
_ORIGINAL_RUN = original.v4auth.run
_PATCHED_PATHS: set[Path] = set()


def _load_correction() -> dict[str, Any]:
    value = json.loads(CORRECTION_FILE.read_text(encoding="utf-8"))
    if value.get("correction_id") != CORRECTION_ID:
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


def _patch_materialized_self_test(command: list[str]) -> None:
    for value in command:
        path = Path(value)
        if path.name != "run_pinned_snapshot_source.py" or not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in _PATCHED_PATHS:
            continue
        text = resolved.read_text(encoding="utf-8")
        counts: dict[str, dict[str, int]] = {}
        for old, new, expected in _SELF_TEST_REPLACEMENTS:
            old_count = text.count(old)
            new_count = text.count(new)
            counts[old] = {"old": old_count, "new": new_count, "expected": expected}
            if old_count == expected and new_count == 0:
                text = text.replace(old, new)
            elif old_count == 0 and new_count == expected:
                pass
            else:
                raise RuntimeError(
                    "unexpected pinned-source self-test identity: "
                    f"old={old!r}, old_count={old_count}, "
                    f"new_count={new_count}, expected={expected}, path={resolved}"
                )
        resolved.write_text(text, encoding="utf-8")
        _PATCHED_PATHS.add(resolved)
        print(
            "STABLECOIN_V5_TAKEOVER_SELFTEST_COMPATIBILITY_APPLIED",
            json.dumps(
                {
                    "path": str(resolved),
                    "correction_id": CORRECTION_ID,
                    "replacement_counts": counts,
                    "scientific_source_execution_changed": False,
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
    _patch_materialized_self_test(command)
    return _ORIGINAL_RUN(command, env=env, check=check, log=log)


def execute(work_dir: Path, publish_dir: Path) -> int:
    _load_correction()
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
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        }
        original.v4auth.write_json(publish_dir / "EXECUTION_FAILURE.json", failure)
        original.v4auth.freeze_hashes(publish_dir)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
