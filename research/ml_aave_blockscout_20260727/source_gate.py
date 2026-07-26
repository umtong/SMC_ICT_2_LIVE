from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as day_time, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from eth_abi import decode

CLAIM_ID = "CLM-20260727-0010-ML-AAVE-BLOCKSCOUT-001"
BLOCKSCOUT_API = "https://eth.blockscout.com/api"
BLOCKSCOUT_REST = "https://eth.blockscout.com/api/v2"
EVENT_SIGNATURE = "LiquidationCall(address,address,address,uint256,uint256,address,bool)"
EVENT_TOPIC = "0xe413a321e8681d831f4dbccbca790d2952b56f977908e45be37335533e005286"
POOLS = {
    "v2": "0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9",
    "v3": "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2",
}
PROBE_DATES = (
    "2021-05-19",
    "2021-12-04",
    "2022-05-12",
    "2022-06-13",
    "2022-11-09",
    "2023-03-11",
    "2023-08-17",
)
MAX_LOGS = 1_000
MIN_REQUEST_INTERVAL_SECONDS = 0.22


class SourceError(RuntimeError):
    pass


class ExplicitRangeLimit(SourceError):
    pass


@dataclass(frozen=True)
class Event:
    version: str
    pool: str
    collateral_asset: str
    debt_asset: str
    user: str
    debt_to_cover_raw: str
    liquidated_collateral_raw: str
    liquidator: str
    receive_atoken: bool
    block_number: int
    block_hash: str
    block_timestamp: int
    available_timestamp: int
    transaction_hash: str
    transaction_index: int
    log_index: int
    probe_date: str

    @property
    def event_id(self) -> str:
        raw = f"{self.block_hash}|{self.transaction_hash}|{self.log_index}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]


def parse_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(text)


def normalize_address(value: str) -> str:
    text = str(value).lower().removeprefix("0x")
    if len(text) == 64:
        text = text[-40:]
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"invalid address {value!r}")
    return "0x" + text


def address_from_abi(value: Any) -> str:
    if isinstance(value, bytes):
        return normalize_address(value.hex())
    return normalize_address(str(value))


def parse_iso_timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp())


def utc_bounds(token: str) -> tuple[int, int]:
    start_date = date.fromisoformat(token)
    start = datetime.combine(start_date, day_time(), tzinfo=timezone.utc)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_status_zero(body: dict[str, Any]) -> str:
    message = str(body.get("message", "")).strip().lower()
    result = body.get("result")
    result_text = str(result).strip().lower()
    combined = f"{message} {result_text}"
    explicit_empty = (
        "no records found" in combined
        or "no logs found" in combined
        or "no transactions found" in combined
    )
    if explicit_empty:
        return "EMPTY"
    explicit_range = any(
        phrase in combined
        for phrase in (
            "query returned more than",
            "result window is too large",
            "too many results",
            "response size exceeded",
            "please narrow down",
            "block range is too wide",
        )
    )
    if explicit_range:
        return "RANGE_LIMIT"
    return "FAIL_CLOSED"


