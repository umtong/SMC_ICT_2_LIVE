from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import source_gate_blockscout as base

source_gate = base.source_gate
parse_int = base.parse_int
parse_iso_timestamp = base.parse_iso_timestamp


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

    fake = {
        "address": base.auth.CONTRACTS["USDT"]["address"],
        "topics": [
            base.auth.TRANSFER_TOPIC,
            base.auth.ZERO_TOPIC,
            "0x" + "0" * 24 + "12" * 20,
        ],
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
    print("authoritative Blockscout source self-test passed")


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
