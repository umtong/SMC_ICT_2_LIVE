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
from typing import Any, Iterable, Sequence

import requests

CLAIM_ID = "CLM-20260726-2324-ML-GMX-V1-LIQUIDATION-001"
PURPOSE = (
    "Outcome-sealed source gate only. No CEX or Bybit market price, future return, "
    "first-passage label, model metric, action, trade, PnL, official 2024-2026 period, "
    "credential, or order path is opened."
)
CHAIN_ID = 42161
VAULT = "0x489ee077994b6658eafa855c308275ead8097c4a"
LIQUIDATE_POSITION_SIGNATURE = (
    "LiquidatePosition(bytes32,address,address,address,bool,uint256,uint256,"
    "uint256,int256,uint256)"
)
LIQUIDATE_POSITION_TOPIC = (
    "0x2e1f85a64a2f22cf2f0c42584e7c919ed4abe8d53675cff0f62bf1e95a1c676f"
)
INDEX_TOKENS = {
    "BTC": "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f",
    "ETH": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
}
INFORMATION_DELAY_SECONDS = 120
PROBE_WINDOWS: tuple[tuple[str, str], ...] = (
    ("2021-12-01T00:00:00Z", "2021-12-08T00:00:00Z"),
    ("2022-05-08T00:00:00Z", "2022-05-15T00:00:00Z"),
    ("2022-06-10T00:00:00Z", "2022-06-18T00:00:00Z"),
    ("2022-11-06T00:00:00Z", "2022-11-13T00:00:00Z"),
    ("2023-03-08T00:00:00Z", "2023-03-15T00:00:00Z"),
    ("2023-08-14T00:00:00Z", "2023-08-21T00:00:00Z"),
)
ENDPOINTS: tuple[str, ...] = (
    "https://arbitrum.blockscout.com/api/eth-rpc",
    "https://arb1.arbitrum.io/rpc",
    "https://arbitrum-one-rpc.publicnode.com",
)
MAX_RPC_CALLS = 5_000
MAX_WALL_SECONDS = 2_400.0
MIN_REQUEST_INTERVAL_SECONDS = 0.08
BLOCK_TIMESTAMP_BATCH_SIZE = 50
INITIAL_LOG_CHUNK_BLOCKS = 150_000
RANGE_ERROR_MARKERS = (
    "-32005",
    "query returned more than",
    "too many results",
    "response size",
    "result size",
    "range too large",
    "block range",
    "limit exceeded",
    "please limit",
    "maximum block",
    "exceeds the range",
)
TRANSIENT_ERROR_MARKERS = (
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "timeout",
    "timed out",
    "connection",
    "temporarily unavailable",
    "rate limit",
)


class RpcError(RuntimeError):
    pass


class EndpointUnavailable(RpcError):
    pass


@dataclass
class RpcStats:
    calls: int = 0
    retries: int = 0
    errors: int = 0


def normalize_address(value: str) -> str:
    clean = value.lower()
    if not clean.startswith("0x"):
        clean = "0x" + clean
    if len(clean) != 42:
        raise ValueError(f"invalid address {value!r}")
    int(clean[2:], 16)
    return clean


