from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import probe_gmx_v1_liquidations as base

ORIGINAL_DECODE = base.decode_liquidation_log
SEMANTIC_CORRECTION_ID = (
    "CORRECTION-20260727-ML-GMX-V1-POOL-ACCOUNTING-NOT-CLOB-FLOW-001"
)


def decode_liquidation_log(
    log: dict[str, Any], *, block_timestamp: int, probe_window: str
) -> dict[str, Any]:
    """Decode a finalized position deletion without inventing a market order."""
    row = ORIGINAL_DECODE(
        log,
        block_timestamp=block_timestamp,
        probe_window=probe_window,
    )
    row.pop("forced_flow_direction", None)
    is_long = row["liquidated_position_side"] == "LONG"
    size_raw = int(row["size_raw_1e30"])
    row.update(
        {
            "source_semantic_correction": SEMANTIC_CORRECTION_ID,
            "removed_trader_exposure": "LONG_REMOVED" if is_long else "SHORT_REMOVED",
            "signed_removed_exposure_raw_1e30": str(-size_raw if is_long else size_raw),
            "external_market_order_direction_asserted": False,
            "source_censoring": "LIQUIDATION_STATE_1_ONLY",
            "mark_price_semantics": (
                "GMX_VAULT_ORACLE_ACCOUNTING_MARK_NOT_EXTERNAL_EXECUTABLE_FILL"
            ),
        }
    )
    return row


# The base source-gate main resolves this global at execution time.
base.decode_liquidation_log = decode_liquidation_log


def self_test() -> None:
    def address_word(value: str) -> bytes:
        return bytes.fromhex(base.normalize_address(value)[2:]).rjust(32, b"\x00")

    words = [
        bytes.fromhex("11" * 32),
        address_word("0x1111111111111111111111111111111111111111"),
        address_word("0x2222222222222222222222222222222222222222"),
        address_word(base.INDEX_TOKENS["BTC"]),
        (1).to_bytes(32, "big"),
        (1_250 * 10**30).to_bytes(32, "big"),
        (125 * 10**30).to_bytes(32, "big"),
        (987654321).to_bytes(32, "big"),
        (-5 * 10**30).to_bytes(32, "big", signed=True),
        (29_500 * 10**30).to_bytes(32, "big"),
    ]
    log = {
        "address": base.VAULT,
        "topics": [base.LIQUIDATE_POSITION_TOPIC],
        "data": "0x" + b"".join(words).hex(),
        "blockNumber": "0x64",
        "blockHash": "0x" + "22" * 32,
        "transactionHash": "0x" + "33" * 32,
        "transactionIndex": "0x2",
        "logIndex": "0x3",
        "removed": False,
    }
    row = decode_liquidation_log(
        log,
        block_timestamp=1_650_000_000,
        probe_window="self-test",
    )
    assert row["removed_trader_exposure"] == "LONG_REMOVED"
    assert int(row["signed_removed_exposure_raw_1e30"]) < 0
    assert row["external_market_order_direction_asserted"] is False
    assert "forced_flow_direction" not in row
    assert row["source_censoring"] == "LIQUIDATION_STATE_1_ONLY"
    print("GMX_V1_SEMANTIC_CORRECTION_SELF_TEST_PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        raise SystemExit("--output is required")
    # Reuse the exact outcome-sealed base CLI after patching event semantics.
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
