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
RPC_ENDPOINTS = (
    "https://ethereum-rpc.publicnode.com",
    "https://eth-mainnet.public.blastapi.io",
    "https://1rpc.io/eth",
)
BLOCKSCOUT = "https://eth.blockscout.com/api"


class SourceError(RuntimeError):
    pass


@dataclass
class Stats:
    calls: int = 0
    retries: int = 0
    errors: int = 0
    batch_calls: int = 0


class Rpc:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "SMC-ICT-2-Aave-fast-source-gate/1.0",
                "Content-Type": "application/json",
            }
        )
        self.identifier = 0
        self.stats = Stats()

    def call(self, method: str, params: list[Any], attempts: int = 4) -> Any:
        self.identifier += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.identifier,
            "method": method,
            "params": params,
        }
        last: Exception | None = None
        for attempt in range(attempts):
            self.stats.calls += 1
            try:
                response = self.session.post(
                    self.endpoint, json=payload, timeout=(10, 45)
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise SourceError(
                        f"HTTP {response.status_code}: {response.text[:200]}"
                    )
                response.raise_for_status()
                body = response.json()
                if body.get("error") is not None:
                    raise SourceError(json.dumps(body["error"], sort_keys=True))
                if "result" not in body:
                    raise SourceError(f"missing result: {body!r}")
                return body["result"]
            except Exception as exc:
                last = exc
                self.stats.errors += 1
                if attempt + 1 >= attempts:
                    break
                self.stats.retries += 1
                time.sleep(min(4.0, 0.5 * 2**attempt))
        raise SourceError(f"{method} failed at {self.endpoint}: {last!r}")

    def block_timestamps(self, blocks: Iterable[int]) -> dict[int, int]:
        unique = sorted(set(int(value) for value in blocks))
        output: dict[int, int] = {}
        for offset in range(0, len(unique), 75):
            group = unique[offset : offset + 75]
            payload: list[dict[str, Any]] = []
            id_to_block: dict[int, int] = {}
            for block in group:
                self.identifier += 1
                request_id = self.identifier
                id_to_block[request_id] = block
                payload.append(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "eth_getBlockByNumber",
                        "params": [hex(block), False],
                    }
                )
            try:
                self.stats.batch_calls += 1
                response = self.session.post(
                    self.endpoint, json=payload, timeout=(10, 60)
                )
                response.raise_for_status()
                rows = response.json()
                if not isinstance(rows, list):
                    raise SourceError("batch response was not a list")
                by_id = {int(row["id"]): row for row in rows}
                for request_id, block in id_to_block.items():
                    row = by_id.get(request_id)
                    if row is None or row.get("error") is not None:
                        raise SourceError(f"missing batch block {block}")
                    result = row.get("result")
                    if result is None:
                        raise SourceError(f"null batch block {block}")
                    output[block] = int(result["timestamp"], 16)
            except Exception:
                for block in group:
                    result = self.call("eth_getBlockByNumber", [hex(block), False])
                    if result is None:
                        raise SourceError(f"missing block {block}")
                    output[block] = int(result["timestamp"], 16)
        return output


def normalize_address(value: str) -> str:
    text = value.lower()
    if not text.startswith("0x"):
        text = "0x" + text
    if len(text) != 42:
        raise ValueError(f"invalid address: {value}")
    return text


def topic_address(value: str) -> str:
    text = value[2:] if value.startswith("0x") else value
    if len(text) != 64:
        raise ValueError(f"invalid indexed topic: {value}")
    return normalize_address(text[-40:])


def utc_epoch(date_text: str, next_day: bool = False) -> int:
    day = dt.date.fromisoformat(date_text)
    stamp = dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc)
    if next_day:
        stamp += dt.timedelta(days=1)
    return int(stamp.timestamp())


def block_by_time(timestamp: int, closest: str) -> int:
    params = {
        "module": "block",
        "action": "getblocknobytime",
        "timestamp": timestamp,
        "closest": closest,
    }
    last: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.get(
                BLOCKSCOUT,
                params=params,
                timeout=(10, 45),
                headers={"User-Agent": "SMC-ICT-2-Aave-fast-source-gate/1.0"},
            )
            response.raise_for_status()
            body = response.json()
            result = body.get("result")
            if isinstance(result, dict):
                value = result.get("blockNumber")
            else:
                value = result
            if value is None:
                raise SourceError(f"bad Blockscout body: {body!r}")
            return int(value, 0) if isinstance(value, str) else int(value)
        except Exception as exc:
            last = exc
            if attempt + 1 < 4:
                time.sleep(min(4.0, 0.5 * 2**attempt))
    raise SourceError(f"block-by-time failed: {last!r}")


