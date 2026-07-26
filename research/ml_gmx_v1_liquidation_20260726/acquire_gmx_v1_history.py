from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import probe_gmx_v1_liquidations as base
import probe_gmx_v1_liquidations_semantic as semantic

START_UTC = "2021-09-01T00:00:00Z"
END_EXCLUSIVE_UTC = "2024-01-01T00:00:00Z"
HISTORY_ID = "DS-GMX-V1-ARBITRUM-LIQUIDATEPOSITION-202109-202312-R1"


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def acquire(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    rpc, endpoint_probe, locator = base.choose_endpoint(base.ENDPOINTS)
    start_block = locator.first_at_or_after(base.parse_utc(START_UTC))
    end_exclusive_block = locator.first_at_or_after(base.parse_utc(END_EXCLUSIVE_UTC))
    logs = base.get_logs_adaptive(
        rpc,
        address=base.VAULT,
        from_block=start_block,
        to_block=end_exclusive_block - 1,
        topic0=base.LIQUIDATE_POSITION_TOPIC,
    )
    blocks = sorted({base.hex_int(log["blockNumber"]) for log in logs})
    timestamps = rpc.batch_block_timestamps(blocks)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for log in logs:
        number = base.hex_int(log["blockNumber"])
        try:
            row = semantic.decode_liquidation_log(
                log,
                block_timestamp=timestamps[number],
                probe_window="FULL_PRE2024_HISTORY",
            )
            if row["removed"]:
                raise ValueError("removed log")
            rows.append(row)
        except Exception as exc:
            errors.append(
                {
                    "block_number": number,
                    "transaction_hash": str(log.get("transactionHash", "")).lower(),
                    "log_index": str(log.get("logIndex", "")),
                    "error": repr(exc),
                }
            )
    identities = [
        (row["block_hash"], row["transaction_hash"], int(row["log_index"]))
        for row in rows
    ]
    duplicate_count = len(identities) - len(set(identities))
    rows = [row for row in rows if row["asset"] in {"BTC", "ETH"}]
    rows.sort(
        key=lambda row: (
            row["block_timestamp"],
            row["transaction_index"],
            row["log_index"],
        )
    )
    months = sorted({row["block_time_utc"][:7] for row in rows})
    assets: dict[str, int] = {}
    sides: dict[str, int] = {}
    for row in rows:
        assets[row["asset"]] = assets.get(row["asset"], 0) + 1
        sides[row["removed_trader_exposure"]] = (
            sides.get(row["removed_trader_exposure"], 0) + 1
        )

    history_path = output / "GMX_V1_LIQUIDATIONS_202109_202312.jsonl.gz"
    with gzip.open(history_path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            )

    checks = {
        "zero_decode_errors": len(errors) == 0,
        "zero_duplicate_identities": duplicate_count == 0,
        "both_assets": set(assets) == {"BTC", "ETH"},
        "both_removed_sides": set(sides) == {"LONG_REMOVED", "SHORT_REMOVED"},
        "minimum_events_120": len(rows) >= 120,
        "minimum_event_bearing_months_18": len(months) >= 18,
        "causal_delay_120_seconds": all(
            int(row["causal_available_timestamp"])
            - int(row["block_timestamp"])
            == 120
            for row in rows
        ),
        "no_external_market_order_assertion": all(
            row.get("external_market_order_direction_asserted") is False
            for row in rows
        ),
    }
    result = {
        "schema_version": 1,
        "claim_id": base.CLAIM_ID,
        "dataset_id": HISTORY_ID,
        "purpose": (
            "Conditional full pre-2024 source materialization after the frozen "
            "source gate passes; no market outcome."
        ),
        "start_utc": START_UTC,
        "end_exclusive_utc": END_EXCLUSIVE_UTC,
        "start_block": start_block,
        "end_exclusive_block": end_exclusive_block,
        "endpoint_probe": endpoint_probe,
        "event_signature": base.LIQUIDATE_POSITION_SIGNATURE,
        "event_topic0": base.LIQUIDATE_POSITION_TOPIC,
        "information_delay_seconds": base.INFORMATION_DELAY_SECONDS,
        "raw_log_count": len(logs),
        "btc_eth_event_count": len(rows),
        "event_bearing_months": months,
        "assets": assets,
        "removed_sides": sides,
        "duplicate_count": duplicate_count,
        "decode_errors": errors,
        "history_checks": checks,
        "history_pass": all(checks.values()),
        "history_file": history_path.name,
        "history_sha256": _digest(history_path),
        "rpc_stats": vars(rpc.stats),
        "orders_submitted": False,
        "official_2024_2026_opened": False,
    }
    (output / "HISTORY_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def self_test() -> None:
    assert base.parse_utc(END_EXCLUSIVE_UTC) > base.parse_utc(START_UTC)
    assert semantic.SEMANTIC_CORRECTION_ID.endswith(
        "POOL-ACCOUNTING-NOT-CLOB-FLOW-001"
    )
    print("GMX_V1_HISTORY_ACQUISITION_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        raise SystemExit("--output is required")
    result = acquire(args.output)
    print(
        json.dumps(
            {
                "history_pass": result["history_pass"],
                "events": result["btc_eth_event_count"],
                "months": len(result["event_bearing_months"]),
            },
            sort_keys=True,
        )
    )
    return 0 if result["history_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
