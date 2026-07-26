from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import source_gate as base


# Canonical Ethereum event identities. USDT's verified TetherToken contract does
# not emit zero-address ERC20 Transfer logs from issue() or redeem().
ISSUE_TOPIC = "0xcb8241adb0c3fdb35b70c24ce35c5eb0c17af7431c99f827d44a445ca624176a"
REDEEM_TOPIC = "0x702d5967f45f6513a38ffc42d6ba9bf230bd40e8f53b16363c7eb4fd2deb9a44"
ZERO_ADDRESS = "0x" + "0" * 40
ORIGINAL_DECODE_LOG = base.decode_log


def eligibility_safe_boundary(block_number: int, target_timestamp: int) -> int:
    """Exclude events whose +64-block stress confirmation enters 2024."""
    if target_timestamp == base.MAX_ALLOWED_TIMESTAMP:
        if block_number < 64:
            raise ValueError("invalid 2024 boundary block")
        return block_number - 64
    return block_number


def first_block_at_or_after(
    client: base.RpcClient,
    target_timestamp: int,
    low: int,
    high: int,
    cache: dict[int, int],
) -> int:
    """Locate a permitted source boundary without requesting post-boundary data."""
    if target_timestamp > base.MAX_ALLOWED_TIMESTAMP:
        raise ValueError("timestamps after the 2024 boundary are prohibited")
    if base.block_timestamp(client, low, cache) >= target_timestamp:
        return eligibility_safe_boundary(low, target_timestamp)
    if base.block_timestamp(client, high, cache) < target_timestamp:
        raise base.RpcError("latest block predates requested target")
    while low + 1 < high:
        mid = (low + high) // 2
        if base.block_timestamp(client, mid, cache) >= target_timestamp:
            high = mid
        else:
            low = mid
    return eligibility_safe_boundary(high, target_timestamp)


def event_filter_topics(token: str, direction: str) -> list[Any]:
    """Return the token-specific canonical supply-event filter."""
    if token == "USDT":
        if direction == "MINT":
            return [ISSUE_TOPIC]
        if direction == "BURN":
            return [REDEEM_TOPIC]
        raise ValueError(direction)
    if token == "USDC":
        if direction == "MINT":
            return [base.TRANSFER_TOPIC, base.ZERO_TOPIC]
        if direction == "BURN":
            return [base.TRANSFER_TOPIC, None, base.ZERO_TOPIC]
        raise ValueError(direction)
    raise ValueError(f"unsupported token {token}")


def _nonempty_topics(log: dict[str, Any]) -> list[str]:
    """Normalize provider padding without admitting a genuine indexed topic.

    Blockscout may serialize non-indexed events with null or empty trailing topic
    placeholders. Those carry no event information. Any nonempty additional topic
    remains visible and will cause the exact Issue/Redeem identity check to fail.
    """
    raw_topics = log.get("topics")
    if not isinstance(raw_topics, list):
        raise ValueError("event topics must be a list")
    normalized: list[str] = []
    for value in raw_topics:
        if value is None:
            continue
        text = str(value).strip().lower()
        if text in {"", "0x"}:
            continue
        normalized.append(text)
    return normalized


def decode_log(token: str, direction: str, log: dict[str, Any]) -> dict[str, Any]:
    """Decode canonical USDT Issue/Redeem or USDC zero-address Transfer."""
    contract = str(log["address"]).lower()
    expected = base.CONTRACTS[token]["address"].lower()
    if contract != expected:
        raise ValueError(f"contract mismatch {contract} != {expected}")

    if token == "USDC":
        return ORIGINAL_DECODE_LOG(token, direction, log)
    if token != "USDT":
        raise ValueError(f"unsupported token {token}")

    expected_topic = ISSUE_TOPIC if direction == "MINT" else REDEEM_TOPIC if direction == "BURN" else None
    if expected_topic is None:
        raise ValueError(direction)
    topics = _nonempty_topics(log)
    # Issue/Redeem carry only a non-indexed uint256 amount. Provider null/empty
    # padding is ignored, but every genuine additional nonempty topic is rejected.
    if topics != [expected_topic]:
        raise ValueError(
            f"USDT {direction} event must contain exactly canonical topic0; observed={topics!r}"
        )
    amount_raw = int(log.get("data", "0x0"), 16)
    if amount_raw <= 0:
        raise ValueError("USDT supply-event amount must be positive")

    return {
        "token": token,
        "direction": direction,
        "contract": contract,
        "block_number": int(log["blockNumber"], 16),
        "tx_hash": str(log["transactionHash"]).lower(),
        "log_index": int(log["logIndex"], 16),
        "amount_raw": amount_raw,
        "amount_usd": amount_raw / (10 ** int(base.CONTRACTS[token]["decimals"])),
        # Tether Issue/Redeem do not expose the owner address in indexed
        # parameters. Contract-address sentinels preserve signed supply flow
        # without inventing a recipient or burner identity.
        "from_address": ZERO_ADDRESS if direction == "MINT" else contract,
        "to_address": contract if direction == "MINT" else ZERO_ADDRESS,
    }


