from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import requests

import source_gate_sqd as gate

CLAIM_ID = gate.CLAIM_ID
PORTAL_MAX_BLOCK_SPAN = 100_000


class FullHistoryError(RuntimeError):
    pass


@dataclass
class FilteredPortalStats:
    timestamp_calls: int = 0
    stream_calls: int = 0
    retries: int = 0
    errors: int = 0
    no_content_chunks: int = 0
    response_headers: list[dict[str, str]] = field(default_factory=list)


class FilteredPortalClient:
    """SQD finalized transport that emits only blocks containing matching logs."""

    def __init__(self, root: str = gate.PORTAL_ROOT) -> None:
        self.root = root.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/x-ndjson, application/json",
                "Accept-Encoding": "gzip",
                "User-Agent": "SMC-ICT-2-Uniswap-SQD-full-history/1.0",
            }
        )
        self.stats = FilteredPortalStats()
        self._last_request = 0.0

    def _pace(self) -> None:
        delay = 0.55 - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)

    def _request(
        self, method: str, url: str, *, attempts: int = 6, **kwargs: Any
    ) -> requests.Response:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                self._pace()
                response = self.session.request(
                    method, url, timeout=(15, 180), **kwargs
                )
                self._last_request = time.monotonic()
                if response.status_code in {408, 425, 429} or response.status_code >= 500:
                    raise FullHistoryError(
                        f"retryable Portal HTTP {response.status_code}: "
                        f"{response.text[:200]}"
                    )
                return response
            except Exception as exc:
                last = exc
                self.stats.errors += 1
                if attempt + 1 >= attempts:
                    break
                self.stats.retries += 1
                time.sleep(min(30.0, 1.5 * (2**attempt)))
        raise FullHistoryError(
            f"Portal request failed: {method} {url}: {last!r}"
        )

    def resolve_timestamp(self, unix_seconds: int) -> int:
        self.stats.timestamp_calls += 1
        response = self._request(
            "GET", f"{self.root}/timestamps/{int(unix_seconds)}/block"
        )
        response.raise_for_status()
        try:
            body: Any = response.json()
        except Exception:
            body = response.text.strip()
        block = gate._recursive_find_block(body)
        if block is None:
            raise FullHistoryError(
                f"timestamp endpoint returned no block: {body!r}"
            )
        return int(block)

    def stream_filtered(
        self,
        *,
        from_block: int,
        to_block: int,
        addresses: Sequence[str],
        topic0: str,
        max_block_span: int = PORTAL_MAX_BLOCK_SPAN,
    ) -> Iterator[dict[str, Any]]:
        if from_block > to_block:
            return
        fields = {
            "block": {"number": True, "hash": True, "timestamp": True},
            "log": {
                "address": True,
                "topics": True,
                "data": True,
                "transactionHash": True,
                "logIndex": True,
            },
        }
        cursor = int(from_block)
        global_last_block = cursor - 1
        while cursor <= int(to_block):
            chunk_end = min(
                int(to_block), cursor + int(max_block_span) - 1
            )
            payload = {
                "type": "evm",
                "fromBlock": cursor,
                "toBlock": chunk_end,
                "includeAllBlocks": False,
                "fields": fields,
                "logs": [
                    {
                        "address": [
                            gate.normalize_address(x) for x in addresses
                        ],
                        "topic0": [topic0.lower()],
                    }
                ],
            }
            self.stats.stream_calls += 1
            response = self._request(
                "POST",
                f"{self.root}/finalized-stream",
                json=payload,
                stream=True,
            )
            if response.status_code == 204:
                self.stats.no_content_chunks += 1
                cursor = chunk_end + 1
                continue
            response.raise_for_status()
            self.stats.response_headers.append(
                {
                    key.lower(): value
                    for key, value in response.headers.items()
                    if key.lower()
                    in {
                        "content-type",
                        "content-encoding",
                        "x-request-id",
                        "x-sqd-request-id",
                    }
                }
            )
            last_block: int | None = None
            for raw in response.iter_lines(decode_unicode=True):
                if not raw or not raw.strip():
                    continue
                parsed = json.loads(raw)
                rows = parsed if isinstance(parsed, list) else [parsed]
                for row in rows:
                    if not isinstance(row, Mapping):
                        raise FullHistoryError(
                            f"Portal row is not an object: {row!r}"
                        )
                    header = row.get("header")
                    if not isinstance(header, Mapping):
                        raise FullHistoryError(
                            f"Portal row omitted header: {row!r}"
                        )
                    number = gate.parse_int(header.get("number"))
                    if number < cursor or number > chunk_end:
                        raise FullHistoryError(
                            f"Portal returned block {number} outside "
                            f"{cursor}:{chunk_end}"
                        )
                    if number <= global_last_block:
                        raise FullHistoryError(
                            "Portal block order repeated/regressed: "
                            f"{global_last_block}, {number}"
                        )
                    global_last_block = number
                    last_block = number
                    yield dict(row)
            if last_block is None:
                self.stats.no_content_chunks += 1
                cursor = chunk_end + 1
            elif last_block < chunk_end:
                cursor = last_block + 1
            else:
                cursor = chunk_end + 1


