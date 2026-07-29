from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests

CLAIM_ID = "CLM-20260726-2110-ML-UNISWAP-HEDGE-TRANSFER-001"
PURPOSE = (
    "Outcome-sealed source gate only. No CEX/DEX market price comparison, future return, "
    "first-passage label, action, trade, PnL, model metric, official 2024-2026 period, "
    "credential, or order path is opened."
)

FACTORY = "0x1f98431c8ad98523631ae4a59f267346ea31f984"
TOKENS = {
    "WETH": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "USDC": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "USDT": "0xdac17f958d2ee523a2206206994597c13d831ec7",
}
POOL_KEYS = (
    ("WETH_USDC_500", "WETH", "USDC", 500),
    ("WETH_USDC_3000", "WETH", "USDC", 3000),
    ("WETH_USDT_500", "WETH", "USDT", 500),
    ("WETH_USDT_3000", "WETH", "USDT", 3000),
)

SWAP_SIGNATURE = "Swap(address,address,int256,int256,uint160,uint128,int24)"
SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
GET_POOL_SELECTOR = bytes.fromhex("1698ee82")
TOKEN0_SELECTOR = "0x0dfe1681"
TOKEN1_SELECTOR = "0xd21220a7"
FEE_SELECTOR = "0xddca3f43"

# Frozen before querying counts. Each window is one UTC hour and remains pre-2024.
PROBE_WINDOWS = (
    ("2021-05-19", 12),
    ("2021-12-04", 12),
    ("2022-05-12", 12),
    ("2022-11-09", 12),
    ("2023-03-11", 12),
    ("2023-08-17", 12),
)

ENDPOINTS = (
    "https://eth-mainnet.public.blastapi.io",
    "https://ethereum-rpc.publicnode.com",
    "https://1rpc.io/eth",
)


class RpcError(RuntimeError):
    pass


@dataclass
class RpcStats:
    calls: int = 0
    retries: int = 0
    errors: int = 0


