from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_TOPIC = "0x" + "0" * 64
CHAIN_ID_MAINNET = 1
MAX_ALLOWED_TIMESTAMP = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())

CONTRACTS = {
    "USDT": {
        "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "decimals": 6,
    },
    "USDC": {
        "address": "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "decimals": 6,
    },
}

FIXED_MONTHS = tuple(
    f"{year}-{month:02d}"
    for year in (2021, 2022, 2023)
    for month in range(1, 13)
)

DEFAULT_ENDPOINTS = (
    "https://ethereum-rpc.publicnode.com",
    "https://eth.llamarpc.com",
    "https://1rpc.io/eth",
    "https://rpc.ankr.com/eth",
)


@dataclass(frozen=True)
class Event:
    token: str
    direction: str
    contract: str
    block_number: int
    tx_hash: str
    log_index: int
    amount_raw: int
    amount_usd: float
    from_address: str
    to_address: str
    block_timestamp: int
    available_block_12: int
    available_timestamp_12: int
    available_block_64: int
    available_timestamp_64: int

    @property
    def event_id(self) -> str:
        payload = f"{self.contract.lower()}|{self.tx_hash.lower()}|{self.log_index}"
        return hashlib.sha256(payload.encode()).hexdigest()[:24]


class RpcError(RuntimeError):
    pass


class RpcClient:
    def __init__(self, endpoints: Iterable[str], timeout: int = 45) -> None:
        self.endpoints = tuple(endpoints)
        if not self.endpoints:
            raise ValueError("at least one endpoint is required")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SMC_ICT_2_LIVE-stablecoin-source-gate/1.0"
        self.endpoint: str | None = None
        self.request_count = 0
        self.errors: list[str] = []

    def _call_endpoint(self, endpoint: str, method: str, params: list[Any]) -> Any:
        request_id = self.request_count + 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        response = self.session.post(endpoint, json=payload, timeout=self.timeout)
        self.request_count += 1
        if response.status_code != 200:
            raise RpcError(f"{endpoint} {method}: HTTP {response.status_code}")
        body = response.json()
        if body.get("error") is not None:
            raise RpcError(f"{endpoint} {method}: {body['error']}")
        if "result" not in body:
            raise RpcError(f"{endpoint} {method}: missing result")
        return body["result"]

    def select(self) -> dict[str, Any]:
        diagnostics: list[dict[str, Any]] = []
        for endpoint in self.endpoints:
            item: dict[str, Any] = {"endpoint": endpoint}
            try:
                chain_id = int(self._call_endpoint(endpoint, "eth_chainId", []), 16)
                latest_hex = self._call_endpoint(endpoint, "eth_blockNumber", [])
                latest = int(latest_hex, 16)
                block = self._call_endpoint(endpoint, "eth_getBlockByNumber", [hex(latest), False])
                if not block:
                    raise RpcError("latest block unavailable")
                latest_timestamp = int(block["timestamp"], 16)
                item.update(
                    status="PASS",
                    chain_id=chain_id,
                    latest_block=latest,
                    latest_timestamp=latest_timestamp,
                )
                diagnostics.append(item)
                if chain_id == CHAIN_ID_MAINNET and latest_timestamp >= MAX_ALLOWED_TIMESTAMP:
                    self.endpoint = endpoint
                    return {"selected": endpoint, "diagnostics": diagnostics}
            except Exception as exc:
                item.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
                diagnostics.append(item)
                self.errors.append(item["error"])
        raise RpcError("no keyless Ethereum mainnet endpoint passed: " + " | ".join(self.errors[-8:]))

    def call(self, method: str, params: list[Any], retries: int = 4) -> Any:
        if self.endpoint is None:
            raise RpcError("endpoint is not selected")
        last: Exception | None = None
        for attempt in range(retries):
            try:
                return self._call_endpoint(self.endpoint, method, params)
            except Exception as exc:
                last = exc
                self.errors.append(f"{method}: {type(exc).__name__}: {exc}")
                time.sleep(min(2 ** attempt, 8))
        raise RpcError(f"{method} failed after {retries} attempts: {last}")