@dataclass
class PoolBucket:
    net: float = 0.0
    gross: float = 0.0
    first_tick: int | None = None
    last_tick: int | None = None


@dataclass
class BucketAccumulator:
    bucket_start_s: int
    gross_stable: float = 0.0
    net_stable: float = 0.0
    positive_gross: float = 0.0
    negative_gross: float = 0.0
    sum_abs_square: float = 0.0
    fee500_gross: float = 0.0
    swaps: int = 0
    transactions: set[str] = field(default_factory=set)
    pools: dict[str, PoolBucket] = field(default_factory=dict)
    first_block: int | None = None
    last_block: int | None = None

    def add(
        self,
        *,
        pool_name: str,
        fee: int,
        signed_stable: float,
        normalized_weth_tick: int,
        transaction_hash: str,
        block_number: int,
    ) -> None:
        gross = abs(float(signed_stable))
        if not math.isfinite(gross) or gross <= 0:
            return
        self.gross_stable += gross
        self.net_stable += float(signed_stable)
        if signed_stable > 0:
            self.positive_gross += gross
        else:
            self.negative_gross += gross
        self.sum_abs_square += gross * gross
        if int(fee) == 500:
            self.fee500_gross += gross
        self.swaps += 1
        self.transactions.add(str(transaction_hash).lower())
        self.first_block = (
            block_number
            if self.first_block is None
            else min(self.first_block, block_number)
        )
        self.last_block = (
            block_number
            if self.last_block is None
            else max(self.last_block, block_number)
        )
        row = self.pools.setdefault(pool_name, PoolBucket())
        row.net += float(signed_stable)
        row.gross += gross
        if row.first_tick is None:
            row.first_tick = int(normalized_weth_tick)
        row.last_tick = int(normalized_weth_tick)

    def finalize(self) -> dict[str, Any]:
        gross = self.gross_stable
        if gross <= 0:
            raise FullHistoryError("cannot finalize empty bucket")
        net_sign = (
            1
            if self.net_stable > 0
            else (-1 if self.net_stable < 0 else 0)
        )
        pool_net_abs = sum(abs(row.net) for row in self.pools.values())
        agreeing_pool_net = sum(
            abs(row.net)
            for row in self.pools.values()
            if net_sign != 0 and row.net * net_sign > 0
        )
        tick_change = 0.0
        for row in self.pools.values():
            if row.first_tick is not None and row.last_tick is not None:
                tick_change += (row.gross / gross) * (
                    row.last_tick - row.first_tick
                )
        return {
            "bucket_start_s": self.bucket_start_s,
            "bucket_end_s": self.bucket_start_s + 300,
            "bucket_start_utc": dt.datetime.fromtimestamp(
                self.bucket_start_s, tz=dt.timezone.utc
            ).isoformat(),
            "gross_stable_notional": gross,
            "net_stable_notional": self.net_stable,
            "signed_imbalance": self.net_stable / gross,
            "aligned_gross_fraction": max(
                self.positive_gross, self.negative_gross
            )
            / gross,
            "swap_count": self.swaps,
            "unique_transaction_count": len(self.transactions),
            "transaction_notional_hhi": self.sum_abs_square
            / (gross * gross),
            "fee500_gross_fraction": self.fee500_gross / gross,
            "cross_pool_direction_consensus": (
                agreeing_pool_net / pool_net_abs
                if pool_net_abs > 0
                else 0.0
            ),
            "weighted_weth_price_tick_change": tick_change,
            "active_pool_count": len(self.pools),
            "first_block": self.first_block,
            "last_block": self.last_block,
        }