class BlockscoutClient:
    def __init__(self, timeout: int = 60) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SMC_ICT_2_LIVE-aave-blockscout/1.0"
        self.last_request_at = 0.0
        self.request_count = 0
        self.errors: list[str] = []
        self.block_timestamp_cache: dict[int, int] = {}

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)

    def get_json(self, url: str, params: dict[str, Any] | None = None, attempts: int = 5) -> Any:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                self._throttle()
                response = self.session.get(url, params=params, timeout=self.timeout)
                self.last_request_at = time.monotonic()
                self.request_count += 1
                if response.status_code != 200:
                    raise SourceError(f"HTTP {response.status_code}: {response.text[:300]}")
                body = response.json()
                return body
            except Exception as exc:
                last = exc
                self.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                if attempt + 1 < attempts:
                    time.sleep(min(8, 2**attempt))
        raise SourceError(f"request failed after {attempts} attempts: {last}")

    def address_info(self, address: str) -> dict[str, Any]:
        body = self.get_json(f"{BLOCKSCOUT_REST}/addresses/{address}")
        observed = normalize_address(str(body.get("hash") or body.get("address") or address))
        expected = normalize_address(address)
        if observed != expected:
            raise SourceError(f"address identity mismatch {observed} != {expected}")
        return {
            "address": expected,
            "is_contract": bool(body.get("is_contract", False)),
            "is_verified": bool(body.get("is_verified", False)),
            "name": body.get("name"),
        }

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
            observed = parse_int(body.get("height"))
            if observed != block_number:
                raise SourceError(f"block identity mismatch {observed} != {block_number}")
            self.block_timestamp_cache[block_number] = parse_iso_timestamp(str(body["timestamp"]))
        return self.block_timestamp_cache[block_number]

    def _logs_once(self, pool: str, start_block: int, end_block: int) -> list[dict[str, Any]]:
        body = self.get_json(
            BLOCKSCOUT_API,
            {
                "module": "logs",
                "action": "getLogs",
                "fromBlock": start_block,
                "toBlock": end_block,
                "address": normalize_address(pool),
                "topic0": EVENT_TOPIC,
            },
        )
        status = str(body.get("status"))
        result = body.get("result")
        if status == "0":
            classification = classify_status_zero(body)
            if classification == "EMPTY":
                return []
            if classification == "RANGE_LIMIT":
                raise ExplicitRangeLimit(json.dumps(body, sort_keys=True))
            raise SourceError(f"unrecognized status=0 response: {body}")
        if status != "1" or not isinstance(result, list):
            raise SourceError(f"unexpected getLogs response: {body}")
        if len(result) >= MAX_LOGS:
            raise ExplicitRangeLimit(f"result length {len(result)} reached limit")
        return result

    def logs(
        self,
        pool: str,
        start_block: int,
        end_block: int,
        diagnostics: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        try:
            rows = self._logs_once(pool, start_block, end_block)
            diagnostics.append(
                {
                    "from_block": start_block,
                    "to_block": end_block,
                    "status": "PASS" if rows else "PASS_EMPTY",
                    "log_count": len(rows),
                }
            )
            return rows
        except ExplicitRangeLimit as exc:
            if start_block >= end_block:
                raise SourceError(f"single-block range limit: {exc}") from exc
            midpoint = (start_block + end_block) // 2
            diagnostics.append(
                {
                    "from_block": start_block,
                    "to_block": end_block,
                    "status": "SPLIT_EXPLICIT_LIMIT",
                    "error": str(exc),
                }
            )
            return self.logs(pool, start_block, midpoint, diagnostics) + self.logs(
                pool, midpoint + 1, end_block, diagnostics
            )


def decode_log(
    log: dict[str, Any],
    *,
    version: str,
    pool: str,
    probe_date: str,
    block_timestamp: int,
) -> Event:
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) != 4:
        raise ValueError(f"unexpected topics {topics!r}")
    if str(topics[0]).lower() != EVENT_TOPIC:
        raise ValueError("event topic mismatch")
    expected_pool = normalize_address(pool)
    if normalize_address(str(log.get("address"))) != expected_pool:
        raise ValueError("pool address mismatch")
    data_hex = str(log.get("data", ""))
    raw = bytes.fromhex(data_hex.removeprefix("0x"))
    debt_to_cover, collateral_amount, liquidator, receive_atoken = decode(
        ["uint256", "uint256", "address", "bool"], raw
    )
    block_hash = str(log.get("blockHash", "")).lower()
    transaction_hash = str(log.get("transactionHash", "")).lower()
    if not block_hash.startswith("0x") or len(block_hash) != 66:
        raise ValueError("missing block hash")
    if not transaction_hash.startswith("0x") or len(transaction_hash) != 66:
        raise ValueError("missing transaction hash")
    return Event(
        version=version,
        pool=expected_pool,
        collateral_asset=normalize_address(str(topics[1])),
        debt_asset=normalize_address(str(topics[2])),
        user=normalize_address(str(topics[3])),
        debt_to_cover_raw=str(int(debt_to_cover)),
        liquidated_collateral_raw=str(int(collateral_amount)),
        liquidator=address_from_abi(liquidator),
        receive_atoken=bool(receive_atoken),
        block_number=parse_int(log["blockNumber"]),
        block_hash=block_hash,
        block_timestamp=block_timestamp,
        available_timestamp=block_timestamp + 120,
        transaction_hash=transaction_hash,
        transaction_index=parse_int(log.get("transactionIndex", 0)),
        log_index=parse_int(log["logIndex"]),
        probe_date=probe_date,
    )


