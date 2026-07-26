from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any, AsyncIterator

import requests
from sqd import SQD

CLAIM_ID = "CLM-20260726-2315-ML-UNISWAP-INVENTORY-001"
PORTAL_ROOT = "https://portal.sqd.dev/datasets/ethereum-mainnet"
POOL = "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"
SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
SNAPSHOT_DATASET = "arthurneuron/USDC-WETH-Uniswap-V3-2021-to-2023"
SNAPSHOT_PARQUET_API = (
    "https://datasets-server.huggingface.co/parquet?dataset=" + SNAPSHOT_DATASET
)
SNAPSHOT_ROWS_API = (
    "https://datasets-server.huggingface.co/rows?dataset="
    + SNAPSHOT_DATASET
    + "&config=default&split=train&offset={offset}&length={length}"
)
BYBIT_BASE = "https://public.bybit.com/kline_for_metatrader4"

SOURCE_START = dt.datetime(2021, 7, 1, tzinfo=dt.timezone.utc)
PRE2024_END = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
OFFICIAL_END = dt.datetime(2024, 7, 1, tzinfo=dt.timezone.utc)
PROBE_DAYS = (
    dt.datetime(2024, 1, 15, tzinfo=dt.timezone.utc),
    dt.datetime(2024, 6, 15, tzinfo=dt.timezone.utc),
)
AVAILABILITY_DELAY_SECONDS = 2 * 60 * 60
EXPECTED_PRE2024_MONTHS = tuple(
    f"{year:04d}-{month:02d}"
    for year, month in (
        (year, month)
        for year in (2021, 2022, 2023)
        for month in range(1, 13)
    )
    if (year, month) >= (2021, 7)
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def request_json(session: requests.Session, url: str) -> Any:
    last_error: Exception | None = None
    for attempt in range(7):
        try:
            response = session.get(url, timeout=(30, 180))
            if response.status_code == 429 or response.status_code >= 500:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # pragma: no cover - network path
            last_error = exc
            if attempt == 6:
                raise
            time.sleep(min(20.0, 0.75 * (2**attempt)))
    raise RuntimeError(last_error)


def timestamp_block(session: requests.Session, timestamp: int) -> int:
    payload = request_json(session, f"{PORTAL_ROOT}/timestamps/{timestamp}/block")
    number = int(payload["block_number"])
    if number <= 0:
        raise ValueError(f"invalid block for timestamp {timestamp}: {number}")
    return number


def parse_timestamp(value: Any) -> int:
    if isinstance(value, (int, float)):
        number = int(value)
        return number // 1000 if number > 10_000_000_000 else number
    text = str(value).strip()
    if text.isdigit():
        return parse_timestamp(int(text))
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.timestamp())


def parse_integer(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value)
    return int(text, 16) if text.startswith("0x") else int(text)


def signed_word(word: bytes, bits: int = 256) -> int:
    value = int.from_bytes(word, "big", signed=False)
    if bits < 256:
        value &= (1 << bits) - 1
    if value >= 1 << (bits - 1):
        value -= 1 << bits
    return value


def decode_swap(data_hex: str) -> dict[str, int | float]:
    clean = data_hex[2:] if data_hex.startswith("0x") else data_hex
    raw = bytes.fromhex(clean)
    if len(raw) != 160:
        raise ValueError(f"Uniswap V3 Swap data must contain five ABI words, got {len(raw)}")
    words = [raw[index : index + 32] for index in range(0, 160, 32)]
    amount0 = signed_word(words[0])
    amount1 = signed_word(words[1])
    sqrt_price_x96 = int.from_bytes(words[2], "big", signed=False)
    liquidity = int.from_bytes(words[3], "big", signed=False)
    tick = signed_word(words[4], 24)
    if amount0 == 0 or amount1 == 0 or (amount0 > 0) == (amount1 > 0):
        raise ValueError(f"unexpected Swap amount signs: amount0={amount0}, amount1={amount1}")
    price = 1e12 / math.pow(1.0001, tick)
    if not math.isfinite(price) or price <= 0:
        raise ValueError(f"invalid tick-derived USDC/WETH price: {price}")
    return {
        "amount0_raw": amount0,
        "amount1_raw": amount1,
        "sqrt_price_x96": sqrt_price_x96,
        "liquidity": liquidity,
        "tick": tick,
        "price_usdc_per_weth": price,
    }


