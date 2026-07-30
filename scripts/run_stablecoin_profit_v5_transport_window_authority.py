from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import run_stablecoin_profit_v5_post_reconstruct_authority as post

ROOT = Path(__file__).resolve().parents[1]
CORRECTION_ID = (
    "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-"
    "BLOCKSCOUT-FIXED-LOG-WINDOWS-014"
)
CORRECTION_PATH = (
    ROOT
    / "research"
    / "execution"
    / "stablecoin_profit_v5_20260727"
    / "EXECUTION_CORRECTION_014_BLOCKSCOUT_FIXED_LOG_WINDOWS_AFTER_TRANSPORT_FAILURE.json"
)
MAX_LOG_WINDOW_BLOCKS = 20_000
_ORIGINAL_SOURCE_PREFETCH_REPAIR = post.prior.repair_materialized_source_prefetch

_LOG_QUERY_OLD = '''                logs = client.logs(
                    spec["address"],
                    direction,
                    period["start_block"],
                    period["end_block"],
                    chunks,
                )
'''

_LOG_QUERY_NEW = '''                logs: list[dict[str, Any]] = []
                window_start = int(period["start_block"])
                period_end_block = int(period["end_block"])
                while window_start <= period_end_block:
                    window_end = min(
                        period_end_block,
                        window_start + 19_999,
                    )
                    logs.extend(
                        client.logs(
                            spec["address"],
                            direction,
                            window_start,
                            window_end,
                            chunks,
                        )
                    )
                    window_start = window_end + 1
'''


def _load_correction() -> dict[str, Any]:
    payload = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    if payload.get("correction_id") != CORRECTION_ID:
        raise AssertionError("transport-window correction identity changed")
    if payload.get("claim_id") != post.prior.REPAIR_CLAIM_ID:
        raise AssertionError("transport-window correction claim changed")
    if payload.get("timing") != (
        "AFTER_DURABLE_TRANSPORT_FAILURE_BEFORE_ANY_SOURCE_PASS_FAIL_"
        "MARKET_ROW_LABEL_MODEL_TRADE_PNL_OR_OFFICIAL_INTERVAL"
    ):
        raise AssertionError("transport-window correction timing changed")
    observed = payload.get("observed_run", {})
    if observed.get("status") != "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE":
        raise AssertionError("transport correction does not follow a transport failure")
    if observed.get("source_pass_fail_observed") is not False:
        raise AssertionError("source PASS/FAIL was observed before transport repair")
    for key in (
        "market_archive_opened",
        "label_computed",
        "model_fitted",
        "trade_or_pnl_opened",
        "official_2024_2026_opened",
        "credentials_used",
        "orders_submitted",
    ):
        if observed.get(key) is not False:
            raise AssertionError(f"transport correction outcome seal failed: {key}")
    correction = payload.get("transport_correction", {})
    if correction.get("maximum_contiguous_log_window_blocks") != MAX_LOG_WINDOW_BLOCKS:
        raise AssertionError("fixed Blockscout log-window size changed")
    return payload


def apply_fixed_log_windows(path: Path) -> Path:
    """Partition only source transport ranges; preserve filters and event semantics."""
    _load_correction()
    post.prior._replace_exact(path, _LOG_QUERY_OLD, _LOG_QUERY_NEW)
    return path


def repair_materialized_source_transport(repository: Path) -> Path:
    path = _ORIGINAL_SOURCE_PREFETCH_REPAIR(repository)
    repaired = apply_fixed_log_windows(path)
    print(
        "STABLECOIN_V5_BLOCKSCOUT_FIXED_LOG_WINDOWS_APPLIED",
        json.dumps(
            {
                "correction_id": CORRECTION_ID,
                "path": str(repaired),
                "maximum_contiguous_log_window_blocks": MAX_LOG_WINDOW_BLOCKS,
                "source_event_or_filter_changed": False,
                "scientific_contract_changed": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return repaired


def main() -> int:
    _load_correction()
    original = post.prior.repair_materialized_source_prefetch
    post.prior.repair_materialized_source_prefetch = (
        repair_materialized_source_transport
    )
    try:
        return post.main()
    finally:
        post.prior.repair_materialized_source_prefetch = original


if __name__ == "__main__":
    raise SystemExit(main())
