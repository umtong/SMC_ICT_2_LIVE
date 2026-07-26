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
from eth_abi import decode
from eth_utils import keccak


EVENT_SIGNATURE = "LiquidationCall(address,address,address,uint256,uint256,address,bool)"
EVENT_TOPIC = "0x" + keccak(text=EVENT_SIGNATURE).hex()
PROBE_DATES = (
    "2021-05-19",
    "2021-12-04",
    "2022-05-12",
    "2022-06-13",
    "2022-11-09",
    "2023-03-11",
    "2023-08-17",
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
                "User-Agent": "SMC-ICT-2-Aave-source-gate/1.0",
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
                    raise RpcError(
                        f"HTTP {response.status_code}: {response.text[:300]}"
                    )
                response.raise_for_status()
                body = response.json()
                if body.get("error") is not None:
                    raise RpcError(json.dumps(body["error"], sort_keys=True))
                if "result" not in body:
                    raise RpcError(f"missing result: {body!r}")
                return body["result"]
            except Exception as exc:
                last_error = exc
                self.stats.errors += 1
                if attempt + 1 >= attempts:
                    break
                self.stats.retries += 1
                time.sleep(min(8.0, 0.75 * (2**attempt)))
        raise RpcError(f"{method} failed at {self.endpoint}: {last_error!r}")


def hex_int(value: str) -> int:
    return int(value, 16)


def normalize_address(value: str) -> str:
    value = value.lower()
    if not value.startswith("0x"):
        value = "0x" + value
    if len(value) != 42:
        raise ValueError(f"invalid address {value}")
    return value


def topic_address(topic: str) -> str:
    clean = topic[2:] if topic.startswith("0x") else topic
    if len(clean) != 64:
        raise ValueError(f"invalid indexed topic length: {topic}")
    return normalize_address(clean[-40:])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_timestamp(date_text: str, *, end: bool = False) -> int:
    day = dt.date.fromisoformat(date_text)
    value = dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc)
    if end:
        value += dt.timedelta(days=1)
    return int(value.timestamp())


class BlockLocator:
    def __init__(self, rpc: RpcClient, latest_block: int) -> None:
        self.rpc = rpc
        self.latest_block = latest_block
        self.cache: dict[int, int] = {}

    def timestamp(self, block_number: int) -> int:
        if block_number not in self.cache:
            block = self.rpc.call(
                "eth_getBlockByNumber", [hex(block_number), False]
            )
            if block is None:
                raise RpcError(f"missing block {block_number}")
            self.cache[block_number] = hex_int(block["timestamp"])
        return self.cache[block_number]

    def first_at_or_after(self, target_timestamp: int) -> int:
        low = 0
        high = self.latest_block
        if self.timestamp(high) < target_timestamp:
            raise RpcError(
                f"target {target_timestamp} after latest block timestamp"
            )
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
    maximum_chunk: int = 2000,
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
                        "address": address,
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


def decode_log(
    log: dict[str, Any],
    *,
    version: str,
    expected_pool: str,
    block_timestamp: int,
) -> dict[str, Any]:
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) != 4:
        raise ValueError(f"unexpected topic structure: {topics!r}")
    if topics[0].lower() != EVENT_TOPIC.lower():
        raise ValueError(f"unexpected topic0 {topics[0]}")
    if normalize_address(log["address"]) != normalize_address(expected_pool):
        raise ValueError("log address does not match queried pool")

    data_hex = log.get("data", "")
    raw_data = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
    debt_to_cover, collateral_amount, liquidator, receive_atoken = decode(
        ["uint256", "uint256", "address", "bool"], raw_data
    )
    return {
        "version": version,
        "pool": normalize_address(expected_pool),
        "collateral_asset": topic_address(topics[1]),
        "debt_asset": topic_address(topics[2]),
        "user": topic_address(topics[3]),
        "debt_to_cover_raw": str(int(debt_to_cover)),
        "liquidated_collateral_raw": str(int(collateral_amount)),
        "liquidator": normalize_address(str(liquidator)),
        "receive_atoken": bool(receive_atoken),
        "block_number": hex_int(log["blockNumber"]),
        "block_hash": log["blockHash"].lower(),
        "block_timestamp": block_timestamp,
        "block_time_utc": dt.datetime.fromtimestamp(
            block_timestamp, tz=dt.timezone.utc
        ).isoformat(),
        "transaction_hash": log["transactionHash"].lower(),
        "transaction_index": hex_int(log["transactionIndex"]),
        "log_index": hex_int(log["logIndex"]),
        "removed": bool(log.get("removed", False)),
        "raw_log": log,
    }


