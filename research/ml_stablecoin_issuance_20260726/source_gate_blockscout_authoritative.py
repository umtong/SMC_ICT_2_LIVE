from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import source_gate_blockscout as base

OriginalBlockscoutClient = base.BlockscoutClient
AUTHORITATIVE_MIN_REQUEST_INTERVAL_SECONDS = 0.36
SOURCE_SCHEMA_ID = "STABLECOIN_SUPPLY_USDT_ISSUE_REDEEM_USDC_ZERO_TRANSFER_V1"
SOURCE_CORRECTION_ID = "CORRECTION-20260726-ML-STABLECOIN-USDT-ISSUE-REDEEM-010"
# Blockscout's default unauthenticated allowance is approximately three requests
# per second. The authoritative source route stays below that rate.
base.MIN_REQUEST_INTERVAL_SECONDS = AUTHORITATIVE_MIN_REQUEST_INTERVAL_SECONDS


def eligible_boundary_block(block_number: int, timestamp: int, closest: str) -> int:
    """Return the end-exclusive source block under the 64-block stress seal."""
    if timestamp == base.auth.base.MAX_ALLOWED_TIMESTAMP and closest == "after":
        if block_number < 64:
            raise ValueError("invalid 2024 boundary block")
        return block_number - 64
    return block_number


class BoundarySafeBlockscoutClient(OriginalBlockscoutClient):
    def block_by_time(self, timestamp: int, closest: str) -> int:
        observed = super().block_by_time(timestamp, closest)
        return eligible_boundary_block(observed, timestamp, closest)

    def _log_params(
        self,
        address: str,
        direction: str,
        start_block: int,
        end_block: int,
    ) -> dict[str, Any]:
        # USDT supply changes are canonical Issue/Redeem events, not
        # zero-address Transfer logs. USDC retains Circle FiatToken's ERC20
        # zero-address Transfer semantics.
        if address.lower() != base.auth.CONTRACTS["USDT"]["address"].lower():
            return super()._log_params(address, direction, start_block, end_block)
        topics = base.auth.event_filter_topics("USDT", direction)
        return {
            "module": "logs",
            "action": "getLogs",
            "fromBlock": start_block,
            "toBlock": end_block,
            "address": address,
            "topic0": topics[0],
        }


# Resolve these globals at source-gate execution time.
base.BlockscoutClient = BoundarySafeBlockscoutClient
_base_source_gate = base.source_gate
parse_int = base.parse_int
parse_iso_timestamp = base.parse_iso_timestamp


def source_gate(output: Path) -> dict[str, Any]:
    """Run the corrected gate and bind its token-specific schema to the artifact."""
    result = _base_source_gate(output)
    manifest_path = output / "SOURCE_MANIFEST.json"
    result_path = output / "SOURCE_GATE_RESULT.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    event_semantics = {
        "USDT_MINT": "Issue(uint256)",
        "USDT_BURN": "Redeem(uint256)",
        "USDC_MINT": "Transfer(address,address,uint256) with from zero address",
        "USDC_BURN": "Transfer(address,address,uint256) with to zero address",
        "ordinary_usdt_transfer_excluded": True,
    }
    binding = {
        "source_schema_id": SOURCE_SCHEMA_ID,
        "source_correction_id": SOURCE_CORRECTION_ID,
        "event_semantics": event_semantics,
    }
    manifest.update(binding)
    result.update(binding)

    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def self_test() -> None:
    if parse_int("0x10") != 16 or parse_int("16") != 16:
        raise AssertionError("integer parsing failed")
    expected = int(datetime(2023, 7, 3, 20, 9, 59, tzinfo=timezone.utc).timestamp())
    if expected != 1_688_414_999:
        raise AssertionError(expected)
    if parse_iso_timestamp("2023-07-03T20:09:59.000000Z") != expected:
        raise AssertionError("ISO timestamp parsing failed")
    if len(base.auth.FIXED_MONTHS) != 36:
        raise AssertionError("full 2021-2023 month contract missing")
    if base.MIN_REQUEST_INTERVAL_SECONDS != AUTHORITATIVE_MIN_REQUEST_INTERVAL_SECONDS:
        raise AssertionError("authoritative Blockscout request pace is not frozen")
    if SOURCE_SCHEMA_ID != "STABLECOIN_SUPPLY_USDT_ISSUE_REDEEM_USDC_ZERO_TRANSFER_V1":
        raise AssertionError("source schema binding changed")
    boundary = base.auth.base.MAX_ALLOWED_TIMESTAMP
    if eligible_boundary_block(18_000_000, boundary, "after") != 17_999_936:
        raise AssertionError("64-block pre-2024 boundary was not applied")
    if eligible_boundary_block(18_000_000, boundary - 1, "after") != 18_000_000:
        raise AssertionError("non-boundary block was altered")

    client = BoundarySafeBlockscoutClient()
    issue_params = client._log_params(
        base.auth.CONTRACTS["USDT"]["address"], "MINT", 10, 20
    )
    if issue_params.get("topic0") != base.auth.ISSUE_TOPIC:
        raise AssertionError(issue_params)
    if "topic1" in issue_params or "topic2" in issue_params:
        raise AssertionError("USDT Issue query incorrectly imposed address topics")
    redeem_params = client._log_params(
        base.auth.CONTRACTS["USDT"]["address"], "BURN", 10, 20
    )
    if redeem_params.get("topic0") != base.auth.REDEEM_TOPIC:
        raise AssertionError(redeem_params)
    usdc_params = client._log_params(
        base.auth.CONTRACTS["USDC"]["address"], "MINT", 10, 20
    )
    if usdc_params.get("topic0") != base.auth.TRANSFER_TOPIC or usdc_params.get("topic1") != base.auth.ZERO_TOPIC:
        raise AssertionError(usdc_params)

    fake = {
        "address": base.auth.CONTRACTS["USDT"]["address"],
        "topics": [base.auth.ISSUE_TOPIC, None, "", "0x"],
        "data": hex(1_000_000 * 10**6),
        "blockNumber": "0x10",
        "transactionHash": "0x" + "ab" * 32,
        "logIndex": "0x2",
        "timeStamp": hex(expected),
    }
    row = base.auth.decode_log("USDT", "MINT", fake)
    if row["amount_usd"] != 1_000_000:
        raise AssertionError(row["amount_usd"])
    if base.log_timestamp(fake) != expected:
        raise AssertionError("log timestamp parsing failed")

    ordinary = dict(fake)
    ordinary["topics"] = [
        base.auth.TRANSFER_TOPIC,
        base.auth.ZERO_TOPIC,
        "0x" + "0" * 24 + "12" * 20,
    ]
    try:
        base.auth.decode_log("USDT", "MINT", ordinary)
    except ValueError:
        pass
    else:
        raise AssertionError("ordinary USDT Transfer accepted as Issue")

    print("authoritative boundary-safe token-specific Blockscout self-test passed")


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
    result = source_gate(args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