def stablecoin_flow_and_tick(
    decoded: Mapping[str, Any], pool: Mapping[str, Any]
) -> tuple[float, int]:
    token0 = gate.normalize_address(str(pool["token0"]))
    token1 = gate.normalize_address(str(pool["token1"]))
    amount0 = int(str(decoded["amount0_raw"]))
    amount1 = int(str(decoded["amount1_raw"]))
    tick = int(decoded["tick"])
    weth = gate.normalize_address(gate.TOKENS["WETH"])
    stablecoins = {
        gate.normalize_address(gate.TOKENS["USDC"]),
        gate.normalize_address(gate.TOKENS["USDT"]),
    }
    if token0 in stablecoins and token1 == weth:
        stable_raw = amount0
        normalized_tick = -tick
    elif token0 == weth and token1 in stablecoins:
        stable_raw = amount1
        normalized_tick = tick
    else:
        raise FullHistoryError(
            f"unexpected pool token ordering: {token0}, {token1}"
        )
    return stable_raw / 1_000_000.0, normalized_tick


def load_source_gate(
    path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    result = json.loads(path.read_text(encoding="utf-8"))
    if (
        result.get("claim_id") != CLAIM_ID
        or result.get("source_gate_status") != "PASS"
    ):
        raise FullHistoryError(
            "full history requires the exact PASS source gate"
        )
    if (
        result.get("scientific_decision")
        != "OPEN_FROZEN_PRE2024_HISTORY_AND_MODEL_STAGE"
    ):
        raise FullHistoryError(
            "source gate did not authorize full pre-2024 history"
        )
    pools = result.get("pools")
    if (
        not isinstance(pools, dict)
        or not all(row.get("status") == "PASS" for row in pools.values())
    ):
        raise FullHistoryError(
            "not every frozen pool passed semantic verification"
        )
    return result, pools


def run_shard(
    *,
    start: str,
    end: str,
    source_gate_path: Path,
    output: Path,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    _, pools = load_source_gate(source_gate_path)
    start_s = gate.timestamp_seconds(start)
    end_s = gate.timestamp_seconds(end)
    if (
        start_s >= end_s
        or end_s
        > gate.timestamp_seconds("2024-01-01T00:00:00+00:00")
    ):
        raise FullHistoryError("invalid or post-2023 shard boundary")

    portal = FilteredPortalClient()
    start_block = portal.resolve_timestamp(start_s)
    end_block_exclusive = portal.resolve_timestamp(end_s)
    by_address = {
        gate.normalize_address(str(row["pool"])): (name, row)
        for name, row in pools.items()
    }

    output_csv = output / "FLOW_5M.csv"
    fieldnames = [
        "bucket_start_s",
        "bucket_end_s",
        "bucket_start_utc",
        "gross_stable_notional",
        "net_stable_notional",
        "signed_imbalance",
        "aligned_gross_fraction",
        "swap_count",
        "unique_transaction_count",
        "transaction_notional_hhi",
        "fee500_gross_fraction",
        "cross_pool_direction_consensus",
        "weighted_weth_price_tick_change",
        "active_pool_count",
        "first_block",
        "last_block",
    ]
    event_hash = hashlib.sha256()
    total_swaps = 0
    duplicate_count = 0
    decode_errors: list[dict[str, Any]] = []
    last_identity: tuple[str, str, int] | None = None
    current: BucketAccumulator | None = None
    bucket_count = 0
    first_event_s: int | None = None
    last_event_s: int | None = None

    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for block_row in portal.stream_filtered(
            from_block=start_block,
            to_block=end_block_exclusive - 1,
            addresses=[str(row["pool"]) for row in pools.values()],
            topic0=gate.SWAP_TOPIC,
        ):
            header = block_row["header"]
            logs = block_row.get("logs", [])
            if not isinstance(logs, list):
                raise FullHistoryError("Portal logs field is not a list")
            for log in sorted(
                logs,
                key=lambda item: gate.parse_int(item.get("logIndex")),
            ):
                try:
                    address = gate.normalize_address(
                        str(log.get("address"))
                    )
                    if address not in by_address:
                        raise FullHistoryError(
                            f"unexpected filtered pool {address}"
                        )
                    pool_name, pool = by_address[address]
                    decoded = gate.decode_swap_log(
                        log,
                        header=header,
                        pool_name=pool_name,
                        expected_pool=address,
                    )
                    timestamp = int(decoded["block_timestamp"])
                    if timestamp < start_s or timestamp >= end_s:
                        raise FullHistoryError(
                            f"decoded event timestamp {timestamp} outside "
                            f"{start_s}:{end_s}"
                        )
                    identity = (
                        str(decoded["block_hash"]),
                        str(decoded["transaction_hash"]),
                        int(decoded["log_index"]),
                    )
                    if last_identity == identity:
                        duplicate_count += 1
                        continue
                    last_identity = identity
                    signed_stable, normalized_tick = (
                        stablecoin_flow_and_tick(decoded, pool)
                    )
                    bucket_s = timestamp - (timestamp % 300)
                    if current is None:
                        current = BucketAccumulator(bucket_s)
                    elif bucket_s != current.bucket_start_s:
                        if bucket_s < current.bucket_start_s:
                            raise FullHistoryError(
                                "bucket order regressed"
                            )
                        writer.writerow(current.finalize())
                        bucket_count += 1
                        current = BucketAccumulator(bucket_s)
                    current.add(
                        pool_name=pool_name,
                        fee=int(pool["fee"]),
                        signed_stable=signed_stable,
                        normalized_weth_tick=normalized_tick,
                        transaction_hash=str(
                            decoded["transaction_hash"]
                        ),
                        block_number=int(decoded["block_number"]),
                    )
                    event_hash.update(
                        (
                            f"{identity[0]}|{identity[1]}|{identity[2]}|"
                            f"{pool_name}|{decoded['amount0_raw']}|"
                            f"{decoded['amount1_raw']}|{decoded['tick']}\n"
                        ).encode("utf-8")
                    )
                    total_swaps += 1
                    first_event_s = (
                        timestamp
                        if first_event_s is None
                        else min(first_event_s, timestamp)
                    )
                    last_event_s = (
                        timestamp
                        if last_event_s is None
                        else max(last_event_s, timestamp)
                    )
                except Exception as exc:
                    decode_errors.append(
                        {
                            "block": header.get("number"),
                            "log_index": log.get("logIndex"),
                            "error": repr(exc),
                        }
                    )
                    if len(decode_errors) >= 20:
                        raise FullHistoryError(
                            f"too many decode errors: {decode_errors}"
                        ) from exc
        if current is not None:
            writer.writerow(current.finalize())
            bucket_count += 1

    status = (
        "PASS"
        if total_swaps > 0
        and duplicate_count == 0
        and not decode_errors
        else "FAIL"
    )
    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "phase": "OUTCOME_SEALED_FULL_SOURCE_SHARD",
        "status": status,
        "start": start,
        "end": end,
        "start_block": start_block,
        "end_block_exclusive": end_block_exclusive,
        "total_decoded_swaps": total_swaps,
        "five_minute_nonzero_buckets": bucket_count,
        "duplicate_identities": duplicate_count,
        "decode_errors": decode_errors,
        "first_event_time": (
            dt.datetime.fromtimestamp(
                first_event_s, tz=dt.timezone.utc
            ).isoformat()
            if first_event_s is not None
            else None
        ),
        "last_event_time": (
            dt.datetime.fromtimestamp(
                last_event_s, tz=dt.timezone.utc
            ).isoformat()
            if last_event_s is not None
            else None
        ),
        "event_stream_sha256": event_hash.hexdigest(),
        "flow_5m_sha256": gate.sha256_file(output_csv),
        "portal_stats": vars(portal.stats),
        "source_gate_result_sha256": gate.sha256_file(
            source_gate_path
        ),
        "market_outcomes_opened": False,
        "orders_submitted": False,
    }
    result_path = output / "SOURCE_SHARD_RESULT.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "SHA256SUMS.txt").write_text(
        f"{gate.sha256_file(result_path)}  SOURCE_SHARD_RESULT.json\n"
        f"{gate.sha256_file(output_csv)}  FLOW_5M.csv\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--source-gate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_shard(
        start=args.start,
        end=args.end,
        source_gate_path=args.source_gate,
        output=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