class RpcClient:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "SMC-ICT-2-Uniswap-source-gate/1.0",
                "Content-Type": "application/json",
            }
        )
        self.counter = 0
        self.stats = RpcStats()

    def call(self, method: str, params: list[Any], *, attempts: int = 5) -> Any:
        self.counter += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.counter,
            "method": method,
            "params": params,
        }
        last_error: Exception | None = None
        for attempt in range(attempts):
            self.stats.calls += 1
            try:
                response = self.session.post(
                    self.endpoint,
                    json=payload,
                    timeout=(15, 60),
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise RpcError(f"HTTP {response.status_code}: {response.text[:300]}")
                response.raise_for_status()
                body = response.json()
                if body.get("error") is not None:
                    raise RpcError(json.dumps(body["error"], sort_keys=True))
                if "result" not in body:
                    raise RpcError(f"missing result: {body!r}")
                return body["result"]
            except Exception as exc:  # endpoint failover evidence is preserved
                last_error = exc
                self.stats.errors += 1
                if attempt + 1 >= attempts:
                    break
                self.stats.retries += 1
                time.sleep(min(8.0, 0.75 * (2**attempt)))
        raise RpcError(f"{method} failed at {self.endpoint}: {last_error!r}")


def normalize_address(value: str) -> str:
    value = value.lower()
    if not value.startswith("0x"):
        value = "0x" + value
    if len(value) != 42:
        raise ValueError(f"invalid address {value}")
    return value


def decode_address_word(value: str) -> str:
    clean = value[2:] if value.startswith("0x") else value
    if len(clean) < 40:
        clean = clean.rjust(64, "0")
    return normalize_address(clean[-40:])


def hex_int(value: str) -> int:
    return int(value, 16)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def abi_address_word(address: str) -> bytes:
    return bytes.fromhex(normalize_address(address)[2:]).rjust(32, b"\x00")


def abi_uint_word(value: int) -> bytes:
    if value < 0:
        raise ValueError("unsigned ABI word cannot be negative")
    return int(value).to_bytes(32, "big", signed=False)


def abi_signed_word(value: int, bits: int = 256) -> bytes:
    lower = -(1 << (bits - 1))
    upper = (1 << (bits - 1)) - 1
    if not lower <= value <= upper:
        raise ValueError(f"signed value {value} outside int{bits}")
    if value < 0:
        value = (1 << 256) + value
    return int(value).to_bytes(32, "big", signed=False)


def decode_signed_word(word: bytes, bits: int = 256) -> int:
    if len(word) != 32:
        raise ValueError("ABI word must be 32 bytes")
    value = int.from_bytes(word, "big", signed=False)
    mask = (1 << bits) - 1
    value &= mask
    if value >= (1 << (bits - 1)):
        value -= 1 << bits
    return value


def get_pool_calldata(token_a: str, token_b: str, fee: int) -> str:
    payload = (
        GET_POOL_SELECTOR
        + abi_address_word(token_a)
        + abi_address_word(token_b)
        + abi_uint_word(int(fee))
    )
    return "0x" + payload.hex()


def one_hour_window(date_text: str, hour: int) -> tuple[int, int]:
    day = dt.date.fromisoformat(date_text)
    start = dt.datetime.combine(
        day, dt.time(hour=hour), tzinfo=dt.timezone.utc
    )
    end = start + dt.timedelta(hours=1)
    return int(start.timestamp()), int(end.timestamp())


class BlockLocator:
    def __init__(self, rpc: RpcClient, latest_block: int) -> None:
        self.rpc = rpc
        self.latest_block = latest_block
        self.cache: dict[int, int] = {}

    def timestamp(self, block_number: int) -> int:
        if block_number not in self.cache:
            block = self.rpc.call("eth_getBlockByNumber", [hex(block_number), False])
            if block is None:
                raise RpcError(f"missing block {block_number}")
            self.cache[block_number] = hex_int(block["timestamp"])
        return self.cache[block_number]

    def first_at_or_after(self, target_timestamp: int) -> int:
        low = 0
        high = self.latest_block
        if self.timestamp(high) < target_timestamp:
            raise RpcError(f"target {target_timestamp} after latest block timestamp")
        while low < high:
            mid = (low + high) // 2
            if self.timestamp(mid) < target_timestamp:
                low = mid + 1
            else:
                high = mid
        return low


def get_logs_adaptive(
    rpc: RpcClient,
    *,
    address: str,
    from_block: int,
    to_block: int,
    topic0: str,
    maximum_chunk: int = 1000,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []

    def query(start: int, end: int) -> None:
        try:
            result = rpc.call(
                "eth_getLogs",
                [
                    {
                        "fromBlock": hex(start),
                        "toBlock": hex(end),
                        "address": normalize_address(address),
                        "topics": [topic0],
                    }
                ],
            )
            if not isinstance(result, list):
                raise RpcError(f"eth_getLogs returned {type(result)!r}")
            output.extend(result)
        except Exception:
            if start >= end:
                raise
            midpoint = (start + end) // 2
            query(start, midpoint)
            query(midpoint + 1, end)

    cursor = from_block
    while cursor <= to_block:
        end = min(to_block, cursor + maximum_chunk - 1)
        query(cursor, end)
        cursor = end + 1
    return output


def decode_swap_log(
    log: dict[str, Any],
    *,
    pool_name: str,
    expected_pool: str,
    token0: str,
    token1: str,
    fee: int,
    block_timestamp: int,
) -> dict[str, Any]:
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) != 3:
        raise ValueError(f"unexpected topic structure: {topics!r}")
    if topics[0].lower() != SWAP_TOPIC.lower():
        raise ValueError(f"unexpected topic0 {topics[0]}")
    if normalize_address(log["address"]) != normalize_address(expected_pool):
        raise ValueError("log address does not match queried pool")

    data_hex = log.get("data", "")
    raw_data = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
    if len(raw_data) != 32 * 5:
        raise ValueError(f"unexpected Swap data length: {len(raw_data)}")
    words = [raw_data[index : index + 32] for index in range(0, len(raw_data), 32)]
    amount0 = decode_signed_word(words[0], 256)
    amount1 = decode_signed_word(words[1], 256)
    sqrt_price_x96 = int.from_bytes(words[2], "big", signed=False)
    liquidity = int.from_bytes(words[3], "big", signed=False)
    tick = decode_signed_word(words[4], 24)
    return {
        "pool_name": pool_name,
        "pool": normalize_address(expected_pool),
        "token0": normalize_address(token0),
        "token1": normalize_address(token1),
        "fee": int(fee),
        "sender": decode_address_word(topics[1]),
        "recipient": decode_address_word(topics[2]),
        "amount0_raw": str(int(amount0)),
        "amount1_raw": str(int(amount1)),
        "sqrt_price_x96": str(int(sqrt_price_x96)),
        "liquidity": str(int(liquidity)),
        "tick": int(tick),
        "block_number": hex_int(log["blockNumber"]),
        "block_hash": log["blockHash"].lower(),
        "block_timestamp": int(block_timestamp),
        "block_time_utc": dt.datetime.fromtimestamp(
            block_timestamp, tz=dt.timezone.utc
        ).isoformat(),
        "transaction_hash": log["transactionHash"].lower(),
        "transaction_index": hex_int(log["transactionIndex"]),
        "log_index": hex_int(log["logIndex"]),
        "removed": bool(log.get("removed", False)),
        "raw_log": log,
    }


def resolve_pools(rpc: RpcClient) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for name, left, right, fee in POOL_KEYS:
        left_addr = TOKENS[left]
        right_addr = TOKENS[right]
        result = rpc.call(
            "eth_call",
            [
                {
                    "to": FACTORY,
                    "data": get_pool_calldata(left_addr, right_addr, fee),
                },
                "latest",
            ],
        )
        pool = decode_address_word(result)
        if pool == "0x0000000000000000000000000000000000000000":
            output[name] = {
                "status": "MISSING",
                "token_a": normalize_address(left_addr),
                "token_b": normalize_address(right_addr),
                "fee": fee,
                "pool": pool,
            }
            continue
        code = rpc.call("eth_getCode", [pool, "latest"])
        token0 = decode_address_word(
            rpc.call("eth_call", [{"to": pool, "data": TOKEN0_SELECTOR}, "latest"])
        )
        token1 = decode_address_word(
            rpc.call("eth_call", [{"to": pool, "data": TOKEN1_SELECTOR}, "latest"])
        )
        fee_value = hex_int(
            rpc.call("eth_call", [{"to": pool, "data": FEE_SELECTOR}, "latest"])
        )
        expected_tokens = {normalize_address(left_addr), normalize_address(right_addr)}
        output[name] = {
            "status": "PASS"
            if len(code.removeprefix("0x")) > 0
            and {token0, token1} == expected_tokens
            and fee_value == fee
            else "FAIL",
            "token_a": normalize_address(left_addr),
            "token_b": normalize_address(right_addr),
            "token0": token0,
            "token1": token1,
            "fee": fee,
            "reported_fee": fee_value,
            "pool": pool,
            "code_bytes": len(code.removeprefix("0x")) // 2,
        }
    return output


def choose_endpoint(
    endpoints: Iterable[str],
) -> tuple[RpcClient, dict[str, Any], dict[str, dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for endpoint in endpoints:
        rpc = RpcClient(endpoint)
        item: dict[str, Any] = {"endpoint": endpoint}
        try:
            chain_id = hex_int(rpc.call("eth_chainId", []))
            latest = hex_int(rpc.call("eth_blockNumber", []))
            factory_code = rpc.call("eth_getCode", [FACTORY, "latest"])
            token_codes = {
                name: len(
                    rpc.call("eth_getCode", [address, "latest"]).removeprefix("0x")
                )
                // 2
                for name, address in TOKENS.items()
            }
            pools = resolve_pools(rpc)
            passing = [name for name, item2 in pools.items() if item2["status"] == "PASS"]
            item.update(
                {
                    "status": "PASS"
                    if chain_id == 1
                    and len(factory_code.removeprefix("0x")) > 0
                    and all(size > 0 for size in token_codes.values())
                    and len(passing) >= 2
                    else "FAIL",
                    "chain_id": chain_id,
                    "latest_block": latest,
                    "factory_code_bytes": len(factory_code.removeprefix("0x")) // 2,
                    "token_code_bytes": token_codes,
                    "passing_pools": passing,
                    "pools": pools,
                    "rpc_stats": vars(rpc.stats),
                }
            )
            attempts.append(item)
            if item["status"] == "PASS":
                return rpc, {"selected": endpoint, "attempts": attempts}, pools
        except Exception as exc:
            item.update(
                {
                    "status": "ERROR",
                    "error": repr(exc),
                    "rpc_stats": vars(rpc.stats),
                }
            )
            attempts.append(item)
    raise RpcError(json.dumps({"endpoint_attempts": attempts}, indent=2))


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    pools = collections.Counter(row["pool_name"] for row in rows)
    return {
        "logs": len(rows),
        "pools": dict(sorted(pools.items())),
        "unique_transactions": len({row["transaction_hash"] for row in rows}),
        "unique_blocks": len({row["block_number"] for row in rows}),
        "first_block_time": min((row["block_time_utc"] for row in rows), default=None),
        "last_block_time": max((row["block_time_utc"] for row in rows), default=None),
    }


def evaluate_gate(
    result: dict[str, Any], raw_records: list[dict[str, Any]]
) -> dict[str, bool]:
    identity_keys = [
        (row["block_hash"], row["transaction_hash"], row["log_index"])
        for row in raw_records
    ]
    dense_windows = sum(
        summary["logs"] >= 10 for summary in result["window_summaries"].values()
    )
    return {
        "endpoint_factory_tokens_and_at_least_two_pools": bool(
            result.get("endpoint_probe", {}).get("selected")
        ),
        "decode_errors_zero": len(result["decode_errors"]) == 0,
        "duplicate_identity_zero": len(identity_keys) == len(set(identity_keys)),
        "at_least_four_dense_windows": dense_windows >= 4,
        "at_least_100_logs": len(raw_records) >= 100,
        "timestamps_complete": all(
            isinstance(row.get("block_timestamp"), int) for row in raw_records
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "purpose": PURPOSE,
        "factory": FACTORY,
        "tokens": TOKENS,
        "pool_keys": [
            {"name": name, "token_a": left, "token_b": right, "fee": fee}
            for name, left, right, fee in POOL_KEYS
        ],
        "swap_signature": SWAP_SIGNATURE,
        "swap_topic": SWAP_TOPIC,
        "probe_windows": [
            {"date": date_text, "hour_utc": hour}
            for date_text, hour in PROBE_WINDOWS
        ],
        "endpoint_probe": {},
        "resolved_pools": {},
        "window_ranges": {},
        "window_summaries": {},
        "decode_errors": [],
        "forbidden_outcome_fields": [
            "future_return",
            "label",
            "action",
            "trade",
            "pnl",
            "model_metric",
            "official_2024_2026",
        ],
    }
    raw_records: list[dict[str, Any]] = []

    try:
        rpc, endpoint_probe, pools = choose_endpoint(ENDPOINTS)
        result["endpoint_probe"] = endpoint_probe
        result["resolved_pools"] = pools
        latest_block = hex_int(rpc.call("eth_blockNumber", []))
        locator = BlockLocator(rpc, latest_block)

        for date_text, hour in PROBE_WINDOWS:
            window_key = f"{date_text}T{hour:02d}:00:00Z"
            start_ts, end_ts = one_hour_window(date_text, hour)
            start_block = locator.first_at_or_after(start_ts)
            next_block = locator.first_at_or_after(end_ts)
            end_block = max(start_block, next_block - 1)
            result["window_ranges"][window_key] = {
                "from_block": start_block,
                "to_block": end_block,
                "from_block_time": dt.datetime.fromtimestamp(
                    locator.timestamp(start_block), tz=dt.timezone.utc
                ).isoformat(),
                "to_block_time": dt.datetime.fromtimestamp(
                    locator.timestamp(end_block), tz=dt.timezone.utc
                ).isoformat(),
            }
            window_records: list[dict[str, Any]] = []
            for pool_name, pool_info in pools.items():
                if pool_info["status"] != "PASS":
                    continue
                logs = get_logs_adaptive(
                    rpc,
                    address=pool_info["pool"],
                    from_block=start_block,
                    to_block=end_block,
                    topic0=SWAP_TOPIC,
                )
                for log in logs:
                    try:
                        block_number = hex_int(log["blockNumber"])
                        decoded = decode_swap_log(
                            log,
                            pool_name=pool_name,
                            expected_pool=pool_info["pool"],
                            token0=pool_info["token0"],
                            token1=pool_info["token1"],
                            fee=pool_info["fee"],
                            block_timestamp=locator.timestamp(block_number),
                        )
                        decoded["probe_window"] = window_key
                        window_records.append(decoded)
                        raw_records.append(decoded)
                    except Exception as exc:
                        result["decode_errors"].append(
                            {
                                "probe_window": window_key,
                                "pool_name": pool_name,
                                "error": repr(exc),
                                "raw_log": log,
                            }
                        )
            window_records.sort(
                key=lambda row: (
                    row["block_number"],
                    row["transaction_index"],
                    row["log_index"],
                )
            )
            result["window_summaries"][window_key] = summarize(window_records)

        raw_records.sort(
            key=lambda row: (
                row["block_number"],
                row["transaction_index"],
                row["log_index"],
            )
        )
        checks = evaluate_gate(result, raw_records)
        result["totals"] = {
            "decoded_logs": len(raw_records),
            "unique_transactions": len({row["transaction_hash"] for row in raw_records}),
            "unique_blocks": len({row["block_number"] for row in raw_records}),
            "decode_error_count": len(result["decode_errors"]),
            "rpc_stats": vars(rpc.stats),
        }
        result["source_gate_checks"] = checks
        result["source_gate_pass"] = all(checks.values())
        result["scientific_decision"] = (
            "OPEN_FROZEN_PRE2024_HISTORY_AND_MODEL_STAGE"
            if result["source_gate_pass"]
            else "CLOSE_SOURCE_ROUTE_BEFORE_OUTCOMES"
        )
    except Exception as exc:
        result["fatal_error"] = repr(exc)
        result["source_gate_pass"] = False
        result["scientific_decision"] = "CLOSE_SOURCE_ROUTE_BEFORE_OUTCOMES"

    raw_path = args.output / "RAW_SWAP_LOGS.jsonl.gz"
    with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
        for row in raw_records:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False))
            handle.write("\n")

    result_path = args.output / "PROBE_RESULT.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest = {
        "PROBE_RESULT.json": sha256_file(result_path),
        "RAW_SWAP_LOGS.jsonl.gz": sha256_file(raw_path),
    }
    (args.output / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(result_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
