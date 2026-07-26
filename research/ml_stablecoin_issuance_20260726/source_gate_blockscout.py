from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import source_gate_authoritative as auth

API_BASE = "https://eth.blockscout.com/api"
REST_BASE = "https://eth.blockscout.com/api/v2"
MAX_LOGS = 1_000
MIN_REQUEST_INTERVAL_SECONDS = 0.24


def parse_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(text)


def parse_iso_timestamp(value: str) -> int:
    text = value.strip().replace("Z", "+00:00")
    return int(datetime.fromisoformat(text).timestamp())


class BlockscoutError(RuntimeError):
    pass


class BlockscoutClient:
    def __init__(self, timeout: int = 60) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SMC_ICT_2_LIVE-stablecoin-blockscout/1.0"
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
                    raise BlockscoutError(f"HTTP {response.status_code}: {response.text[:300]}")
                return response.json()
            except Exception as exc:
                last = exc
                self.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                time.sleep(min(2**attempt, 8))
        raise BlockscoutError(f"request failed after {retries} attempts: {last}")

    def block_by_time(self, timestamp: int, closest: str) -> int:
        if timestamp > auth.base.MAX_ALLOWED_TIMESTAMP:
            raise ValueError("timestamp after 2024 boundary prohibited")
        body = self.get_json(
            API_BASE,
            {
                "module": "block",
                "action": "getblocknobytime",
                "timestamp": timestamp,
                "closest": closest,
            },
        )
        if str(body.get("status")) != "1":
            raise BlockscoutError(f"getblocknobytime failed: {body}")
        result = body.get("result")
        if isinstance(result, dict):
            result = result.get("blockNumber")
        return parse_int(result)

    def address_info(self, address: str) -> dict[str, Any]:
        body = self.get_json(f"{REST_BASE}/addresses/{address}")
        observed = str(body.get("hash") or body.get("address") or address).lower()
        if observed != address.lower():
            raise BlockscoutError(f"address identity mismatch: {observed} != {address.lower()}")
        return {
            "address": address,
            "observed_address": observed,
            "is_contract": bool(body.get("is_contract", False)),
            "is_verified": bool(body.get("is_verified", False)),
            "name": body.get("name"),
        }

    def block_timestamp(self, block_number: int) -> int:
        if block_number not in self.block_timestamp_cache:
            body = self.get_json(f"{REST_BASE}/blocks/{block_number}")
            observed = int(body.get("height"))
            if observed != block_number:
                raise BlockscoutError(f"block height mismatch: {observed} != {block_number}")
            timestamp = parse_iso_timestamp(str(body["timestamp"]))
            self.block_timestamp_cache[block_number] = timestamp
        return self.block_timestamp_cache[block_number]

    def _log_params(
        self,
        address: str,
        direction: str,
        start_block: int,
        end_block: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "module": "logs",
            "action": "getLogs",
            "fromBlock": start_block,
            "toBlock": end_block,
            "address": address,
            "topic0": auth.TRANSFER_TOPIC,
        }
        if direction == "MINT":
            params.update(topic1=auth.ZERO_TOPIC, topic0_1_opr="and")
        elif direction == "BURN":
            params.update(topic2=auth.ZERO_TOPIC, topic0_2_opr="and")
        else:
            raise ValueError(direction)
        return params

    def logs(
        self,
        address: str,
        direction: str,
        start_block: int,
        end_block: int,
        diagnostics: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        body = self.get_json(
            API_BASE,
            self._log_params(address, direction, start_block, end_block),
        )
        status = str(body.get("status"))
        result = body.get("result")
        if status == "0":
            message = str(body.get("message", ""))
            if result in ([], None, "") or "no" in message.lower():
                diagnostics.append({
                    "from_block": start_block,
                    "to_block": end_block,
                    "status": "PASS_EMPTY",
                    "log_count": 0,
                })
                return []
            raise BlockscoutError(f"getLogs failed: {body}")
        if status != "1" or not isinstance(result, list):
            raise BlockscoutError(f"unexpected getLogs response: {body}")

        diagnostics.append({
            "from_block": start_block,
            "to_block": end_block,
            "status": "PASS",
            "log_count": len(result),
        })
        if len(result) < MAX_LOGS:
            return result
        if start_block >= end_block:
            raise BlockscoutError("single block reached the 1000-log truncation ceiling")
        mid = (start_block + end_block) // 2
        diagnostics[-1]["status"] = "SPLIT_AT_LIMIT"
        return self.logs(address, direction, start_block, mid, diagnostics) + self.logs(
            address, direction, mid + 1, end_block, diagnostics
        )


def log_timestamp(log: dict[str, Any]) -> int:
    if "timeStamp" not in log:
        raise ValueError("Blockscout log lacks timeStamp")
    return parse_int(log["timeStamp"])


def source_gate(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    client = BlockscoutClient()

    contracts = {
        token: client.address_info(spec["address"])
        for token, spec in auth.CONTRACTS.items()
    }
    if not all(item["is_contract"] for item in contracts.values()):
        raise BlockscoutError(f"contract identity failed: {contracts}")

    month_ranges: list[dict[str, Any]] = []
    for month in auth.FIXED_MONTHS:
        start_ts, end_ts = auth.month_bounds(month)
        start_block = client.block_by_time(start_ts, "after")
        end_exclusive = client.block_by_time(end_ts, "after")
        end_block = end_exclusive - 1
        if end_block < start_block:
            raise BlockscoutError(f"invalid range for {month}")
        start_observed = client.block_timestamp(start_block)
        end_observed = client.block_timestamp(end_block)
        if start_observed < start_ts or end_observed >= end_ts:
            raise BlockscoutError(
                f"month boundary mismatch {month}: {start_observed}, {end_observed}"
            )
        month_ranges.append({
            "month": month,
            "start_timestamp": start_ts,
            "end_timestamp_exclusive": end_ts,
            "start_block": start_block,
            "end_block": end_block,
            "start_block_timestamp": start_observed,
            "end_block_timestamp": end_observed,
        })

    decoded: list[dict[str, Any]] = []
    query_diagnostics: list[dict[str, Any]] = []
    for period in month_ranges:
        for token, spec in auth.CONTRACTS.items():
            for direction in ("MINT", "BURN"):
                chunks: list[dict[str, Any]] = []
                logs = client.logs(
                    spec["address"],
                    direction,
                    period["start_block"],
                    period["end_block"],
                    chunks,
                )
                query_diagnostics.append({
                    "month": period["month"],
                    "token": token,
                    "direction": direction,
                    "chunks": chunks,
                    "log_count": len(logs),
                })
                for log in logs:
                    row = auth.decode_log(token, direction, log)
                    timestamp = log_timestamp(log)
                    if not (
                        period["start_timestamp"]
                        <= timestamp
                        < period["end_timestamp_exclusive"]
                    ):
                        raise BlockscoutError(
                            f"log timestamp outside month {period['month']}: {timestamp}"
                        )
                    row["block_timestamp"] = timestamp
                    row["month"] = period["month"]
                    decoded.append(row)

    unique: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in decoded:
        key = (row["contract"], row["tx_hash"], int(row["log_index"]))
        prior = unique.get(key)
        if prior is not None and prior != row:
            raise BlockscoutError(f"conflicting duplicate {key}")
        unique[key] = row

    events: list[auth.Event] = []
    for row in sorted(unique.values(), key=lambda x: (x["block_number"], x["log_index"])):
        block_number = int(row["block_number"])
        timestamp = int(row["block_timestamp"])
        if timestamp >= auth.base.MAX_ALLOWED_TIMESTAMP:
            raise BlockscoutError("2024+ event leaked into source gate")
        block12 = block_number + 12
        block64 = block_number + 64
        events.append(auth.Event(
            token=row["token"],
            direction=row["direction"],
            contract=row["contract"],
            block_number=block_number,
            tx_hash=row["tx_hash"],
            log_index=int(row["log_index"]),
            amount_raw=int(row["amount_raw"]),
            amount_usd=float(row["amount_usd"]),
            from_address=row["from_address"],
            to_address=row["to_address"],
            block_timestamp=timestamp,
            available_block_12=block12,
            available_timestamp_12=client.block_timestamp(block12),
            available_block_64=block64,
            available_timestamp_64=client.block_timestamp(block64),
        ))

    months_with_events = sorted({
        datetime.fromtimestamp(e.block_timestamp, tz=timezone.utc).strftime("%Y-%m")
        for e in events
    })
    distinct_tokens = sorted({e.token for e in events})
    pass_checks = {
        "both_contracts_identified": all(item["is_contract"] for item in contracts.values()),
        "all_fixed_months_resolved": len(month_ranges) == len(auth.FIXED_MONTHS),
        "all_events_pre_2024": all(
            event.block_timestamp < auth.base.MAX_ALLOWED_TIMESTAMP for event in events
        ),
        "minimum_unique_events": len(events) >= 120,
        "minimum_months_with_events": len(months_with_events) >= 24,
        "minimum_distinct_tokens": len(distinct_tokens) >= 2,
    }
    status = "PASS" if all(pass_checks.values()) else "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE"

    event_path = output / "EVENTS.jsonl"
    event_path.write_text(
        "".join(json.dumps(auth.event_to_dict(e), sort_keys=True) + "\n" for e in events),
        encoding="utf-8",
    )
    events_sha = hashlib.sha256(event_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001",
        "transport_id": "TRANSPORT-20260726-ML-STABLECOIN-BLOCKSCOUT-003",
        "phase": "OUTCOME_SEALED_SOURCE_GATE",
        "provider": "Blockscout Ethereum per-instance API",
        "contracts": contracts,
        "fixed_months": list(auth.FIXED_MONTHS),
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
            for token in auth.CONTRACTS
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
        "transport_id": manifest["transport_id"],
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
    assert parse_int("0x10") == 16
    assert parse_int("16") == 16
    assert parse_iso_timestamp("2023-07-03T20:09:59.000000Z") == 1_688_411_399
    assert len(auth.FIXED_MONTHS) == 36
    fake = {
        "address": auth.CONTRACTS["USDT"]["address"],
        "topics": [
            auth.TRANSFER_TOPIC,
            auth.ZERO_TOPIC,
            "0x" + "0" * 24 + "12" * 20,
        ],
        "data": hex(1_000_000 * 10**6),
        "blockNumber": "0x10",
        "transactionHash": "0x" + "ab" * 32,
        "logIndex": "0x2",
        "timeStamp": "0x63b0cd00",
    }
    row = auth.decode_log("USDT", "MINT", fake)
    assert row["amount_usd"] == 1_000_000
    assert log_timestamp(fake) == int("63b0cd00", 16)
    print("Blockscout source self-test passed")


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