# Patch the authority helpers used by the Blockscout transport. The original
# generic RPC source routine remains intentionally unused because its internal
# filter loop predates token-specific event schemas.
base.first_block_at_or_after = first_block_at_or_after
base.decode_log = decode_log

CONTRACTS = base.CONTRACTS
FIXED_MONTHS = base.FIXED_MONTHS
TRANSFER_TOPIC = base.TRANSFER_TOPIC
ZERO_TOPIC = base.ZERO_TOPIC
Event = base.Event
event_to_dict = base.event_to_dict
month_bounds = base.month_bounds
normalize_address_topic = base.normalize_address_topic


def source_gate(
    output: Path,
    endpoints: Iterable[str] = base.DEFAULT_ENDPOINTS,
    fixed_months: Iterable[str] = FIXED_MONTHS,
) -> dict[str, Any]:
    del output, endpoints, fixed_months
    raise RuntimeError(
        "generic RPC source transport is disabled after the token-specific "
        "USDT Issue/Redeem correction; use source_gate_blockscout_authoritative.py"
    )


def self_test() -> None:
    class FakeClient:
        def __init__(self, timestamps: dict[int, int]) -> None:
            self.timestamps = timestamps

        def call(self, method: str, params: list[object]) -> dict[str, str]:
            if method != "eth_getBlockByNumber":
                raise AssertionError(method)
            number = int(str(params[0]), 16)
            return {"timestamp": hex(self.timestamps[number])}

    boundary = base.MAX_ALLOWED_TIMESTAMP
    timestamps = {i: boundary - (100 - i) * 12 for i in range(101)}
    fake = FakeClient(timestamps)
    if first_block_at_or_after(fake, boundary, 0, 100, {}) != 36:
        raise AssertionError("64-block pre-2024 eligibility boundary failed")
    if first_block_at_or_after(fake, boundary - 120, 0, 100, {}) != 90:
        raise AssertionError("ordinary historical boundary was altered")
    try:
        first_block_at_or_after(fake, boundary + 1, 0, 100, {})
    except ValueError:
        pass
    else:
        raise AssertionError("post-2024 timestamp was not rejected")

    issue = {
        "address": CONTRACTS["USDT"]["address"],
        "topics": [ISSUE_TOPIC],
        "data": hex(125_000_000 * 10**6),
        "blockNumber": "0x10",
        "transactionHash": "0x" + "ab" * 32,
        "logIndex": "0x2",
    }
    issue_row = decode_log("USDT", "MINT", issue)
    if issue_row["amount_usd"] != 125_000_000 or issue_row["from_address"] != ZERO_ADDRESS:
        raise AssertionError(issue_row)

    padded_issue = dict(issue)
    padded_issue["topics"] = [ISSUE_TOPIC, None, "", "0x"]
    if decode_log("USDT", "MINT", padded_issue)["amount_usd"] != 125_000_000:
        raise AssertionError("provider topic padding was not normalized")

    redeem = dict(issue)
    redeem["topics"] = [REDEEM_TOPIC]
    redeem["transactionHash"] = "0x" + "cd" * 32
    redeem_row = decode_log("USDT", "BURN", redeem)
    if redeem_row["amount_usd"] != 125_000_000 or redeem_row["to_address"] != ZERO_ADDRESS:
        raise AssertionError(redeem_row)

    ordinary_transfer = dict(issue)
    ordinary_transfer["topics"] = [
        TRANSFER_TOPIC,
        ZERO_TOPIC,
        "0x" + "0" * 24 + "12" * 20,
    ]
    try:
        decode_log("USDT", "MINT", ordinary_transfer)
    except ValueError:
        pass
    else:
        raise AssertionError("ordinary USDT Transfer was accepted as issuance")

    genuine_extra = dict(issue)
    genuine_extra["topics"] = [ISSUE_TOPIC, ZERO_TOPIC]
    try:
        decode_log("USDT", "MINT", genuine_extra)
    except ValueError:
        pass
    else:
        raise AssertionError("genuine indexed topic was treated as provider padding")

    expected = int(datetime(2023, 7, 3, 20, 9, 59, tzinfo=timezone.utc).timestamp())
    if expected != 1_688_414_999:
        raise AssertionError(expected)
    print("authoritative token-specific source self-test passed")


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
    result = source_gate(args.output, endpoints=tuple(args.endpoint) if args.endpoint else base.DEFAULT_ENDPOINTS)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
