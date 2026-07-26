from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
CHAIN_ID_MAINNET = 1
BLOCKSCOUT_API = "https://eth.blockscout.com/api"
BLOCKSCOUT_REST = "https://eth.blockscout.com/api/v2"
PERIOD_START = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp())
PERIOD_END_EXCLUSIVE = int(datetime(2023, 2, 1, tzinfo=timezone.utc).timestamp())
MAX_LOGS = 1_000
MIN_REQUEST_INTERVAL_SECONDS = 0.22

BYBIT_ADDRESSES = tuple(
    address.lower()
    for address in (
        "0xf89d7b9c864f589bbF53a82105107622B35EaA40",
        "0x1Db92e2EeBC8E0c075a02BeA49a2935BcD2dFCF4",
        "0xA7A93fd0a276fc1C0197a5B5623eD117786eeD06",
        "0xee5B5B923fFcE93A870B3104b7CA09c3db80047A",
    )
)
BYBIT_SET = frozenset(BYBIT_ADDRESSES)
TOKENS = {
    "USDT": {"address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "decimals": 6},
    "USDC": {"address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "decimals": 6},
}
RPC_ENDPOINTS = (
    "https://ethereum-rpc.publicnode.com",
    "https://eth.llamarpc.com",
    "https://1rpc.io/eth",
    "https://rpc.ankr.com/eth",
)


class SourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Event:
    token: str
    direction: str
    contract: str
    block_number: int
    transaction_hash: str
    log_index: int
    amount_raw: int
    amount_usd: float
    from_address: str
    to_address: str
    bybit_address: str
    block_timestamp: int
    available_block_12: int
    available_timestamp_12: int

    @property
    def event_id(self) -> str:
        raw = f"{self.contract}|{self.transaction_hash}|{self.log_index}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]


def parse_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(text)


def parse_iso_timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp())


def normalize_address(value: str) -> str:
    text = value.lower().removeprefix("0x")
    if len(text) == 64:
        text = text[-40:]
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"invalid address: {value}")
    return "0x" + text


def address_topic(address: str) -> str:
    return "0x" + "0" * 24 + normalize_address(address)[2:]


def canonical_rows_hash(rows: Iterable[dict[str, Any]]) -> str:
    payload = [
        {
            "contract": str(row["contract"]).lower(),
            "transaction_hash": str(row["transaction_hash"]).lower(),
            "log_index": int(row["log_index"]),
            "direction": str(row["direction"]),
            "amount_raw": int(row["amount_raw"]),
            "from_address": str(row["from_address"]).lower(),
            "to_address": str(row["to_address"]).lower(),
        }
        for row in rows
    ]
    payload.sort(key=lambda row: (row["contract"], row["transaction_hash"], row["log_index"]))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def decode_transfer(token: str, log: dict[str, Any]) -> dict[str, Any] | None:
    topics = log.get("topics") or []
    if len(topics) < 3 or str(topics[0]).lower() != TRANSFER_TOPIC:
        raise ValueError("not an ERC20 Transfer log")
    contract = str(log.get("address", "")).lower()
    if contract != TOKENS[token]["address"]:
        raise ValueError(f"contract mismatch: {contract}")
    from_address = normalize_address(str(topics[1]))
    to_address = normalize_address(str(topics[2]))
    from_bybit = from_address in BYBIT_SET
    to_bybit = to_address in BYBIT_SET
    if from_bybit and to_bybit:
        return None
    if not from_bybit and not to_bybit:
        return None
    direction = "INFLOW" if to_bybit else "OUTFLOW"
    bybit_address = to_address if to_bybit else from_address
    amount_raw = parse_int(log.get("data", "0x0"))
    return {
        "token": token,
        "direction": direction,
        "contract": contract,
        "block_number": parse_int(log["blockNumber"]),
        "transaction_hash": str(log["transactionHash"]).lower(),
        "log_index": parse_int(log["logIndex"]),
        "amount_raw": amount_raw,
        "amount_usd": amount_raw / (10 ** int(TOKENS[token]["decimals"])),
        "from_address": from_address,
        "to_address": to_address,
        "bybit_address": bybit_address,
    }