def hex_int(value: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ValueError(f"expected 0x-prefixed integer, got {value!r}")
    return int(value, 16)


def decode_address_word(word: bytes) -> str:
    if len(word) != 32:
        raise ValueError("ABI address word must be 32 bytes")
    if any(word[:12]):
        raise ValueError("non-zero high bytes in ABI address word")
    return normalize_address(word[-20:].hex())


def decode_signed_word(word: bytes) -> int:
    if len(word) != 32:
        raise ValueError("ABI signed word must be 32 bytes")
    return int.from_bytes(word, "big", signed=True)


def decimal_1e30(raw: int) -> str:
    sign = "-" if raw < 0 else ""
    value = abs(int(raw))
    whole, fraction = divmod(value, 10**30)
    if fraction == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{fraction:030d}".rstrip("0")


def parse_utc(value: str) -> int:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone aware")
    return int(parsed.timestamp())


def utc_iso(timestamp: int) -> str:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RpcClient:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "SMC-ICT-2-GMX-V1-source-gate/1.0",
                "Content-Type": "application/json",
            }
        )
        self.counter = 0
        self.stats = RpcStats()
        self.started_monotonic = time.monotonic()
        self.next_request_monotonic = self.started_monotonic

    def _pace(self) -> None:
        if self.stats.calls >= MAX_RPC_CALLS:
            raise EndpointUnavailable(f"RPC call budget exceeded at {self.endpoint}")
        if time.monotonic() - self.started_monotonic >= MAX_WALL_SECONDS:
            raise EndpointUnavailable(f"RPC wall-time budget exceeded at {self.endpoint}")
        now = time.monotonic()
        delay = self.next_request_monotonic - now
        if delay > 0:
            time.sleep(delay)
        self.next_request_monotonic = time.monotonic() + MIN_REQUEST_INTERVAL_SECONDS

    def _post(self, payload: Any, *, attempts: int = 5) -> Any:
        last_error: Exception | None = None
        count = max(1, min(int(attempts), 5))
        for attempt in range(count):
            self._pace()
            self.stats.calls += 1
            try:
                response = self.session.post(
                    self.endpoint,
                    json=payload,
                    timeout=(15, 90),
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise RpcError(f"HTTP {response.status_code}: {response.text[:300]}")
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                self.stats.errors += 1
                if attempt + 1 >= count:
                    break
                self.stats.retries += 1
                time.sleep(min(10.0, 0.75 * (2**attempt)))
        raise RpcError(f"request failed at {self.endpoint}: {last_error!r}")

    def call(self, method: str, params: list[Any], *, attempts: int = 5) -> Any:
        self.counter += 1
        request_id = self.counter
        body = self._post(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
            attempts=attempts,
        )
        if not isinstance(body, dict):
            raise RpcError(f"{method} returned non-object JSON: {type(body)!r}")
        if body.get("error") is not None:
            raise RpcError(json.dumps(body["error"], sort_keys=True))
        if body.get("id") != request_id:
            raise RpcError(f"{method} response id mismatch")
        if "result" not in body:
            raise RpcError(f"{method} missing result")
        return body["result"]

    def batch_block_timestamps(self, block_numbers: Iterable[int]) -> dict[int, int]:
        numbers = tuple(dict.fromkeys(int(number) for number in block_numbers))
        output: dict[int, int] = {}
        for offset in range(0, len(numbers), BLOCK_TIMESTAMP_BATCH_SIZE):
            chunk = numbers[offset : offset + BLOCK_TIMESTAMP_BATCH_SIZE]
            payload: list[dict[str, Any]] = []
            ids: dict[int, int] = {}
            for number in chunk:
                self.counter += 1
                request_id = self.counter
                ids[request_id] = number
                payload.append(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "eth_getBlockByNumber",
                        "params": [hex(number), False],
                    }
                )
            try:
                body = self._post(payload, attempts=5)
                if not isinstance(body, list):
                    raise RpcError(f"batch block lookup returned {type(body)!r}")
                by_id = {
                    int(item["id"]): item
                    for item in body
                    if isinstance(item, dict) and "id" in item
                }
                for request_id, number in ids.items():
                    item = by_id.get(request_id)
                    if item is None:
                        raise RpcError(f"missing batch response for block {number}")
                    if item.get("error") is not None:
                        raise RpcError(json.dumps(item["error"], sort_keys=True))
                    block = item.get("result")
                    if not isinstance(block, dict):
                        raise RpcError(f"missing block {number}")
                    output[number] = hex_int(block["timestamp"])
            except Exception:
                for number in chunk:
                    block = self.call("eth_getBlockByNumber", [hex(number), False])
                    if not isinstance(block, dict):
                        raise EndpointUnavailable(f"missing block {number}")
                    output[number] = hex_int(block["timestamp"])
        return output