def normalize_header(block: dict[str, Any]) -> tuple[int, int]:
    header = block.get("header") or {}
    if "number" not in header or "timestamp" not in header:
        raise ValueError(f"SQD block header lacks number/timestamp: {header!r}")
    return parse_integer(header["number"]), parse_timestamp(header["timestamp"])


def normalize_log(log: dict[str, Any]) -> tuple[str, int, str, list[str]]:
    address = str(log.get("address") or "").lower()
    tx_hash = str(log.get("transactionHash") or log.get("transaction_hash") or "").lower()
    index_value = log.get("logIndex", log.get("log_index"))
    data = str(log.get("data") or "")
    topics = [str(item).lower() for item in (log.get("topics") or [])]
    if address != POOL or not tx_hash.startswith("0x") or index_value is None:
        raise ValueError(f"unexpected SQD log identity: {log!r}")
    if not topics or topics[0] != SWAP_TOPIC:
        raise ValueError(f"unexpected SQD Swap topic: {topics!r}")
    return tx_hash, parse_integer(index_value), data, topics


class HourlyAccumulator:
    def __init__(self) -> None:
        self.rows: dict[int, dict[str, Any]] = {}
        self.event_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.month_counts: Counter[str] = Counter()
        self.event_digest = hashlib.sha256()
        self.first_samples: list[dict[str, Any]] = []
        self.last_samples: list[dict[str, Any]] = []
        self.last_block = -1
        self.last_log_index = -1
        self.last_identity: tuple[int, str, int] | None = None

    def add(self, *, block_number: int, timestamp: int, log: dict[str, Any]) -> None:
        if block_number < self.last_block:
            raise ValueError(f"non-monotonic SQD block order: {block_number} after {self.last_block}")
        tx_hash, log_index, data, _topics = normalize_log(log)
        identity = (block_number, tx_hash, log_index)
        if identity == self.last_identity:
            raise ValueError(f"duplicate adjacent SQD log identity: {identity}")
        if block_number == self.last_block and log_index <= self.last_log_index:
            raise ValueError(
                f"non-increasing log index in block {block_number}: {log_index} <= {self.last_log_index}"
            )
        decoded = decode_swap(data)
        amount0 = int(decoded["amount0_raw"])
        amount1 = int(decoded["amount1_raw"])
        signed_usdc = amount0 / 1e6
        signed_weth = -amount1 / 1e18
        direction = 1 if signed_usdc > 0 else -1
        price = float(decoded["price_usdc_per_weth"])
        event_hour = timestamp - timestamp % 3600
        available_hour = event_hour + AVAILABILITY_DELAY_SECONDS
        row = self.rows.setdefault(
            available_hour,
            {
                "available_time": available_hour,
                "source_event_hour": event_hour,
                "net_usdc": 0.0,
                "gross_usdc": 0.0,
                "net_weth": 0.0,
                "gross_weth": 0.0,
                "swap_count": 0,
                "buy_count": 0,
                "sell_count": 0,
                "transaction_hashes": set(),
                "price_open": price,
                "price_high": price,
                "price_low": price,
                "price_close": price,
                "first_block": block_number,
                "last_block": block_number,
            },
        )
        row["net_usdc"] += signed_usdc
        row["gross_usdc"] += abs(signed_usdc)
        row["net_weth"] += signed_weth
        row["gross_weth"] += abs(signed_weth)
        row["swap_count"] += 1
        row["buy_count"] += int(direction > 0)
        row["sell_count"] += int(direction < 0)
        row["transaction_hashes"].add(tx_hash)
        row["price_high"] = max(row["price_high"], price)
        row["price_low"] = min(row["price_low"], price)
        row["price_close"] = price
        row["last_block"] = block_number

        month = dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).strftime("%Y-%m")
        self.month_counts[month] += 1
        self.event_count += 1
        self.buy_count += int(direction > 0)
        self.sell_count += int(direction < 0)
        canonical = (
            f"{block_number}|{timestamp}|{tx_hash}|{log_index}|{amount0}|{amount1}|"
            f"{decoded['sqrt_price_x96']}|{decoded['liquidity']}|{decoded['tick']}\n"
        )
        self.event_digest.update(canonical.encode())
        sample = {
            "block_number": block_number,
            "timestamp": timestamp,
            "transaction_hash": tx_hash,
            "log_index": log_index,
            "amount0_raw": str(amount0),
            "amount1_raw": str(amount1),
            "tick": int(decoded["tick"]),
        }
        if len(self.first_samples) < 5:
            self.first_samples.append(sample)
        self.last_samples.append(sample)
        if len(self.last_samples) > 5:
            self.last_samples.pop(0)
        self.last_block = block_number
        self.last_log_index = log_index
        self.last_identity = identity

    def finalized_rows(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for key in sorted(self.rows):
            row = dict(self.rows[key])
            row["unique_transaction_count"] = len(row.pop("transaction_hashes"))
            row["buy_share"] = row["buy_count"] / row["swap_count"]
            row["signed_notional_share"] = (
                row["net_usdc"] / row["gross_usdc"] if row["gross_usdc"] else 0.0
            )
            row["price_return"] = row["price_close"] / row["price_open"] - 1.0
            output.append(row)
        return output


async def stream_logs(
    *,
    start_block: int,
    end_block: int,
    accumulator: HourlyAccumulator,
) -> None:
    if end_block < start_block:
        raise ValueError(f"invalid SQD range {start_block}..{end_block}")
    source = SQD(dataset="ethereum-mainnet", stream_type="finalized")
    query = source.get_logs(
        from_block=start_block,
        to_block=end_block,
        address=POOL,
        topic0=SWAP_TOPIC,
    )
    async for block in query:
        block_number, timestamp = normalize_header(block)
        if block_number < start_block or block_number > end_block:
            raise ValueError(f"SQD returned block outside requested range: {block_number}")
        for log in block.get("logs", []):
            accumulator.add(block_number=block_number, timestamp=timestamp, log=log)


def inspect_snapshot_reference(session: requests.Session) -> dict[str, Any]:
    parquet = request_json(session, SNAPSHOT_PARQUET_API)
    files = parquet.get("parquet_files") if isinstance(parquet, dict) else None
    if not isinstance(files, list) or not files:
        raise RuntimeError("immutable snapshot parquet metadata is unavailable")
    head = request_json(session, SNAPSHOT_ROWS_API.format(offset=0, length=2))
    tail = request_json(session, SNAPSHOT_ROWS_API.format(offset=6_174_600, length=20))

    def extract_blocks(payload: Any) -> list[int]:
        rows = payload.get("rows") if isinstance(payload, dict) else None
        result: list[int] = []
        for item in rows or []:
            row = item.get("row") if isinstance(item, dict) else None
            if isinstance(row, dict) and row.get("Block") is not None:
                result.append(int(row["Block"]))
        return result

    head_blocks = extract_blocks(head)
    tail_blocks = extract_blocks(tail)
    if not head_blocks or not tail_blocks:
        raise RuntimeError("immutable snapshot row cross-check is unavailable")
    return {
        "dataset": SNAPSHOT_DATASET,
        "role": "reference_only_not_primary_signal_source",
        "file_count": len(files),
        "files": [
            {
                "filename": item.get("filename"),
                "size": item.get("size"),
                "url": item.get("url"),
            }
            for item in files
        ],
        "head_blocks": head_blocks,
        "tail_blocks": tail_blocks,
        "observed_reference_min_block": min(head_blocks),
        "observed_reference_max_block": max(tail_blocks),
        "metadata_sha256": canonical_json_sha256(parquet),
    }


def bybit_url(year: int, month: int, last_day: int) -> str:
    name = f"ETHUSDT_5_{year:04d}-{month:02d}-01_{year:04d}-{month:02d}-{last_day:02d}.csv.gz"
    return f"{BYBIT_BASE}/ETHUSDT/{year}/{name}"


def inspect_bybit_probe(session: requests.Session, url: str, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with session.get(url, stream=True, timeout=(30, 300)) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(1 << 20):
                if chunk:
                    handle.write(chunk)
    digest = sha256_file(destination)
    valid_rows = 0
    first_line = None
    last_line = None
    with gzip.open(destination, "rt", encoding="utf-8", errors="strict") as handle:
        for line in handle:
            if line.strip():
                valid_rows += 1
                first_line = first_line or line.strip()
                last_line = line.strip()
    if valid_rows < 100:
        raise ValueError(f"Bybit probe has only {valid_rows} rows: {url}")
    return {
        "url": url,
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": digest,
        "row_count": valid_rows,
        "first_line": first_line,
        "last_line": last_line,
    }


def write_hourly(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "available_time",
        "source_event_hour",
        "net_usdc",
        "gross_usdc",
        "net_weth",
        "gross_weth",
        "swap_count",
        "buy_count",
        "sell_count",
        "unique_transaction_count",
        "buy_share",
        "signed_notional_share",
        "price_open",
        "price_high",
        "price_low",
        "price_close",
        "price_return",
        "first_block",
        "last_block",
    ]
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


async def run(output: Path, cache: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-2-signed-uniswap-source/1.0"})

    metadata = request_json(session, f"{PORTAL_ROOT}/metadata")
    if metadata.get("dataset") != "ethereum-mainnet" or int(metadata.get("start_block", -1)) != 0:
        raise RuntimeError(f"unexpected SQD Ethereum metadata: {metadata!r}")

    start_block = timestamp_block(session, int(SOURCE_START.timestamp()))
    pre2024_end_block = timestamp_block(session, int(PRE2024_END.timestamp()))
    official_end_block = timestamp_block(session, int(OFFICIAL_END.timestamp()))
    if not start_block < pre2024_end_block < official_end_block:
        raise ValueError(
            f"invalid SQD timestamp mapping: {start_block}, {pre2024_end_block}, {official_end_block}"
        )

    pre2024 = HourlyAccumulator()
    await stream_logs(
        start_block=start_block,
        end_block=pre2024_end_block - 1,
        accumulator=pre2024,
    )
    hourly_rows = pre2024.finalized_rows()
    hourly_path = output / "PRE2024_SIGNED_SWAP_HOURLY.csv.gz"
    write_hourly(hourly_path, hourly_rows)

    probe_results: list[dict[str, Any]] = []
    for probe_day in PROBE_DAYS:
        probe_start = timestamp_block(session, int(probe_day.timestamp()))
        probe_end = timestamp_block(session, int((probe_day + dt.timedelta(days=1)).timestamp()))
        probe = HourlyAccumulator()
        await stream_logs(
            start_block=probe_start,
            end_block=probe_end - 1,
            accumulator=probe,
        )
        probe_results.append(
            {
                "date": probe_day.date().isoformat(),
                "start_block": probe_start,
                "end_block_exclusive": probe_end,
                "event_count": probe.event_count,
                "buy_count": probe.buy_count,
                "sell_count": probe.sell_count,
                "event_digest_sha256": probe.event_digest.hexdigest(),
                "first_samples": probe.first_samples,
                "last_samples": probe.last_samples,
            }
        )

    snapshot = inspect_snapshot_reference(session)
    bybit_specs = ((2021, 7, 31), (2023, 12, 31), (2024, 1, 31))
    bybit = []
    for year, month, last_day in bybit_specs:
        url = bybit_url(year, month, last_day)
        destination = cache / "bybit" / str(year) / url.rsplit("/", 1)[-1]
        bybit.append(inspect_bybit_probe(session, url, destination))

    missing_months = sorted(set(EXPECTED_PRE2024_MONTHS) - set(pre2024.month_counts))
    source_pass = (
        pre2024.event_count >= 500_000
        and len(hourly_rows) >= 15_000
        and pre2024.buy_count > 0
        and pre2024.sell_count > 0
        and not missing_months
        and all(item["event_count"] >= 100 for item in probe_results)
        and all(item["buy_count"] > 0 and item["sell_count"] > 0 for item in probe_results)
        and len(bybit) == 3
    )

    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "status": "SOURCE_GATE_PASS" if source_pass else "SOURCE_GATE_FAIL",
        "decision": "OPEN_FROZEN_PRE2024_MODEL_STAGE" if source_pass else "RETIRE_SOURCE_ROUTE",
        "primary_source": {
            "provider": "SQD public Ethereum Portal",
            "dataset": "ethereum-mainnet",
            "stream_type": "finalized",
            "pool": POOL,
            "topic0": SWAP_TOPIC,
            "metadata": metadata,
            "metadata_sha256": canonical_json_sha256(metadata),
            "start_block": start_block,
            "pre2024_end_block_exclusive": pre2024_end_block,
            "official_2024H1_end_block_exclusive": official_end_block,
            "availability_delay_seconds": AVAILABILITY_DELAY_SECONDS,
        },
        "pre2024": {
            "start": SOURCE_START.isoformat(),
            "end_exclusive": PRE2024_END.isoformat(),
            "event_count": pre2024.event_count,
            "buy_count": pre2024.buy_count,
            "sell_count": pre2024.sell_count,
            "hourly_row_count": len(hourly_rows),
            "event_bearing_months": dict(sorted(pre2024.month_counts.items())),
            "missing_expected_months": missing_months,
            "event_digest_sha256": pre2024.event_digest.hexdigest(),
            "first_samples": pre2024.first_samples,
            "last_samples": pre2024.last_samples,
            "hourly_path": str(hourly_path),
            "hourly_sha256": sha256_file(hourly_path),
        },
        "official_2024H1_source_continuity_probes_only": probe_results,
        "immutable_snapshot_reference": snapshot,
        "bybit_archive_probes": bybit,
        "gates": {
            "minimum_pre2024_events": 500_000,
            "minimum_hourly_rows": 15_000,
            "required_pre2024_months": list(EXPECTED_PRE2024_MONTHS),
            "minimum_events_per_frozen_2024H1_probe_day": 100,
            "both_directions_required": True,
        },
        "outcome_seal": {
            "market_labels_opened": False,
            "model_fitted": False,
            "strategy_actions_opened": False,
            "strategy_pnl_opened": False,
            "complete_2024H1_source_opened": False,
            "official_2024H1_account_opened": False,
            "orders_submitted": False,
        },
        "unopened_periods": ["complete_2024H1_source", "2024H1_account", "2024H2", "2025H1", "2025H2", "2026H1"],
    }
    result_path = output / "SOURCE_GATE.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "source_gate_sha256": sha256_file(result_path),
        "hourly_sha256": sha256_file(hourly_path),
        "event_digest_sha256": pre2024.event_digest.hexdigest(),
        "snapshot_metadata_sha256": snapshot["metadata_sha256"],
        "bybit_probe_sha256s": [item["sha256"] for item in bybit],
    }
    manifest_path = output / "SOURCE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    with (output / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
        for path in sorted(output.iterdir()):
            if path.is_file() and path.name != "SHA256SUMS.txt":
                handle.write(f"{sha256_file(path)}  {path.name}\n")
    return result


def self_test() -> None:
    def encode_signed(value: int) -> bytes:
        return (value if value >= 0 else (1 << 256) + value).to_bytes(32, "big")

    amount0 = 2_000_000_000
    amount1 = -10**18
    tick = 200_000
    tick_word = tick.to_bytes(32, "big", signed=False)
    payload = (
        encode_signed(amount0)
        + encode_signed(amount1)
        + (2**96).to_bytes(32, "big")
        + (123).to_bytes(32, "big")
        + tick_word
    )
    decoded = decode_swap("0x" + payload.hex())
    assert decoded["amount0_raw"] == amount0
    assert decoded["amount1_raw"] == amount1
    assert decoded["tick"] == tick
    assert decoded["price_usdc_per_weth"] > 1_000
    assert len(EXPECTED_PRE2024_MONTHS) == 30
    print(json.dumps({"status": "SELF_TEST_PASS", "expected_months": len(EXPECTED_PRE2024_MONTHS)}))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    result = asyncio.run(run(args.output, args.cache))
    print(json.dumps({"status": result["status"], "decision": result["decision"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