class BlockscoutClient:
    def __init__(self, timeout: int = 60) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SMC_ICT_2_LIVE-bybit-reserve-netflow/1.0"
        self.last_request_at = 0.0
        self.request_count = 0
        self.errors: list[str] = []
        self.block_timestamp_cache: dict[int, int] = {}

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)

    def get_json(self, url: str, params: dict[str, Any] | None = None, retries: int = 4) -> Any:
        last: Exception | None = None
        for attempt in range(retries):
            try:
                self._throttle()
                response = self.session.get(url, params=params, timeout=self.timeout)
                self.last_request_at = time.monotonic()
                self.request_count += 1
                if response.status_code != 200:
                    raise SourceError(f"HTTP {response.status_code}: {response.text[:240]}")
                return response.json()
            except Exception as exc:
                last = exc
                self.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                time.sleep(min(2**attempt, 8))
        raise SourceError(f"request failed after {retries} attempts: {last}")

    def block_by_time(self, timestamp: int, closest: str = "after") -> int:
        body = self.get_json(
            BLOCKSCOUT_API,
            {
                "module": "block",
                "action": "getblocknobytime",
                "timestamp": timestamp,
                "closest": closest,
            },
        )
        if str(body.get("status")) != "1":
            raise SourceError(f"getblocknobytime failed: {body}")
        result = body.get("result")
        if isinstance(result, dict):
            result = result.get("blockNumber")
        return parse_int(result)

    def block_timestamp(self, block_number: int) -> int:
        if block_number not in self.block_timestamp_cache:
            body = self.get_json(f"{BLOCKSCOUT_REST}/blocks/{block_number}")
            if parse_int(body.get("height")) != block_number:
                raise SourceError(f"block identity mismatch: {block_number}")
            self.block_timestamp_cache[block_number] = parse_iso_timestamp(str(body["timestamp"]))
        return self.block_timestamp_cache[block_number]

    def address_info(self, address: str) -> dict[str, Any]:
        body = self.get_json(f"{BLOCKSCOUT_REST}/addresses/{address}")
        observed = normalize_address(str(body.get("hash") or body.get("address") or address))
        if observed != normalize_address(address):
            raise SourceError(f"address identity mismatch: {observed} != {address}")
        return {
            "address": normalize_address(address),
            "is_contract": bool(body.get("is_contract", False)),
            "is_verified": bool(body.get("is_verified", False)),
            "name": body.get("name"),
        }

    def _params(self, token: str, direction: str, bybit_address: str, start_block: int, end_block: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "module": "logs",
            "action": "getLogs",
            "fromBlock": start_block,
            "toBlock": end_block,
            "address": TOKENS[token]["address"],
            "topic0": TRANSFER_TOPIC,
        }
        topic = address_topic(bybit_address)
        if direction == "INFLOW":
            params.update(topic2=topic, topic0_2_opr="and")
        elif direction == "OUTFLOW":
            params.update(topic1=topic, topic0_1_opr="and")
        else:
            raise ValueError(direction)
        return params

    def logs(
        self,
        token: str,
        direction: str,
        bybit_address: str,
        start_block: int,
        end_block: int,
        diagnostics: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        body = self.get_json(BLOCKSCOUT_API, self._params(token, direction, bybit_address, start_block, end_block))
        status = str(body.get("status"))
        result = body.get("result")
        if status == "0":
            message = str(body.get("message", ""))
            if result in ([], None, "") or "no" in message.lower():
                diagnostics.append({"from_block": start_block, "to_block": end_block, "status": "PASS_EMPTY", "log_count": 0})
                return []
            raise SourceError(f"getLogs failed: {body}")
        if status != "1" or not isinstance(result, list):
            raise SourceError(f"unexpected getLogs response: {body}")
        diagnostics.append({"from_block": start_block, "to_block": end_block, "status": "PASS", "log_count": len(result)})
        if len(result) < MAX_LOGS:
            return result
        if start_block >= end_block:
            raise SourceError("single block reached Blockscout log ceiling")
        mid = (start_block + end_block) // 2
        diagnostics[-1]["status"] = "SPLIT_AT_LIMIT"
        return self.logs(token, direction, bybit_address, start_block, mid, diagnostics) + self.logs(
            token, direction, bybit_address, mid + 1, end_block, diagnostics
        )


class RpcClient:
    def __init__(self, endpoints: Iterable[str] = RPC_ENDPOINTS, timeout: int = 45) -> None:
        self.endpoints = tuple(endpoints)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SMC_ICT_2_LIVE-bybit-reserve-verify/1.0"
        self.attempts: list[dict[str, Any]] = []

    def call(self, endpoint: str, method: str, params: list[Any]) -> Any:
        response = self.session.post(
            endpoint,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise SourceError(f"HTTP {response.status_code}")
        body = response.json()
        if body.get("error") is not None:
            raise SourceError(str(body["error"]))
        if "result" not in body:
            raise SourceError("missing result")
        return body["result"]

    def query_filtered(self, endpoint: str, token: str, direction: str, bybit_address: str, start_block: int, end_block: int) -> list[dict[str, Any]]:
        topics: list[Any] = [TRANSFER_TOPIC]
        if direction == "INFLOW":
            topics += [None, address_topic(bybit_address)]
        else:
            topics += [address_topic(bybit_address)]
        params = [{"address": TOKENS[token]["address"], "fromBlock": hex(start_block), "toBlock": hex(end_block), "topics": topics}]
        result = self.call(endpoint, "eth_getLogs", params)
        if not isinstance(result, list):
            raise SourceError("eth_getLogs did not return a list")
        return result

    def verify(self, primary_rows: list[dict[str, Any]], start_block: int, end_block: int) -> dict[str, Any]:
        expected = [row for row in primary_rows if start_block <= int(row["block_number"]) <= end_block]
        expected_hash = canonical_rows_hash(expected)
        for endpoint in self.endpoints:
            attempt: dict[str, Any] = {"endpoint": endpoint, "start_block": start_block, "end_block": end_block}
            try:
                chain_id = parse_int(self.call(endpoint, "eth_chainId", []))
                if chain_id != CHAIN_ID_MAINNET:
                    raise SourceError(f"chain id {chain_id}")
                raw_logs: list[dict[str, Any]] = []
                for token in TOKENS:
                    for address in BYBIT_ADDRESSES:
                        for direction in ("INFLOW", "OUTFLOW"):
                            raw_logs.extend(self.query_filtered(endpoint, token, direction, address, start_block, end_block))
                rows: dict[tuple[str, str, int], dict[str, Any]] = {}
                for token, spec in TOKENS.items():
                    for log in raw_logs:
                        if str(log.get("address", "")).lower() != spec["address"]:
                            continue
                        decoded = decode_transfer(token, log)
                        if decoded is None:
                            continue
                        key = (decoded["contract"], decoded["transaction_hash"], int(decoded["log_index"]))
                        rows[key] = decoded
                observed = list(rows.values())
                observed_hash = canonical_rows_hash(observed)
                matched = bool(expected) and observed_hash == expected_hash
                attempt.update(status="PASS" if matched else "HASH_MISMATCH", expected_count=len(expected), observed_count=len(observed), expected_hash=expected_hash, observed_hash=observed_hash)
                self.attempts.append(attempt)
                if matched:
                    return {"matched": True, "endpoint": endpoint, "expected_count": len(expected), "observed_count": len(observed), "canonical_hash": expected_hash, "attempts": self.attempts}
            except Exception as exc:
                attempt.update(status="ERROR", error=f"{type(exc).__name__}: {exc}")
                self.attempts.append(attempt)
        return {"matched": False, "endpoint": None, "expected_count": len(expected), "canonical_hash": expected_hash, "attempts": self.attempts}


def choose_verification_range(rows: list[dict[str, Any]], period_start_block: int, period_end_block: int) -> tuple[int, int]:
    if not rows:
        return period_start_block, min(period_end_block, period_start_block + 1_999)
    blocks = sorted({int(row["block_number"]) for row in rows})
    anchor = blocks[min(len(blocks) // 2, len(blocks) - 1)]
    start = max(period_start_block, anchor - 600)
    end = min(period_end_block, anchor + 600)
    return start, end


def source_gate(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    client = BlockscoutClient()
    token_identity = {token: client.address_info(spec["address"]) for token, spec in TOKENS.items()}
    bybit_identity = {address: client.address_info(address) for address in BYBIT_ADDRESSES}
    if not all(item["is_contract"] for item in token_identity.values()):
        raise SourceError(f"token identity failed: {token_identity}")

    start_block = client.block_by_time(PERIOD_START, "after")
    end_exclusive = client.block_by_time(PERIOD_END_EXCLUSIVE, "after")
    end_block = end_exclusive - 1
    if client.block_timestamp(start_block) < PERIOD_START or client.block_timestamp(end_block) >= PERIOD_END_EXCLUSIVE:
        raise SourceError("period block boundary mismatch")

    raw_logs: list[tuple[str, dict[str, Any]]] = []
    query_diagnostics: list[dict[str, Any]] = []
    for token in TOKENS:
        for address in BYBIT_ADDRESSES:
            for direction in ("INFLOW", "OUTFLOW"):
                chunks: list[dict[str, Any]] = []
                logs = client.logs(token, direction, address, start_block, end_block, chunks)
                query_diagnostics.append({"token": token, "bybit_address": address, "direction": direction, "chunks": chunks, "raw_log_count": len(logs)})
                raw_logs.extend((token, log) for log in logs)

    decoded: dict[tuple[str, str, int], dict[str, Any]] = {}
    for token, log in raw_logs:
        row = decode_transfer(token, log)
        if row is None:
            continue
        key = (row["contract"], row["transaction_hash"], int(row["log_index"]))
        prior = decoded.get(key)
        if prior is not None and prior != row:
            raise SourceError(f"conflicting duplicate event {key}")
        decoded[key] = row

    rows = sorted(decoded.values(), key=lambda row: (int(row["block_number"]), int(row["log_index"])))
    events: list[Event] = []
    for row in rows:
        block = int(row["block_number"])
        block_ts = client.block_timestamp(block)
        if not (PERIOD_START <= block_ts < PERIOD_END_EXCLUSIVE):
            raise SourceError(f"event outside frozen period: {block_ts}")
        events.append(Event(**row, block_timestamp=block_ts, available_block_12=block + 12, available_timestamp_12=client.block_timestamp(block + 12)))

    event_rows = [{**asdict(event), "event_id": event.event_id} for event in events]
    event_path = output / "EVENTS.jsonl"
    event_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in event_rows), encoding="utf-8")

    verify_start, verify_end = choose_verification_range(event_rows, start_block, end_block)
    verification = RpcClient().verify(event_rows, verify_start, verify_end)
    unique_finality_times = len({event.available_timestamp_12 for event in events})
    direction_counts = {direction: sum(event.direction == direction for event in events) for direction in ("INFLOW", "OUTFLOW")}
    token_counts = {token: sum(event.token == token for event in events) for token in TOKENS}
    large_counts = {str(threshold): sum(event.amount_usd >= threshold for event in events) for threshold in (100_000, 1_000_000, 10_000_000)}
    gross = {direction: sum(event.amount_usd for event in events if event.direction == direction) for direction in ("INFLOW", "OUTFLOW")}
    net = gross["INFLOW"] - gross["OUTFLOW"]
    pass_checks = {
        "minimum_external_events": len(events) >= 100,
        "minimum_unique_finality_times": unique_finality_times >= 30,
        "minimum_million_events": large_counts["1000000"] >= 20,
        "minimum_inflows": direction_counts["INFLOW"] >= 10,
        "minimum_outflows": direction_counts["OUTFLOW"] >= 10,
        "independent_rpc_hash_match": verification["matched"] is True,
        "both_tokens_present": all(token_counts[token] > 0 for token in TOKENS),
        "all_events_pre_february": all(PERIOD_START <= event.block_timestamp < PERIOD_END_EXCLUSIVE for event in events),
    }
    status = "PASS" if all(pass_checks.values()) else "FAIL_SOURCE_GATE"
    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-1710-BYBIT-RESERVE-NETFLOW-001",
        "phase": "OUTCOME_SEALED_SOURCE_GATE",
        "provider": "Blockscout Ethereum API with independent JSON-RPC bounded verification",
        "period": {"start": PERIOD_START, "end_exclusive": PERIOD_END_EXCLUSIVE, "start_block": start_block, "end_block": end_block},
        "address_authority": "Bybit official balance-checker Proof-of-Reserves-era Ethereum configuration; labels usable after 2022-12-12",
        "bybit_addresses": list(BYBIT_ADDRESSES),
        "token_identity": token_identity,
        "bybit_address_identity": bybit_identity,
        "query_diagnostics": query_diagnostics,
        "blockscout_request_count": client.request_count,
        "blockscout_errors": client.errors[-20:],
        "event_count": len(events),
        "event_file": event_path.name,
        "event_file_sha256": hashlib.sha256(event_path.read_bytes()).hexdigest(),
        "canonical_event_hash": canonical_rows_hash(event_rows),
        "unique_finality_times": unique_finality_times,
        "direction_counts": direction_counts,
        "token_counts": token_counts,
        "large_event_counts": large_counts,
        "gross_amount_usd": gross,
        "net_amount_usd": net,
        "verification": verification,
        "pass_checks": pass_checks,
        "status": status,
        "market_outcome_opened": False,
        "model_fit": False,
        "trade_or_pnl_opened": False,
        "official_2024_2026_opened": False,
        "credentials_used": False,
        "orders_submitted": False,
    }
    (output / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "schema_version": 1,
        "claim_id": manifest["claim_id"],
        "status": status,
        "pass_checks": pass_checks,
        "event_count": len(events),
        "unique_finality_times": unique_finality_times,
        "direction_counts": direction_counts,
        "token_counts": token_counts,
        "large_event_counts": large_counts,
        "gross_amount_usd": gross,
        "net_amount_usd": net,
        "canonical_event_hash": manifest["canonical_event_hash"],
        "independent_verification": verification,
        "conditional_economic_screen_authorized": status == "PASS",
        "market_outcome_opened": False,
        "model_fit": False,
        "trade_or_pnl_opened": False,
        "official_2024_2026_opened": False,
        "credentials_used": False,
        "orders_submitted": False,
    }
    (output / "SOURCE_GATE_RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> None:
    assert normalize_address(address_topic(BYBIT_ADDRESSES[0])) == BYBIT_ADDRESSES[0]
    external = "0x" + "11" * 20
    bybit = BYBIT_ADDRESSES[0]
    base = {
        "address": TOKENS["USDT"]["address"],
        "topics": [TRANSFER_TOPIC, address_topic(external), address_topic(bybit)],
        "data": hex(2_500_000 * 10**6),
        "blockNumber": hex(100),
        "transactionHash": "0x" + "aa" * 32,
        "logIndex": hex(3),
    }
    inflow = decode_transfer("USDT", base)
    assert inflow and inflow["direction"] == "INFLOW" and inflow["amount_usd"] == 2_500_000
    out_log = dict(base)
    out_log["topics"] = [TRANSFER_TOPIC, address_topic(bybit), address_topic(external)]
    out_log["transactionHash"] = "0x" + "bb" * 32
    outflow = decode_transfer("USDT", out_log)
    assert outflow and outflow["direction"] == "OUTFLOW"
    internal = dict(base)
    internal["topics"] = [TRANSFER_TOPIC, address_topic(BYBIT_ADDRESSES[0]), address_topic(BYBIT_ADDRESSES[1])]
    assert decode_transfer("USDT", internal) is None
    rows = [inflow, outflow]
    assert canonical_rows_hash(rows) == canonical_rows_hash(list(reversed(rows)))
    start, end = choose_verification_range(rows, 1, 10_000)
    assert start <= 100 <= end
    print("bybit reserve netflow source self-test passed")


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
    try:
        result = source_gate(args.output)
    except Exception as exc:
        result = {
            "schema_version": 1,
            "claim_id": "CLM-20260726-1710-BYBIT-RESERVE-NETFLOW-001",
            "status": "SOURCE_UNAVAILABLE",
            "error": f"{type(exc).__name__}: {exc}",
            "conditional_economic_screen_authorized": False,
            "market_outcome_opened": False,
            "model_fit": False,
            "trade_or_pnl_opened": False,
            "official_2024_2026_opened": False,
            "credentials_used": False,
            "orders_submitted": False,
        }
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "SOURCE_GATE_RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