class BlockLocator:
    def __init__(self, rpc: RpcClient, latest_block: int) -> None:
        self.rpc = rpc
        self.latest_block = int(latest_block)
        self.cache: dict[int, int] = {}

    def timestamp(self, block_number: int) -> int:
        number = int(block_number)
        if number not in self.cache:
            block = self.rpc.call("eth_getBlockByNumber", [hex(number), False])
            if not isinstance(block, dict):
                raise EndpointUnavailable(f"missing block {number}")
            self.cache[number] = hex_int(block["timestamp"])
        return self.cache[number]

    def first_at_or_after(self, target_timestamp: int) -> int:
        low = 0
        high = self.latest_block
        if self.timestamp(high) < int(target_timestamp):
            raise EndpointUnavailable(
                f"target {target_timestamp} is after latest block timestamp"
            )
        while low < high:
            midpoint = (low + high) // 2
            if self.timestamp(midpoint) < int(target_timestamp):
                low = midpoint + 1
            else:
                high = midpoint
        return low


def is_range_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in RANGE_ERROR_MARKERS)


def is_transient_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in TRANSIENT_ERROR_MARKERS)


def get_logs_adaptive(
    rpc: RpcClient,
    *,
    address: str,
    from_block: int,
    to_block: int,
    topic0: str,
    maximum_chunk: int = INITIAL_LOG_CHUNK_BLOCKS,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []

    def query(start: int, end: int, depth: int = 0) -> None:
        if depth > 32:
            raise EndpointUnavailable("range bisection depth exceeded")
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
        except Exception as exc:
            if not is_range_error(exc):
                raise EndpointUnavailable(
                    f"historical eth_getLogs unavailable at {rpc.endpoint}: {exc}"
                ) from exc
            if start >= end:
                raise EndpointUnavailable(
                    f"single-block eth_getLogs still exceeds provider limit at {start}"
                ) from exc
            midpoint = (start + end) // 2
            query(start, midpoint, depth + 1)
            query(midpoint + 1, end, depth + 1)

    cursor = int(from_block)
    final = int(to_block)
    while cursor <= final:
        end = min(final, cursor + int(maximum_chunk) - 1)
        query(cursor, end)
        cursor = end + 1
    return output


def decode_liquidation_log(
    log: dict[str, Any],
    *,
    block_timestamp: int,
    probe_window: str,
) -> dict[str, Any]:
    if normalize_address(log.get("address", "")) != VAULT:
        raise ValueError("log address does not match canonical GMX V1 Vault")
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) != 1:
        raise ValueError(f"unexpected topic structure: {topics!r}")
    if str(topics[0]).lower() != LIQUIDATE_POSITION_TOPIC:
        raise ValueError("unexpected topic0")
    data_hex = str(log.get("data", ""))
    clean = data_hex[2:] if data_hex.startswith("0x") else data_hex
    if len(clean) != 32 * 10 * 2:
        raise ValueError(f"unexpected LiquidatePosition data length: {len(clean) // 2}")
    raw = bytes.fromhex(clean)
    words = [raw[index : index + 32] for index in range(0, len(raw), 32)]
    is_long_raw = int.from_bytes(words[4], "big", signed=False)
    if is_long_raw not in (0, 1):
        raise ValueError(f"invalid ABI bool value {is_long_raw}")
    key = "0x" + words[0].hex()
    account = decode_address_word(words[1])
    collateral_token = decode_address_word(words[2])
    index_token = decode_address_word(words[3])
    size = int.from_bytes(words[5], "big", signed=False)
    collateral = int.from_bytes(words[6], "big", signed=False)
    reserve_amount = int.from_bytes(words[7], "big", signed=False)
    realised_pnl = decode_signed_word(words[8])
    mark_price = int.from_bytes(words[9], "big", signed=False)
    asset = next(
        (name for name, address in INDEX_TOKENS.items() if index_token == address),
        "OTHER",
    )
    return {
        "claim_id": CLAIM_ID,
        "source": "GMX_V1_ARBITRUM_LIQUIDATE_POSITION",
        "probe_window": probe_window,
        "vault": VAULT,
        "event_signature": LIQUIDATE_POSITION_SIGNATURE,
        "event_topic0": LIQUIDATE_POSITION_TOPIC,
        "key": key,
        "account": account,
        "collateral_token": collateral_token,
        "index_token": index_token,
        "asset": asset,
        "liquidated_position_side": "LONG" if is_long_raw == 1 else "SHORT",
        "forced_flow_direction": "SELL" if is_long_raw == 1 else "BUY",
        "size_raw_1e30": str(size),
        "size_usd": decimal_1e30(size),
        "collateral_raw_1e30": str(collateral),
        "collateral_usd": decimal_1e30(collateral),
        "reserve_amount_raw": str(reserve_amount),
        "realised_pnl_raw_1e30": str(realised_pnl),
        "realised_pnl_usd": decimal_1e30(realised_pnl),
        "mark_price_raw_1e30": str(mark_price),
        "mark_price_usd": decimal_1e30(mark_price),
        "block_number": hex_int(log["blockNumber"]),
        "block_hash": str(log["blockHash"]).lower(),
        "block_timestamp": int(block_timestamp),
        "block_time_utc": utc_iso(int(block_timestamp)),
        "causal_available_timestamp": int(block_timestamp) + INFORMATION_DELAY_SECONDS,
        "causal_available_time_utc": utc_iso(
            int(block_timestamp) + INFORMATION_DELAY_SECONDS
        ),
        "transaction_hash": str(log["transactionHash"]).lower(),
        "transaction_index": hex_int(log["transactionIndex"]),
        "log_index": hex_int(log["logIndex"]),
        "removed": bool(log.get("removed", False)),
        "raw_log": log,
    }