def choose_rpc(pools: dict[str, str]) -> tuple[Rpc, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for endpoint in RPC_ENDPOINTS:
        rpc = Rpc(endpoint)
        item: dict[str, Any] = {"endpoint": endpoint}
        try:
            chain_id = int(rpc.call("eth_chainId", []), 16)
            latest = int(rpc.call("eth_blockNumber", []), 16)
            code_sizes: dict[str, int] = {}
            for version, address in pools.items():
                code = rpc.call("eth_getCode", [address, "latest"])
                clean = code[2:] if isinstance(code, str) and code.startswith("0x") else ""
                code_sizes[version] = len(clean) // 2
            passed = chain_id == 1 and latest > 0 and all(
                size > 0 for size in code_sizes.values()
            )
            item.update(
                {
                    "status": "PASS" if passed else "FAIL",
                    "chain_id": chain_id,
                    "latest_block": latest,
                    "pool_code_bytes": code_sizes,
                    "rpc_stats": vars(rpc.stats),
                }
            )
            attempts.append(item)
            if passed:
                return rpc, attempts
        except Exception as exc:
            item.update(
                {
                    "status": "ERROR",
                    "error": repr(exc),
                    "rpc_stats": vars(rpc.stats),
                }
            )
            attempts.append(item)
    raise SourceError(json.dumps(attempts, sort_keys=True))


def get_logs_adaptive(
    rpc: Rpc, address: str, start: int, end: int
) -> list[dict[str, Any]]:
    try:
        result = rpc.call(
            "eth_getLogs",
            [
                {
                    "fromBlock": hex(start),
                    "toBlock": hex(end),
                    "address": address,
                    "topics": [EVENT_TOPIC],
                }
            ],
            attempts=3,
        )
        if not isinstance(result, list):
            raise SourceError("eth_getLogs did not return a list")
        return result
    except Exception:
        if start >= end:
            raise
        midpoint = (start + end) // 2
        return get_logs_adaptive(rpc, address, start, midpoint) + get_logs_adaptive(
            rpc, address, midpoint + 1, end
        )


def decode_event(
    log: dict[str, Any], version: str, pool: str, timestamp: int, probe_date: str
) -> dict[str, Any]:
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) != 4:
        raise ValueError(f"unexpected topics: {topics!r}")
    if topics[0].lower() != EVENT_TOPIC.lower():
        raise ValueError("topic0 mismatch")
    if normalize_address(log["address"]) != pool:
        raise ValueError("pool address mismatch")
    data = log.get("data", "")
    raw = bytes.fromhex(data[2:] if data.startswith("0x") else data)
    debt, collateral, liquidator, receive_atoken = decode(
        ["uint256", "uint256", "address", "bool"], raw
    )
    block_number = int(log["blockNumber"], 16)
    return {
        "version": version,
        "pool": pool,
        "probe_date": probe_date,
        "collateral_asset": topic_address(topics[1]),
        "debt_asset": topic_address(topics[2]),
        "user": topic_address(topics[3]),
        "debt_to_cover_raw": str(int(debt)),
        "liquidated_collateral_raw": str(int(collateral)),
        "liquidator": normalize_address(str(liquidator)),
        "receive_atoken": bool(receive_atoken),
        "block_number": block_number,
        "block_hash": log["blockHash"].lower(),
        "block_timestamp": timestamp,
        "block_time_utc": dt.datetime.fromtimestamp(
            timestamp, tz=dt.timezone.utc
        ).isoformat(),
        "transaction_hash": log["transactionHash"].lower(),
        "transaction_index": int(log["transactionIndex"], 16),
        "log_index": int(log["logIndex"], 16),
        "removed": bool(log.get("removed", False)),
        "raw_log": log,
    }


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    return {
        "logs": len(values),
        "versions": dict(sorted(collections.Counter(x["version"] for x in values).items())),
        "unique_transactions": len({x["transaction_hash"] for x in values}),
        "unique_blocks": len({x["block_number"] for x in values}),
        "unique_users": len({x["user"] for x in values}),
        "unique_liquidators": len({x["liquidator"] for x in values}),
        "receive_atoken_true": sum(bool(x["receive_atoken"]) for x in values),
        "first_block_time": min((x["block_time_utc"] for x in values), default=None),
        "last_block_time": max((x["block_time_utc"] for x in values), default=None),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--addresses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    addresses = json.loads(args.addresses.read_text(encoding="utf-8"))
    pools = {key: normalize_address(value) for key, value in addresses["pools"].items()}
    result: dict[str, Any] = {
        "schema_version": 2,
        "claim_id": "CLM-20260726-1952-ML-AAVE-LIQUIDATION-001",
        "transport_correction": "TRANSPORT-CORRECTION-20260726-AAVE-BLOCK-BY-TIME-001",
        "purpose": "Outcome-sealed source gate only; no price, label, model, trade or PnL.",
        "address_book": addresses,
        "event_signature": EVENT_SIGNATURE,
        "event_topic": EVENT_TOPIC,
        "probe_dates": list(PROBE_DATES),
        "block_locator": BLOCKSCOUT,
        "endpoint_probe": {},
        "date_ranges": {},
        "date_summaries": {},
        "decode_errors": [],
    }
    records: list[dict[str, Any]] = []
    try:
        rpc, endpoint_attempts = choose_rpc(pools)
        result["endpoint_probe"] = {
            "selected": rpc.endpoint,
            "attempts": endpoint_attempts,
        }
        staged_logs: list[tuple[str, str, str, dict[str, Any]]] = []
        boundary_blocks: set[int] = set()
        for date_text in PROBE_DATES:
            start = block_by_time(utc_epoch(date_text), "after")
            next_day = block_by_time(utc_epoch(date_text, next_day=True), "after")
            end = max(start, next_day - 1)
            boundary_blocks.update((start, end))
            result["date_ranges"][date_text] = {
                "from_block": start,
                "to_block": end,
            }
            for version, pool in pools.items():
                for log in get_logs_adaptive(rpc, pool, start, end):
                    staged_logs.append((date_text, version, pool, log))

        event_blocks = {int(item[3]["blockNumber"], 16) for item in staged_logs}
        timestamps = rpc.block_timestamps(boundary_blocks | event_blocks)
        for date_text in PROBE_DATES:
            item = result["date_ranges"][date_text]
            start = int(item["from_block"])
            end = int(item["to_block"])
            item["from_block_time"] = dt.datetime.fromtimestamp(
                timestamps[start], tz=dt.timezone.utc
            ).isoformat()
            item["to_block_time"] = dt.datetime.fromtimestamp(
                timestamps[end], tz=dt.timezone.utc
            ).isoformat()
            start_epoch = utc_epoch(date_text)
            end_epoch = utc_epoch(date_text, next_day=True)
            item["boundary_verified"] = (
                start_epoch <= timestamps[start] < end_epoch
                and start_epoch <= timestamps[end] < end_epoch
            )

        by_date: dict[str, list[dict[str, Any]]] = {date: [] for date in PROBE_DATES}
        for date_text, version, pool, log in staged_logs:
            try:
                block = int(log["blockNumber"], 16)
                row = decode_event(log, version, pool, timestamps[block], date_text)
                if not (utc_epoch(date_text) <= row["block_timestamp"] < utc_epoch(date_text, True)):
                    raise ValueError("event timestamp outside frozen UTC date")
                by_date[date_text].append(row)
                records.append(row)
            except Exception as exc:
                result["decode_errors"].append(
                    {"probe_date": date_text, "version": version, "error": repr(exc), "raw_log": log}
                )

        records.sort(key=lambda x: (x["block_number"], x["transaction_index"], x["log_index"]))
        for date_text in PROBE_DATES:
            by_date[date_text].sort(
                key=lambda x: (x["block_number"], x["transaction_index"], x["log_index"])
            )
            result["date_summaries"][date_text] = summarize(by_date[date_text])
        identities = [
            (x["block_hash"], x["transaction_hash"], x["log_index"]) for x in records
        ]
        duplicates = len(identities) - len(set(identities))
        nonzero_dates = sum(x["logs"] > 0 for x in result["date_summaries"].values())
        result["totals"] = {
            "decoded_logs": len(records),
            "nonzero_dates": nonzero_dates,
            "unique_transactions": len({x["transaction_hash"] for x in records}),
            "unique_blocks": len({x["block_number"] for x in records}),
            "duplicate_identity_count": duplicates,
            "decode_error_count": len(result["decode_errors"]),
            "rpc_stats": vars(rpc.stats),
        }
        checks = {
            "endpoint_and_pool_code": True,
            "all_date_boundaries_verified": all(
                x["boundary_verified"] for x in result["date_ranges"].values()
            ),
            "decode_errors_zero": len(result["decode_errors"]) == 0,
            "duplicate_identity_zero": duplicates == 0,
            "at_least_four_nonzero_dates": nonzero_dates >= 4,
            "at_least_25_logs": len(records) >= 25,
            "timestamps_complete": all(isinstance(x["block_timestamp"], int) for x in records),
        }
        result["source_gate_checks"] = checks
        result["source_gate_pass"] = all(checks.values())
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
        for row in records:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    result_path = args.output / "PROBE_RESULT.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    manifest = {
        "PROBE_RESULT.json": sha256_file(result_path),
        "RAW_LOGS.jsonl.gz": sha256_file(raw_path),
        "addresses_sha256": sha256_file(args.addresses),
    }
    (args.output / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(result_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
