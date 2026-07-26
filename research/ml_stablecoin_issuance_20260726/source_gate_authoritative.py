from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import source_gate as base


def first_block_at_or_after(
    client: base.RpcClient,
    target_timestamp: int,
    low: int,
    high: int,
    cache: dict[int, int],
) -> int:
    """Locate the first block at/after a permitted source boundary.

    Exactly 2024-01-01 00:00 UTC is allowed only as the end-exclusive
    boundary for December 2023. Any timestamp after it remains prohibited,
    and base.source_gate still rejects every event at or after the boundary.
    """
    if target_timestamp > base.MAX_ALLOWED_TIMESTAMP:
        raise ValueError("timestamps after the 2024 boundary are prohibited")
    if base.block_timestamp(client, low, cache) >= target_timestamp:
        return low
    if base.block_timestamp(client, high, cache) < target_timestamp:
        raise base.RpcError("latest block predates requested target")
    while low + 1 < high:
        mid = (low + high) // 2
        if base.block_timestamp(client, mid, cache) >= target_timestamp:
            high = mid
        else:
            low = mid
    return high


# Patch the single pre-outcome boundary defect while preserving the base source
# implementation and its exact transport, decoding, identity, density and seal logic.
base.first_block_at_or_after = first_block_at_or_after

CONTRACTS = base.CONTRACTS
FIXED_MONTHS = base.FIXED_MONTHS
TRANSFER_TOPIC = base.TRANSFER_TOPIC
ZERO_TOPIC = base.ZERO_TOPIC
Event = base.Event
decode_log = base.decode_log
event_to_dict = base.event_to_dict
month_bounds = base.month_bounds
normalize_address_topic = base.normalize_address_topic


def source_gate(
    output: Path,
    endpoints: Iterable[str] = base.DEFAULT_ENDPOINTS,
    fixed_months: Iterable[str] = FIXED_MONTHS,
) -> dict[str, Any]:
    return base.source_gate(output, endpoints=endpoints, fixed_months=tuple(fixed_months))


def self_test() -> None:
    base.self_test()

    class FakeClient:
        def __init__(self, timestamps: dict[int, int]) -> None:
            self.timestamps = timestamps

        def call(self, method: str, params: list[object]) -> dict[str, str]:
            if method != "eth_getBlockByNumber":
                raise AssertionError(method)
            number = int(str(params[0]), 16)
            return {"timestamp": hex(self.timestamps[number])}

    boundary = base.MAX_ALLOWED_TIMESTAMP
    fake = FakeClient({0: boundary - 24, 1: boundary - 12, 2: boundary})
    if first_block_at_or_after(fake, boundary, 0, 2, {}) != 2:
        raise AssertionError("exact end-exclusive boundary lookup failed")
    try:
        first_block_at_or_after(fake, boundary + 1, 0, 2, {})
    except ValueError:
        pass
    else:
        raise AssertionError("post-2024 timestamp was not rejected")
    print("authoritative boundary self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--endpoint", action="append", default=[])
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        raise SystemExit("--output is required")
    endpoints = tuple(args.endpoint) if args.endpoint else base.DEFAULT_ENDPOINTS
    result = source_gate(args.output, endpoints=endpoints)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