def summarize(events: list[Event]) -> dict[str, Any]:
    versions = collections.Counter(event.version for event in events)
    collateral = collections.Counter(event.collateral_asset for event in events)
    debt = collections.Counter(event.debt_asset for event in events)
    return {
        "events": len(events),
        "versions": dict(sorted(versions.items())),
        "unique_transactions": len({event.transaction_hash for event in events}),
        "unique_blocks": len({event.block_number for event in events}),
        "unique_users": len({event.user for event in events}),
        "unique_liquidators": len({event.liquidator for event in events}),
        "top_collateral_assets": collateral.most_common(10),
        "top_debt_assets": debt.most_common(10),
        "receive_atoken_true": sum(event.receive_atoken for event in events),
    }


def source_gate(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    client = BlockscoutClient()
    pool_identity = {version: client.address_info(pool) for version, pool in POOLS.items()}
    if not all(item["is_contract"] for item in pool_identity.values()):
        raise SourceError(f"pool identity failed: {pool_identity}")

    events: list[Event] = []
    decode_errors: list[dict[str, Any]] = []
    query_diagnostics: list[dict[str, Any]] = []
    date_ranges: dict[str, Any] = {}
    date_summaries: dict[str, Any] = {}
    for token in PROBE_DATES:
        start_ts, end_ts = utc_bounds(token)
        start_block = client.block_by_time(start_ts, "after")
        end_exclusive = client.block_by_time(end_ts, "after")
        end_block = end_exclusive - 1
        start_observed = client.block_timestamp(start_block)
        end_observed = client.block_timestamp(end_block)
        if start_observed < start_ts or end_observed >= end_ts:
            raise SourceError(f"date boundary mismatch {token}: {start_observed}, {end_observed}")
        date_ranges[token] = {
            "from_block": start_block,
            "to_block": end_block,
            "from_block_timestamp": start_observed,
            "to_block_timestamp": end_observed,
        }
        date_events: list[Event] = []
        for version, pool in POOLS.items():
            chunks: list[dict[str, Any]] = []
            raw_logs = client.logs(pool, start_block, end_block, chunks)
            query_diagnostics.append(
                {
                    "probe_date": token,
                    "version": version,
                    "pool": pool,
                    "raw_log_count": len(raw_logs),
                    "chunks": chunks,
                }
            )
            for raw in raw_logs:
                try:
                    block_number = parse_int(raw["blockNumber"])
                    timestamp = client.block_timestamp(block_number)
                    if not (start_ts <= timestamp < end_ts):
                        raise ValueError(f"event timestamp outside probe date: {timestamp}")
                    event = decode_log(
                        raw,
                        version=version,
                        pool=pool,
                        probe_date=token,
                        block_timestamp=timestamp,
                    )
                    date_events.append(event)
                    events.append(event)
                except Exception as exc:
                    decode_errors.append(
                        {
                            "probe_date": token,
                            "version": version,
                            "error": f"{type(exc).__name__}: {exc}",
                            "raw_log": raw,
                        }
                    )
        date_events.sort(key=lambda event: (event.block_number, event.transaction_index, event.log_index))
        date_summaries[token] = summarize(date_events)

    events.sort(key=lambda event: (event.block_number, event.transaction_index, event.log_index))
    identities = [(event.block_hash, event.transaction_hash, event.log_index) for event in events]
    duplicate_identity_count = len(identities) - len(set(identities))
    versions = collections.Counter(event.version for event in events)
    nonzero_dates = sum(summary["events"] > 0 for summary in date_summaries.values())
    pass_checks = {
        "all_pool_identities_match": all(item["is_contract"] for item in pool_identity.values()),
        "decode_errors_zero": len(decode_errors) == 0,
        "duplicate_identity_count_zero": duplicate_identity_count == 0,
        "minimum_event_dates": nonzero_dates >= 4,
        "minimum_decoded_events": len(events) >= 25,
        "both_versions_present": all(versions.get(version, 0) > 0 for version in POOLS),
        "all_block_timestamps_complete": all(event.block_timestamp > 0 for event in events),
        "all_availability_times_complete": all(event.available_timestamp == event.block_timestamp + 120 for event in events),
    }
    status = "PASS" if all(pass_checks.values()) else "FAIL_BELOW_SOURCE_GATE"

    raw_path = output / "RAW_LOGS.jsonl.gz"
    with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
        for event in events:
            row = asdict(event)
            row["event_id"] = event.event_id
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "status": status,
        "source_gate_pass": status == "PASS",
        "scientific_decision": "OPEN_FULL_2021_2023_HISTORY_AND_FROZEN_MODEL" if status == "PASS" else "CLOSE_BLOCKSCOUT_SOURCE_BEFORE_OUTCOMES",
        "authority": {
            "address_book_package": "@aave-dao/aave-address-book@4.61.0",
            "address_book_commit": "67c777be17e782c2f961a44e085ec55b39e63639",
            "event_signature": EVENT_SIGNATURE,
            "event_topic": EVENT_TOPIC,
            "pools": POOLS,
        },
        "transport": {
            "provider": "Blockscout Ethereum API",
            "request_count": client.request_count,
            "errors": client.errors[-20:],
            "status_zero_empty_policy": "EXPLICIT_NO_RECORDS_ONLY",
            "status_zero_range_policy": "EXPLICIT_RANGE_LIMIT_ONLY",
            "unrecognized_status_zero_policy": "FAIL_CLOSED",
        },
        "probe_dates": list(PROBE_DATES),
        "pool_identity": pool_identity,
        "date_ranges": date_ranges,
        "date_summaries": date_summaries,
        "query_diagnostics": query_diagnostics,
        "event_count": len(events),
        "nonzero_date_count": nonzero_dates,
        "version_counts": dict(sorted(versions.items())),
        "duplicate_identity_count": duplicate_identity_count,
        "decode_errors": decode_errors,
        "pass_checks": pass_checks,
        "raw_logs_file": raw_path.name,
        "raw_logs_sha256": sha256_file(raw_path),
        "market_outcome_opened": False,
        "model_fit": False,
        "trade_or_pnl_opened": False,
        "official_2024_2026_opened": False,
        "credentials_used": False,
        "orders_submitted": False,
    }
    result_path = output / "SOURCE_GATE_RESULT.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "provider": "Blockscout Ethereum API",
        "source_gate_result_sha256": sha256_file(result_path),
        "raw_logs_sha256": sha256_file(raw_path),
        "event_count": len(events),
        "orders_submitted": False,
    }
    (output / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def synthetic_log() -> dict[str, Any]:
    def topic(address: str) -> str:
        return "0x" + "0" * 24 + normalize_address(address)[2:]

    debt_to_cover = (1_000_000).to_bytes(32, "big")
    collateral_amount = (2_000_000).to_bytes(32, "big")
    liquidator = bytes.fromhex("00" * 12 + "44" * 20)
    receive_atoken = (1).to_bytes(32, "big")
    return {
        "address": POOLS["v2"],
        "topics": [
            EVENT_TOPIC,
            topic("0x" + "11" * 20),
            topic("0x" + "22" * 20),
            topic("0x" + "33" * 20),
        ],
        "data": "0x" + (debt_to_cover + collateral_amount + liquidator + receive_atoken).hex(),
        "blockNumber": hex(12_345_678),
        "blockHash": "0x" + "aa" * 32,
        "transactionHash": "0x" + "bb" * 32,
        "transactionIndex": hex(3),
        "logIndex": hex(7),
    }


def self_test() -> None:
    assert classify_status_zero({"status": "0", "message": "No records found", "result": []}) == "EMPTY"
    assert classify_status_zero({"status": "0", "message": "NOTOK", "result": "rate limit"}) == "FAIL_CLOSED"
    assert classify_status_zero({"status": "0", "message": "NOTOK", "result": "Query returned more than 1000 results"}) == "RANGE_LIMIT"
    event = decode_log(
        synthetic_log(),
        version="v2",
        pool=POOLS["v2"],
        probe_date="2021-05-19",
        block_timestamp=1_621_382_400,
    )
    assert event.collateral_asset == "0x" + "11" * 20
    assert event.debt_asset == "0x" + "22" * 20
    assert event.user == "0x" + "33" * 20
    assert event.liquidator == "0x" + "44" * 20
    assert event.debt_to_cover_raw == "1000000"
    assert event.liquidated_collateral_raw == "2000000"
    assert event.receive_atoken is True
    assert event.available_timestamp == event.block_timestamp + 120
    print("aave Blockscout source self-test passed")


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
        args.output.mkdir(parents=True, exist_ok=True)
        result = {
            "schema_version": 1,
            "claim_id": CLAIM_ID,
            "status": "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE",
            "source_gate_pass": False,
            "scientific_decision": "CLOSE_BLOCKSCOUT_SOURCE_BEFORE_OUTCOMES",
            "fatal_error": f"{type(exc).__name__}: {exc}",
            "market_outcome_opened": False,
            "model_fit": False,
            "trade_or_pnl_opened": False,
            "official_2024_2026_opened": False,
            "credentials_used": False,
            "orders_submitted": False,
        }
        (args.output / "SOURCE_GATE_RESULT.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
