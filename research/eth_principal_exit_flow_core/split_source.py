from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq

START = date(2023, 4, 12)
END = date(2023, 12, 31)
BASE_URL = (
    "https://data.ethpandaops.io/xatu/mainnet/databases/default/"
    "canonical_beacon_block_withdrawal"
)
REQUIRED_COLUMNS = {
    "slot",
    "slot_start_date_time",
    "epoch",
    "block_root",
    "withdrawal_index",
    "withdrawal_validator_index",
    "withdrawal_address",
    "withdrawal_amount",
}
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
PRINCIPAL_GWEI = 16_000_000_000
SOURCE_CONFIRMATION_DELAY = timedelta(minutes=3)


def days(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def url_for(day: date) -> str:
    return f"{BASE_URL}/{day.year}/{day.month}/{day.day}.parquet"


def download(url: str, target: Path, retries: int = 4) -> None:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "SMC-ICT-principal-exit-flow-source/1"},
            )
            with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
            if target.stat().st_size <= 0:
                raise RuntimeError("empty source file")
            return
        except Exception as exc:  # noqa: BLE001 - retained for source evidence
            last = exc
            target.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(attempt)
    raise RuntimeError(f"download failed for {url}: {last}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decode_integer(value: Any) -> int:
    if value is None:
        raise ValueError("unexpected null integer")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return int.from_bytes(bytes(value), byteorder="little", signed=False)
    return int(value)


def integer_values(array: pa.ChunkedArray) -> list[int]:
    return [decode_integer(value) for value in array.to_pylist()]


def decode_datetime(value: Any) -> datetime:
    if value is None:
        raise ValueError("unexpected null datetime")
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        text = str(value)
        if text.isdigit():
            parsed = datetime.fromtimestamp(int(text), tz=timezone.utc)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def datetime_values(array: pa.ChunkedArray) -> list[datetime]:
    return [decode_datetime(value) for value in array.to_pylist()]


def normalize_fixed_hex(value: Any, expected_bytes: int) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        try:
            decoded = raw.decode("utf-8")
            if decoded.startswith("0x"):
                return decoded
        except UnicodeDecodeError:
            pass
        if len(raw) == expected_bytes:
            return "0x" + raw.hex()
        decoded = raw.rstrip(b"\x00").decode("ascii")
        return decoded
    return str(value)


def validate_index_set(indices: list[int]) -> tuple[int, int]:
    if not indices:
        raise ValueError("empty withdrawal index set")
    if len(indices) != len(set(indices)):
        raise ValueError("duplicate withdrawal index")
    ordered = sorted(indices)
    if ordered[-1] - ordered[0] + 1 != len(ordered):
        raise ValueError("non-contiguous withdrawal index set")
    return ordered[0], ordered[-1]


def empty_stream() -> dict[str, Any]:
    return {
        "event_count": 0,
        "amount_gwei": 0,
        "validators": set(),
        "addresses": Counter(),
        "max_amount_gwei": 0,
    }


def add_stream(item: dict[str, Any], amount: int, validator: int, address: str) -> None:
    item["event_count"] += 1
    item["amount_gwei"] += amount
    item["validators"].add(validator)
    item["addresses"][address] += amount
    item["max_amount_gwei"] = max(item["max_amount_gwei"], amount)


def stream_fields(prefix: str, item: dict[str, Any]) -> dict[str, Any]:
    total = int(item["amount_gwei"])
    shares = [amount / total for amount in item["addresses"].values()] if total else []
    return {
        f"{prefix}_event_count": int(item["event_count"]),
        f"{prefix}_amount_gwei": total,
        f"{prefix}_amount_eth": total / 1e9,
        f"{prefix}_unique_validators": len(item["validators"]),
        f"{prefix}_unique_addresses": len(item["addresses"]),
        f"{prefix}_max_amount_gwei": int(item["max_amount_gwei"]),
        f"{prefix}_max_amount_eth": int(item["max_amount_gwei"]) / 1e9,
        f"{prefix}_address_amount_hhi": sum(share * share for share in shares),
    }


def aggregate_day(
    day: date, path: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], set[int], set[str]]:
    table = pq.read_table(path, columns=sorted(REQUIRED_COLUMNS), use_threads=True)
    missing = sorted(REQUIRED_COLUMNS - set(table.column_names))
    if missing:
        raise ValueError(f"missing columns: {missing}")
    if table.num_rows <= 0:
        raise ValueError("empty daily source partition")

    indices = integer_values(table["withdrawal_index"])
    validators = integer_values(table["withdrawal_validator_index"])
    amounts = integer_values(table["withdrawal_amount"])
    slots = integer_values(table["slot"])
    timestamps = datetime_values(table["slot_start_date_time"])
    addresses = [normalize_fixed_hex(value, 20) for value in table["withdrawal_address"].to_pylist()]
    roots = [normalize_fixed_hex(value, 32) for value in table["block_root"].to_pylist()]

    min_index, max_index = validate_index_set(indices)
    if any(amount <= 0 for amount in amounts):
        raise ValueError("non-positive withdrawal amount")
    if any(not ADDRESS_RE.match(address) for address in addresses):
        bad = next(address for address in addresses if not ADDRESS_RE.match(address))
        raise ValueError(f"invalid withdrawal address: {bad!r}")
    if any(not root.startswith("0x") or len(root) != 66 for root in roots):
        raise ValueError("invalid block root")
    if any(timestamp.date() != day for timestamp in timestamps):
        raise ValueError("slot timestamp outside daily partition")

    hourly: dict[datetime, dict[str, Any]] = defaultdict(
        lambda: {
            "all": empty_stream(),
            "principal": empty_stream(),
            "partial": empty_stream(),
            "gap_8_to_16_count": 0,
            "gap_8_to_16_gwei": 0,
        }
    )
    principal_rows = 0
    principal_gwei = 0
    partial_rows = 0
    partial_gwei = 0
    gap_rows = 0
    gap_gwei = 0
    for timestamp, amount, validator, address in zip(
        timestamps, amounts, validators, addresses, strict=True
    ):
        hour = timestamp.replace(minute=0, second=0, microsecond=0)
        item = hourly[hour]
        add_stream(item["all"], amount, validator, address)
        if amount >= PRINCIPAL_GWEI:
            add_stream(item["principal"], amount, validator, address)
            principal_rows += 1
            principal_gwei += amount
        else:
            add_stream(item["partial"], amount, validator, address)
            partial_rows += 1
            partial_gwei += amount
        if 8_000_000_000 <= amount < PRINCIPAL_GWEI:
            item["gap_8_to_16_count"] += 1
            item["gap_8_to_16_gwei"] += amount
            gap_rows += 1
            gap_gwei += amount

    hourly_rows: list[dict[str, Any]] = []
    for hour, item in sorted(hourly.items()):
        row = {
            "source_hour_start": hour,
            "source_hour_end": hour + timedelta(hours=1),
            "available_at": hour + timedelta(hours=1) + SOURCE_CONFIRMATION_DELAY,
            **stream_fields("all", item["all"]),
            **stream_fields("principal", item["principal"]),
            **stream_fields("partial", item["partial"]),
            "gap_8_to_16_count": int(item["gap_8_to_16_count"]),
            "gap_8_to_16_eth": int(item["gap_8_to_16_gwei"]) / 1e9,
        }
        row["principal_amount_share"] = (
            row["principal_amount_gwei"] / row["all_amount_gwei"]
            if row["all_amount_gwei"]
            else 0.0
        )
        row["principal_event_share"] = (
            row["principal_event_count"] / row["all_event_count"]
            if row["all_event_count"]
            else 0.0
        )
        hourly_rows.append(row)

    summary = {
        "day": day.isoformat(),
        "url": url_for(day),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "rows": table.num_rows,
        "min_withdrawal_index": min_index,
        "max_withdrawal_index": max_index,
        "min_slot": min(slots),
        "max_slot": max(slots),
        "min_slot_time": min(timestamps).isoformat(),
        "max_slot_time": max(timestamps).isoformat(),
        "total_gwei": sum(amounts),
        "total_eth": sum(amounts) / 1e9,
        "principal_rows": principal_rows,
        "principal_gwei": principal_gwei,
        "principal_eth": principal_gwei / 1e9,
        "partial_rows": partial_rows,
        "partial_gwei": partial_gwei,
        "partial_eth": partial_gwei / 1e9,
        "gap_8_to_16_rows": gap_rows,
        "gap_8_to_16_gwei": gap_gwei,
        "gap_8_to_16_eth": gap_gwei / 1e9,
        "unique_validators": len(set(validators)),
        "unique_addresses": len(set(addresses)),
        "hour_count": len(hourly_rows),
        "validation": "PASS",
    }
    if summary["principal_rows"] + summary["partial_rows"] != summary["rows"]:
        raise ValueError("daily row conservation failed")
    if summary["principal_gwei"] + summary["partial_gwei"] != summary["total_gwei"]:
        raise ValueError("daily ETH conservation failed")
    return summary, hourly_rows, set(validators), set(addresses)