def choose_endpoint(
    endpoints: Sequence[str],
) -> tuple[RpcClient, dict[str, Any], BlockLocator]:
    attempts: list[dict[str, Any]] = []
    first_start = parse_utc(PROBE_WINDOWS[0][0])
    for endpoint in endpoints:
        rpc = RpcClient(endpoint)
        item: dict[str, Any] = {"endpoint": endpoint}
        try:
            chain_id = hex_int(rpc.call("eth_chainId", []))
            latest = hex_int(rpc.call("eth_blockNumber", []))
            vault_code = rpc.call("eth_getCode", [VAULT, "latest"])
            if (
                chain_id != CHAIN_ID
                or not isinstance(vault_code, str)
                or len(vault_code.removeprefix("0x")) == 0
            ):
                raise EndpointUnavailable("chain ID or canonical Vault bytecode failed")
            locator = BlockLocator(rpc, latest)
            historical_block = locator.first_at_or_after(first_start)
            historical = rpc.call(
                "eth_getBlockByNumber", [hex(historical_block), False]
            )
            if not isinstance(historical, dict):
                raise EndpointUnavailable("historical block preflight returned null")
            one_block_logs = rpc.call(
                "eth_getLogs",
                [
                    {
                        "fromBlock": hex(historical_block),
                        "toBlock": hex(historical_block),
                        "address": VAULT,
                        "topics": [LIQUIDATE_POSITION_TOPIC],
                    }
                ],
            )
            if not isinstance(one_block_logs, list):
                raise EndpointUnavailable("historical one-block log preflight failed")
            item.update(
                {
                    "status": "PASS",
                    "chain_id": chain_id,
                    "latest_block": latest,
                    "vault_code_bytes": len(vault_code.removeprefix("0x")) // 2,
                    "historical_preflight_block": historical_block,
                    "historical_preflight_log_count": len(one_block_logs),
                    "rpc_stats": vars(rpc.stats),
                }
            )
            attempts.append(item)
            return rpc, {"selected": endpoint, "attempts": attempts}, locator
        except Exception as exc:
            item.update(
                {
                    "status": "ERROR",
                    "error": repr(exc),
                    "rpc_stats": vars(rpc.stats),
                }
            )
            attempts.append(item)
    raise EndpointUnavailable(json.dumps({"endpoint_attempts": attempts}, indent=2))