def summarize_date(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    collateral = collections.Counter(row["collateral_asset"] for row in rows)
    debt = collections.Counter(row["debt_asset"] for row in rows)
    versions = collections.Counter(row["version"] for row in rows)
    return {
        "logs": len(rows),
        "versions": dict(sorted(versions.items())),
        "unique_transactions": len({row["transaction_hash"] for row in rows}),
        "unique_blocks": len({row["block_number"] for row in rows}),
        "unique_users": len({row["user"] for row in rows}),
        "unique_liquidators": len({row["liquidator"] for row in rows}),
        "receive_atoken_true": sum(row["receive_atoken"] for row in rows),
        "top_collateral_assets": collateral.most_common(10),
        "top_debt_assets": debt.most_common(10),
        "first_block_time": min(
            (row["block_time_utc"] for row in rows), default=None
        ),
        "last_block_time": max(
            (row["block_time_utc"] for row in rows), default=None
        ),
    }


def choose_endpoint(
    endpoints: Iterable[str], pools: dict[str, str]
) -> tuple[RpcClient, dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for endpoint in endpoints:
        rpc = RpcClient(endpoint)
        item: dict[str, Any] = {"endpoint": endpoint}
        try:
            chain_id = hex_int(rpc.call("eth_chainId", []))
            latest = hex_int(rpc.call("eth_blockNumber", []))
            code_sizes: dict[str, int] = {}
            for version, pool in pools.items():
                code = rpc.call("eth_getCode", [pool, "latest"])
                clean = code[2:] if isinstance(code, str) and code.startswith("0x") else ""
                code_sizes[version] = len(clean) // 2
            item.update(
                {
                    "status": "PASS"
                    if chain_id == 1 and all(size > 0 for size in code_sizes.values())
                    else "FAIL",
                    "chain_id": chain_id,
                    "latest_block": latest,
                    "pool_code_bytes": code_sizes,
                    "rpc_stats": vars(rpc.stats),
                }
            )
            attempts.append(item)
            if item["status"] == "PASS":
                return rpc, {"selected": endpoint, "attempts": attempts}
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--addresses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    addresses = json.loads(args.addresses.read_text(encoding="utf-8"))
    pools = {
        key: normalize_address(value)
        for key, value in addresses["pools"].items()
    }

    result: dict[str, Any] = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-1952-ML-AAVE-LIQUIDATION-001",
        "purpose": (
            "Outcome-sealed source gate only. No market price, return, label, "
            "action, trade, PnL, model metric, official project period, credential, "
            "or order path is opened."
        ),
        "address_book": addresses,
        "event_signature": EVENT_SIGNATURE,
        "event_topic": EVENT_TOPIC,
        "probe_dates": list(PROBE_DATES),
        "endpoint_probe": {},
        "date_ranges": {},
        "date_summaries": {},
        "decode_errors": [],
    }

    raw_records: list[dict[str, Any]] = []
    try:
        rpc, endpoint_probe = choose_endpoint(ENDPOINTS, pools)
        result["endpoint_probe"] = endpoint_probe
        latest_block = hex_int(rpc.call("eth_blockNumber", []))
        locator = BlockLocator(rpc, latest_block)

        for date_text in PROBE_DATES:
            start_block = locator.first_at_or_after(utc_timestamp(date_text))
            next_day_block = locator.first_at_or_after(
                utc_timestamp(date_text, end=True)
            )
            end_block = max(start_block, next_day_block - 1)
            result["date_ranges"][date_text] = {
                "from_block": start_block,
                "to_block": end_block,
                "from_block_time": dt.datetime.fromtimestamp(
                    locator.timestamp(start_block), tz=dt.timezone.utc
                ).isoformat(),
                "to_block_time": dt.datetime.fromtimestamp(
                    locator.timestamp(end_block), tz=dt.timezone.utc
                ).isoformat(),
            }

            date_records: list[dict[str, Any]] = []
            for version, pool in pools.items():
                logs = get_logs_adaptive(
                    rpc,
                    address=pool,
                    from_block=start_block,
                    to_block=end_block,
                    topic0=EVENT_TOPIC,
                )
                for log in logs:
                    try:
                        block_number = hex_int(log["blockNumber"])
                        timestamp = locator.timestamp(block_number)
                        decoded = decode_log(
                            log,
                            version=version,
                            expected_pool=pool,
                            block_timestamp=timestamp,
                        )
                        decoded["probe_date"] = date_text
                        date_records.append(decoded)
                        raw_records.append(decoded)
                    except Exception as exc:
                        result["decode_errors"].append(
                            {
                                "probe_date": date_text,
                                "version": version,
                                "error": repr(exc),
                                "raw_log": log,
                            }
                        )
            date_records.sort(
                key=lambda row: (
                    row["block_number"],
                    row["transaction_index"],
                    row["log_index"],
                )
            )
            result["date_summaries"][date_text] = summarize_date(date_records)

        raw_records.sort(
            key=lambda row: (
                row["block_number"],
                row["transaction_index"],
                row["log_index"],
            )
        )
        identity_keys = [
            (row["block_hash"], row["transaction_hash"], row["log_index"])
            for row in raw_records
        ]
        duplicate_count = len(identity_keys) - len(set(identity_keys))
        nonzero_dates = sum(
            summary["logs"] > 0
            for summary in result["date_summaries"].values()
        )
        result["totals"] = {
            "decoded_logs": len(raw_records),
            "nonzero_dates": nonzero_dates,
            "unique_transactions": len(
                {row["transaction_hash"] for row in raw_records}
            ),
            "unique_blocks": len({row["block_number"] for row in raw_records}),
            "duplicate_identity_count": duplicate_count,
            "decode_error_count": len(result["decode_errors"]),
            "rpc_stats": vars(rpc.stats),
        }
        result["source_gate_checks"] = {
            "endpoint_and_pool_code": True,
            "decode_errors_zero": len(result["decode_errors"]) == 0,
            "duplicate_identity_zero": duplicate_count == 0,
            "at_least_four_nonzero_dates": nonzero_dates >= 4,
            "at_least_25_logs": len(raw_records) >= 25,
            "timestamps_complete": all(
                isinstance(row["block_timestamp"], int) for row in raw_records
            ),
        }
        result["source_gate_pass"] = all(
            result["source_gate_checks"].values()
        )
        result["scientific_decision"] = (
            "OPEN_FROZEN_PRE2024_HISTORY_STAGE"
            if result["source_gate_pass"]
            else "CLOSE_SOURCE_ROUTE_BEFORE_OUTCOMES"
        )
    except Exception as exc:
        result["fatal_error"] = repr(exc)
        result["source_gate_pass"] = False
        result["scientific_decision"] = "CLOSE_SOURCE_ROUTE_BEFORE_OUTCOMES"

    raw_path = args.output / "RAW_LOGS.jsonl.gz"
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
        "RAW_LOGS.jsonl.gz": sha256_file(raw_path),
        "addresses_sha256": sha256_file(args.addresses),
    }
    (args.output / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(result_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