def month_bounds(token: str) -> tuple[int, int]:
    start = datetime.strptime(token + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if start.year >= 2024:
        raise ValueError("official 2024+ source is prohibited")
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(start.year, start.month + 1, 1, tzinfo=timezone.utc)
    return int(start.timestamp()), int(end.timestamp())


def normalize_address_topic(topic: str) -> str:
    value = topic.lower().removeprefix("0x")
    if len(value) != 64:
        raise ValueError("invalid address topic")
    return "0x" + value[-40:]


def decode_log(token: str, direction: str, log: dict[str, Any]) -> dict[str, Any]:
    topics = log.get("topics") or []
    if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC:
        raise ValueError("not an ERC20 Transfer log")
    from_address = normalize_address_topic(topics[1])
    to_address = normalize_address_topic(topics[2])
    if direction == "MINT" and topics[1].lower() != ZERO_TOPIC:
        raise ValueError("mint filter mismatch")
    if direction == "BURN" and topics[2].lower() != ZERO_TOPIC:
        raise ValueError("burn filter mismatch")
    amount_raw = int(log.get("data", "0x0"), 16)
    contract = str(log["address"]).lower()
    expected = CONTRACTS[token]["address"].lower()
    if contract != expected:
        raise ValueError(f"contract mismatch {contract} != {expected}")
    return {
        "token": token,
        "direction": direction,
        "contract": contract,
        "block_number": int(log["blockNumber"], 16),
        "tx_hash": str(log["transactionHash"]).lower(),
        "log_index": int(log["logIndex"], 16),
        "amount_raw": amount_raw,
        "amount_usd": amount_raw / (10 ** int(CONTRACTS[token]["decimals"])),
        "from_address": from_address,
        "to_address": to_address,
    }


def block_timestamp(client: RpcClient, block_number: int, cache: dict[int, int]) -> int:
    if block_number not in cache:
        block = client.call("eth_getBlockByNumber", [hex(block_number), False])
        if not block:
            raise RpcError(f"block {block_number} unavailable")
        cache[block_number] = int(block["timestamp"], 16)
    return cache[block_number]


def first_block_at_or_after(
    client: RpcClient,
    target_timestamp: int,
    low: int,
    high: int,
    cache: dict[int, int],
) -> int:
    if target_timestamp >= MAX_ALLOWED_TIMESTAMP:
        raise ValueError("2024+ timestamp prohibited")
    if block_timestamp(client, low, cache) >= target_timestamp:
        return low
    if block_timestamp(client, high, cache) < target_timestamp:
        raise RpcError("latest block predates requested target")
    while low + 1 < high:
        mid = (low + high) // 2
        if block_timestamp(client, mid, cache) >= target_timestamp:
            high = mid
        else:
            low = mid
    return high


def query_logs_adaptive(
    client: RpcClient,
    address: str,
    topics: list[Any],
    start_block: int,
    end_block: int,
    initial_span: int = 200_000,
    minimum_span: int = 500,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    out: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    cursor = start_block
    span = min(initial_span, max(1, end_block - start_block + 1))
    while cursor <= end_block:
        stop = min(end_block, cursor + span - 1)
        params = [{
            "address": address,
            "fromBlock": hex(cursor),
            "toBlock": hex(stop),
            "topics": topics,
        }]
        try:
            logs = client.call("eth_getLogs", params, retries=2)
            diagnostics.append({
                "from_block": cursor,
                "to_block": stop,
                "span": stop - cursor + 1,
                "status": "PASS",
                "log_count": len(logs),
            })
            out.extend(logs)
            cursor = stop + 1
            if span < initial_span:
                span = min(initial_span, span * 2)
        except Exception as exc:
            diagnostics.append({
                "from_block": cursor,
                "to_block": stop,
                "span": stop - cursor + 1,
                "status": "RETRY_SMALLER",
                "error": f"{type(exc).__name__}: {exc}",
            })
            if span <= minimum_span:
                raise
            span = max(minimum_span, span // 2)
    return out, diagnostics


def event_to_dict(event: Event) -> dict[str, Any]:
    row = asdict(event)
    row["event_id"] = event.event_id
    return row


def source_gate(
    output: Path,
    endpoints: Iterable[str] = DEFAULT_ENDPOINTS,
    fixed_months: Iterable[str] = FIXED_MONTHS,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    client = RpcClient(endpoints)
    selection = client.select()
    latest = int(client.call("eth_blockNumber", []), 16)
    cache: dict[int, int] = {}
    latest_timestamp = block_timestamp(client, latest, cache)

    contract_checks: dict[str, Any] = {}
    for token, spec in CONTRACTS.items():
        code = client.call("eth_getCode", [spec["address"], "latest"])
        contract_checks[token] = {
            "address": spec["address"],
            "code_bytes": max(0, (len(code.removeprefix("0x")) // 2)),
            "has_bytecode": code not in ("0x", "0x0", None),
        }

    month_ranges: list[dict[str, Any]] = []
    previous_low = 0
    for month in fixed_months:
        start_ts, end_ts = month_bounds(month)
        start_block = first_block_at_or_after(client, start_ts, previous_low, latest, cache)
        end_exclusive = first_block_at_or_after(client, end_ts, start_block, latest, cache)
        end_block = end_exclusive - 1
        if end_block < start_block:
            raise RuntimeError(f"invalid block range for {month}")
        month_ranges.append({
            "month": month,
            "start_timestamp": start_ts,
            "end_timestamp_exclusive": end_ts,
            "start_block": start_block,
            "end_block": end_block,
            "start_block_timestamp": block_timestamp(client, start_block, cache),
            "end_block_timestamp": block_timestamp(client, end_block, cache),
        })
        previous_low = start_block

    decoded: list[dict[str, Any]] = []
    query_diagnostics: list[dict[str, Any]] = []
    for period in month_ranges:
        for token, spec in CONTRACTS.items():
            filters = (
                ("MINT", [TRANSFER_TOPIC, ZERO_TOPIC]),
                ("BURN", [TRANSFER_TOPIC, None, ZERO_TOPIC]),
            )
            for direction, topics in filters:
                logs, diag = query_logs_adaptive(
                    client,
                    spec["address"],
                    topics,
                    period["start_block"],
                    period["end_block"],
                )
                query_diagnostics.append({
                    "month": period["month"],
                    "token": token,
                    "direction": direction,
                    "chunks": diag,
                    "log_count": len(logs),
                })
                for log in logs:
                    row = decode_log(token, direction, log)
                    row["month"] = period["month"]
                    decoded.append(row)

    unique: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in decoded:
        key = (row["contract"], row["tx_hash"], row["log_index"])
        prior = unique.get(key)
        if prior is not None and prior != row:
            raise RuntimeError(f"conflicting duplicate event {key}")
        unique[key] = row

    events: list[Event] = []
    for row in sorted(unique.values(), key=lambda x: (x["block_number"], x["log_index"])):
        block_no = int(row["block_number"])
        ts = block_timestamp(client, block_no, cache)
        if ts >= MAX_ALLOWED_TIMESTAMP:
            raise RuntimeError("2024+ event leaked into source gate")
        a12 = min(block_no + 12, latest)
        a64 = min(block_no + 64, latest)
        events.append(Event(
            token=row["token"],
            direction=row["direction"],
            contract=row["contract"],
            block_number=block_no,
            tx_hash=row["tx_hash"],
            log_index=int(row["log_index"]),
            amount_raw=int(row["amount_raw"]),
            amount_usd=float(row["amount_usd"]),
            from_address=row["from_address"],
            to_address=row["to_address"],
            block_timestamp=ts,
            available_block_12=a12,
            available_timestamp_12=block_timestamp(client, a12, cache),
            available_block_64=a64,
            available_timestamp_64=block_timestamp(client, a64, cache),
        ))

    months_with_events = sorted({
        datetime.fromtimestamp(e.block_timestamp, tz=timezone.utc).strftime("%Y-%m")
        for e in events
    })
    distinct_tokens = sorted({e.token for e in events})
    pass_checks = {
        "chain_id_mainnet": int(client.call("eth_chainId", []), 16) == CHAIN_ID_MAINNET,
        "both_contracts_have_bytecode": all(x["has_bytecode"] for x in contract_checks.values()),
        "all_fixed_months_resolved": len(month_ranges) == len(tuple(fixed_months)),
        "all_events_pre_2024": all(e.block_timestamp < MAX_ALLOWED_TIMESTAMP for e in events),
        "minimum_unique_events": len(events) >= 120,
        "minimum_months_with_events": len(months_with_events) >= 24,
        "minimum_distinct_tokens": len(distinct_tokens) >= 2,
    }
    status = "PASS" if all(pass_checks.values()) else "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE"

    event_rows = [event_to_dict(e) for e in events]
    event_path = output / "EVENTS.jsonl"
    event_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in event_rows),
        encoding="utf-8",
    )
    events_sha = hashlib.sha256(event_path.read_bytes()).hexdigest()

    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001",
        "phase": "OUTCOME_SEALED_SOURCE_GATE",
        "selected_endpoint": selection["selected"],
        "endpoint_diagnostics": selection["diagnostics"],
        "latest_block_observed": latest,
        "latest_timestamp_observed": latest_timestamp,
        "contracts": contract_checks,
        "fixed_months": list(fixed_months),
        "month_ranges": month_ranges,
        "query_diagnostics": query_diagnostics,
        "request_count": client.request_count,
        "events_file": event_path.name,
        "events_sha256": events_sha,
        "event_count": len(events),
        "months_with_events": months_with_events,
        "distinct_tokens": distinct_tokens,
        "event_direction_counts": {
            direction: sum(e.direction == direction for e in events)
            for direction in ("MINT", "BURN")
        },
        "token_counts": {
            token: sum(e.token == token for e in events)
            for token in CONTRACTS
        },
        "causal_availability": {
            "primary": "event block plus 12 subsequent blocks",
            "stress": "event block plus 64 subsequent blocks",
        },
        "market_outcome_opened": False,
        "model_fit": False,
        "trade_or_pnl_opened": False,
        "official_2024_2026_opened": False,
        "credentials_used": False,
        "orders_submitted": False,
    }
    (output / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = {
        "schema_version": 1,
        "claim_id": manifest["claim_id"],
        "status": status,
        "pass_checks": pass_checks,
        "event_count": len(events),
        "months_with_events": months_with_events,
        "distinct_tokens": distinct_tokens,
        "event_direction_counts": manifest["event_direction_counts"],
        "token_counts": manifest["token_counts"],
        "conditional_model_screen_authorized": status == "PASS",
        "market_outcome_opened": False,
        "model_fit": False,
        "trade_or_pnl_opened": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    (output / "SOURCE_GATE_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def self_test() -> None:
    assert month_bounds("2023-12")[1] == int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    log = {
        "address": CONTRACTS["USDT"]["address"],
        "topics": [
            TRANSFER_TOPIC,
            ZERO_TOPIC,
            "0x" + "0" * 24 + "1234567890abcdef1234567890abcdef12345678",
        ],
        "data": hex(125_000_000 * 10**6),
        "blockNumber": hex(17_000_000),
        "transactionHash": "0x" + "ab" * 32,
        "logIndex": "0x2",
    }
    row = decode_log("USDT", "MINT", log)
    assert row["amount_usd"] == 125_000_000
    assert row["from_address"] == "0x" + "0" * 40
    assert row["to_address"] == "0x1234567890abcdef1234567890abcdef12345678"
    event = Event(
        token="USDT",
        direction="MINT",
        contract=CONTRACTS["USDT"]["address"].lower(),
        block_number=17_000_000,
        tx_hash=log["transactionHash"],
        log_index=2,
        amount_raw=row["amount_raw"],
        amount_usd=row["amount_usd"],
        from_address=row["from_address"],
        to_address=row["to_address"],
        block_timestamp=1_680_000_000,
        available_block_12=17_000_012,
        available_timestamp_12=1_680_000_144,
        available_block_64=17_000_064,
        available_timestamp_64=1_680_000_768,
    )
    assert len(event.event_id) == 24
    assert event_to_dict(event)["event_id"] == event.event_id
    print("self-test passed")


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
    endpoints = tuple(args.endpoint) if args.endpoint else DEFAULT_ENDPOINTS
    result = source_gate(args.output, endpoints=endpoints)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