def window_key(start: str, end: str) -> str:
    return f"{start}__{end}"


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    assets = collections.Counter(row["asset"] for row in rows)
    sides = collections.Counter(row["liquidated_position_side"] for row in rows)
    return {
        "decoded_logs": len(rows),
        "btc_eth_logs": sum(row["asset"] in INDEX_TOKENS for row in rows),
        "assets": dict(sorted(assets.items())),
        "sides": dict(sorted(sides.items())),
        "unique_transactions": len({row["transaction_hash"] for row in rows}),
        "unique_blocks": len({row["block_number"] for row in rows}),
        "size_usd_sum_btc_eth": decimal_1e30(
            sum(
                int(row["size_raw_1e30"])
                for row in rows
                if row["asset"] in INDEX_TOKENS
            )
        ),
        "first_block_time": min((row["block_time_utc"] for row in rows), default=None),
        "last_block_time": max((row["block_time_utc"] for row in rows), default=None),
    }


def evaluate_gate(
    result: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, bool]:
    btc_eth = [row for row in records if row["asset"] in INDEX_TOKENS]
    identity_keys = [
        (row["block_hash"], row["transaction_hash"], row["log_index"])
        for row in records
    ]
    non_empty_windows = sum(
        int(summary["btc_eth_logs"]) > 0
        for summary in result["window_summaries"].values()
    )
    assets = {row["asset"] for row in btc_eth}
    sides = {row["liquidated_position_side"] for row in btc_eth}
    return {
        "canonical_chain_vault_and_historical_rpc": bool(
            result.get("endpoint_probe", {}).get("selected")
        ),
        "decode_errors_zero": len(result["decode_errors"]) == 0,
        "removed_logs_zero": all(not row["removed"] for row in records),
        "duplicate_identity_zero": len(identity_keys) == len(set(identity_keys)),
        "timestamps_complete": all(
            isinstance(row.get("block_timestamp"), int) for row in records
        ),
        "at_least_twenty_btc_eth_liquidations": len(btc_eth) >= 20,
        "at_least_four_non_empty_windows": non_empty_windows >= 4,
        "both_btc_and_eth": assets == {"BTC", "ETH"},
        "both_liquidated_sides": sides == {"LONG", "SHORT"},
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
        "chain_id": CHAIN_ID,
        "vault": VAULT,
        "event_signature": LIQUIDATE_POSITION_SIGNATURE,
        "event_topic0": LIQUIDATE_POSITION_TOPIC,
        "index_tokens": INDEX_TOKENS,
        "information_delay_seconds": INFORMATION_DELAY_SECONDS,
        "probe_windows": [
            {"start_utc": start, "end_exclusive_utc": end}
            for start, end in PROBE_WINDOWS
        ],
        "endpoint_probe": {},
        "window_ranges": {},
        "window_summaries": {},
        "decode_errors": [],
        "forbidden_outcome_fields": [
            "market_price",
            "future_return",
            "first_passage_label",
            "model_metric",
            "action",
            "trade",
            "pnl",
            "account_nav",
            "official_2024_2026",
            "credential",
            "order",
        ],
    }
    decoded_records: list[dict[str, Any]] = []
    raw_logs_by_window: list[tuple[str, dict[str, Any]]] = []
    try:
        rpc, endpoint_probe, locator = choose_endpoint(ENDPOINTS)
        result["endpoint_probe"] = endpoint_probe
        for start_text, end_text in PROBE_WINDOWS:
            key = window_key(start_text, end_text)
            start_ts = parse_utc(start_text)
            end_ts = parse_utc(end_text)
            start_block = locator.first_at_or_after(start_ts)
            next_block = locator.first_at_or_after(end_ts)
            end_block = max(start_block, next_block - 1)
            result["window_ranges"][key] = {
                "from_block": start_block,
                "to_block": end_block,
                "from_block_time": utc_iso(locator.timestamp(start_block)),
                "to_block_time": utc_iso(locator.timestamp(end_block)),
            }
            logs = get_logs_adaptive(
                rpc,
                address=VAULT,
                from_block=start_block,
                to_block=end_block,
                topic0=LIQUIDATE_POSITION_TOPIC,
            )
            for log in logs:
                raw_logs_by_window.append((key, log))
        block_numbers = sorted(
            {hex_int(log["blockNumber"]) for _, log in raw_logs_by_window}
        )
        timestamps = rpc.batch_block_timestamps(block_numbers)
        by_window: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        for key, log in raw_logs_by_window:
            try:
                block_number = hex_int(log["blockNumber"])
                decoded = decode_liquidation_log(
                    log,
                    block_timestamp=timestamps[block_number],
                    probe_window=key,
                )
                by_window[key].append(decoded)
                decoded_records.append(decoded)
            except Exception as exc:
                result["decode_errors"].append(
                    {
                        "probe_window": key,
                        "error": repr(exc),
                        "raw_log": log,
                    }
                )
        decoded_records.sort(
            key=lambda row: (
                row["block_number"],
                row["transaction_index"],
                row["log_index"],
            )
        )
        for start_text, end_text in PROBE_WINDOWS:
            key = window_key(start_text, end_text)
            rows = sorted(
                by_window.get(key, []),
                key=lambda row: (
                    row["block_number"],
                    row["transaction_index"],
                    row["log_index"],
                ),
            )
            result["window_summaries"][key] = summarize(rows)
        checks = evaluate_gate(result, decoded_records)
        btc_eth = [row for row in decoded_records if row["asset"] in INDEX_TOKENS]
        result["totals"] = {
            "decoded_logs": len(decoded_records),
            "btc_eth_liquidations": len(btc_eth),
            "unique_transactions": len(
                {row["transaction_hash"] for row in decoded_records}
            ),
            "unique_blocks": len({row["block_number"] for row in decoded_records}),
            "decode_error_count": len(result["decode_errors"]),
            "assets": dict(
                sorted(collections.Counter(row["asset"] for row in decoded_records).items())
            ),
            "sides_btc_eth": dict(
                sorted(
                    collections.Counter(
                        row["liquidated_position_side"] for row in btc_eth
                    ).items()
                )
            ),
            "size_usd_sum_btc_eth": decimal_1e30(
                sum(int(row["size_raw_1e30"]) for row in btc_eth)
            ),
            "rpc_stats": vars(rpc.stats),
        }
        result["source_gate_checks"] = checks
        result["source_gate_pass"] = all(checks.values())
        result["scientific_decision"] = (
            "OPEN_FROZEN_PRE2024_HISTORY_AND_MODEL_STAGE"
            if result["source_gate_pass"]
            else "CLOSE_SOURCE_ROUTE_BEFORE_MARKET_OUTCOMES"
        )
    except Exception as exc:
        result["fatal_error"] = repr(exc)
        result["source_gate_pass"] = False
        result["scientific_decision"] = "CLOSE_SOURCE_ROUTE_BEFORE_MARKET_OUTCOMES"
    raw_path = args.output / "RAW_GMX_V1_LIQUIDATIONS.jsonl.gz"
    with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
        for row in decoded_records:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False))
            handle.write("\n")
    result_path = args.output / "SOURCE_GATE_RESULT.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest = {
        "SOURCE_GATE_RESULT.json": sha256_file(result_path),
        "RAW_GMX_V1_LIQUIDATIONS.jsonl.gz": sha256_file(raw_path),
    }
    (args.output / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(result_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