def assert_global_continuity(daily: list[dict[str, Any]]) -> None:
    if len(daily) != 264:
        raise ValueError(f"expected 264 daily partitions, found {len(daily)}")
    expected_day = START
    previous_max: int | None = None
    for item in daily:
        current_day = date.fromisoformat(item["day"])
        if current_day != expected_day:
            raise ValueError(f"daily gap: expected {expected_day}, got {current_day}")
        if previous_max is None:
            if item["min_withdrawal_index"] != 0:
                raise ValueError("withdrawal sequence does not start at zero")
        elif item["min_withdrawal_index"] != previous_max + 1:
            raise ValueError("global withdrawal index discontinuity")
        previous_max = item["max_withdrawal_index"]
        expected_day += timedelta(days=1)
    if expected_day - timedelta(days=1) != END:
        raise ValueError("source chronology did not reach end date")


def assert_hourly_continuity(hourly: list[dict[str, Any]]) -> None:
    ordered = sorted(row["source_hour_start"] for row in hourly)
    if not ordered:
        raise ValueError("empty hourly chronology")
    expected = ordered[0]
    for observed in ordered:
        if observed != expected:
            raise ValueError(f"hourly gap: expected {expected}, got {observed}")
        expected += timedelta(hours=1)


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty parquet: {path}")
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifact"))
    parser.add_argument("--download-workers", type=int, default=8)
    parser.add_argument("--batch-days", type=int, default=16)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    work = args.output / "downloads"
    work.mkdir(parents=True, exist_ok=True)

    requested = list(days(START, END))
    daily_rows: list[dict[str, Any]] = []
    hourly_rows: list[dict[str, Any]] = []
    global_validators: set[int] = set()
    global_addresses: set[str] = set()

    for offset in range(0, len(requested), args.batch_days):
        batch = requested[offset : offset + args.batch_days]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.download_workers) as pool:
            downloaded = list(
                pool.map(
                    lambda day: (
                        day,
                        (lambda path: (download(url_for(day), path), path)[1])(
                            work / f"{day.isoformat()}.parquet"
                        ),
                    ),
                    batch,
                )
            )
        for day, path in sorted(downloaded):
            summary, hours, validators, addresses = aggregate_day(day, path)
            daily_rows.append(summary)
            hourly_rows.extend(hours)
            global_validators.update(validators)
            global_addresses.update(addresses)
            path.unlink()
        print(
            json.dumps(
                {
                    "processed_days": len(daily_rows),
                    "latest_day": daily_rows[-1]["day"],
                    "rows": sum(item["rows"] for item in daily_rows),
                    "principal_rows": sum(item["principal_rows"] for item in daily_rows),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    assert_global_continuity(daily_rows)
    assert_hourly_continuity(hourly_rows)
    total_rows = sum(item["rows"] for item in daily_rows)
    total_gwei = sum(item["total_gwei"] for item in daily_rows)
    principal_rows = sum(item["principal_rows"] for item in daily_rows)
    principal_gwei = sum(item["principal_gwei"] for item in daily_rows)
    partial_rows = sum(item["partial_rows"] for item in daily_rows)
    partial_gwei = sum(item["partial_gwei"] for item in daily_rows)
    gap_rows = sum(item["gap_8_to_16_rows"] for item in daily_rows)
    gap_gwei = sum(item["gap_8_to_16_gwei"] for item in daily_rows)
    if principal_rows + partial_rows != total_rows:
        raise ValueError("global row conservation failed")
    if principal_gwei + partial_gwei != total_gwei:
        raise ValueError("global ETH conservation failed")

    write_parquet(args.output / "DAILY_SPLIT_SOURCE.parquet", daily_rows)
    write_parquet(args.output / "HOURLY_SPLIT_SOURCE.parquet", hourly_rows)
    (args.output / "FILE_MANIFEST.json").write_text(
        json.dumps(daily_rows, indent=2, sort_keys=True)
    )
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260730-ETH-PRINCIPAL-EXIT-FLOW-CORE-001",
        "result_id": "RES-20260730-ETH-PRINCIPAL-EXIT-SOURCE-001",
        "status": "SOURCE_PASS_PRINCIPAL_PARTIAL_SPLIT",
        "source_period": [START.isoformat(), END.isoformat()],
        "principal_scale_threshold_eth": PRINCIPAL_GWEI / 1e9,
        "daily_partitions": len(daily_rows),
        "hourly_rows": len(hourly_rows),
        "withdrawal_rows": total_rows,
        "min_withdrawal_index": daily_rows[0]["min_withdrawal_index"],
        "max_withdrawal_index": daily_rows[-1]["max_withdrawal_index"],
        "global_index_contiguous": True,
        "hourly_chronology_contiguous": True,
        "total_gwei": total_gwei,
        "total_eth": total_gwei / 1e9,
        "principal_rows": principal_rows,
        "principal_eth": principal_gwei / 1e9,
        "partial_rows": partial_rows,
        "partial_eth": partial_gwei / 1e9,
        "gap_8_to_16_rows": gap_rows,
        "gap_8_to_16_eth": gap_gwei / 1e9,
        "principal_row_share": principal_rows / total_rows,
        "principal_amount_share": principal_gwei / total_gwei,
        "unique_validators": len(global_validators),
        "unique_addresses": len(global_addresses),
        "source_confirmation_delay_seconds": int(SOURCE_CONFIRMATION_DELAY.total_seconds()),
        "row_conservation_pass": principal_rows + partial_rows == total_rows,
        "amount_conservation_pass": principal_gwei + partial_gwei == total_gwei,
        "market_outcomes_opened": False,
        "bybit_data_opened": False,
        "orders_submitted": False,
        "decision": "Source split passes. Conditional pre-2024 principal-versus-partial economics may open under the frozen contract.",
    }
    (args.output / "SOURCE_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True)
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
