from __future__ import annotations

import argparse
import concurrent.futures
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

import source_probe as source

START = date(2023, 4, 12)
END = date(2023, 12, 31)
SOURCE_CONFIRMATION_DELAY = timedelta(minutes=3)


def download_day(day: date, directory: Path) -> tuple[date, Path]:
    path = directory / f"{day.isoformat()}.parquet"
    source.download(source.url_for(day), path)
    return day, path


def validate_index_set(indices: list[int]) -> tuple[int, int]:
    if not indices:
        raise ValueError("empty withdrawal index set")
    if len(indices) != len(set(indices)):
        raise ValueError("duplicate withdrawal index")
    ordered = sorted(indices)
    if ordered[-1] - ordered[0] + 1 != len(ordered):
        raise ValueError("non-contiguous withdrawal index set")
    return ordered[0], ordered[-1]


def aggregate_day(day: date, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], set[int], set[str]]:
    table = pq.read_table(path, columns=sorted(source.REQUIRED_COLUMNS), use_threads=True)
    missing = sorted(source.REQUIRED_COLUMNS - set(table.column_names))
    if missing:
        raise ValueError(f"missing columns: {missing}")
    if table.num_rows <= 0:
        raise ValueError("empty daily source partition")

    indices = source.integer_values(table["withdrawal_index"])
    validators = source.integer_values(table["withdrawal_validator_index"])
    amounts_gwei = source.integer_values(table["withdrawal_amount"])
    slots = source.integer_values(table["slot"])
    timestamps = source.datetime_values(table["slot_start_date_time"])
    addresses = [source.normalize_address(v) for v in table["withdrawal_address"].to_pylist()]
    roots = [source.normalize_address(v) for v in table["block_root"].to_pylist()]

    min_index, max_index = validate_index_set(indices)
    if any(amount <= 0 for amount in amounts_gwei):
        raise ValueError("non-positive withdrawal amount")
    if any(not source.ADDRESS_RE.match(address) for address in addresses):
        raise ValueError("invalid withdrawal address")
    if any(not root.startswith("0x") or len(root) != 66 for root in roots):
        raise ValueError("invalid block root")
    if any(ts.date() != day for ts in timestamps):
        raise ValueError("slot timestamp outside daily partition")

    hourly: dict[datetime, dict[str, Any]] = defaultdict(
        lambda: {
            "event_count": 0,
            "amount_gwei": 0,
            "validators": set(),
            "addresses": Counter(),
            "max_amount_gwei": 0,
        }
    )
    for timestamp, amount, validator, address in zip(
        timestamps, amounts_gwei, validators, addresses, strict=True
    ):
        hour = timestamp.replace(minute=0, second=0, microsecond=0)
        item = hourly[hour]
        item["event_count"] += 1
        item["amount_gwei"] += amount
        item["validators"].add(validator)
        item["addresses"][address] += amount
        item["max_amount_gwei"] = max(item["max_amount_gwei"], amount)

    hourly_rows: list[dict[str, Any]] = []
    for hour, item in sorted(hourly.items()):
        total = int(item["amount_gwei"])
        shares = [value / total for value in item["addresses"].values()]
        hourly_rows.append(
            {
                "source_hour_start": hour,
                "source_hour_end": hour + timedelta(hours=1),
                "available_at": hour + timedelta(hours=1) + SOURCE_CONFIRMATION_DELAY,
                "event_count": int(item["event_count"]),
                "amount_gwei": total,
                "amount_eth": total / 1e9,
                "unique_validators": len(item["validators"]),
                "unique_addresses": len(item["addresses"]),
                "max_amount_gwei": int(item["max_amount_gwei"]),
                "max_amount_eth": int(item["max_amount_gwei"]) / 1e9,
                "address_amount_hhi": sum(share * share for share in shares),
            }
        )

    summary = {
        "day": day.isoformat(),
        "url": source.url_for(day),
        "bytes": path.stat().st_size,
        "sha256": source.sha256(path),
        "rows": table.num_rows,
        "min_withdrawal_index": min_index,
        "max_withdrawal_index": max_index,
        "min_slot": min(slots),
        "max_slot": max(slots),
        "min_slot_time": min(timestamps).isoformat(),
        "max_slot_time": max(timestamps).isoformat(),
        "total_gwei": sum(amounts_gwei),
        "total_eth": sum(amounts_gwei) / 1e9,
        "max_amount_gwei": max(amounts_gwei),
        "max_amount_eth": max(amounts_gwei) / 1e9,
        "unique_validators": len(set(validators)),
        "unique_addresses": len(set(addresses)),
        "hour_count": len(hourly_rows),
        "validation": "PASS",
    }
    return summary, hourly_rows, set(validators), set(addresses)


def assert_global_continuity(daily: list[dict[str, Any]]) -> None:
    if not daily:
        raise ValueError("no daily source rows")
    expected_day = START
    previous_max: int | None = None
    for item in daily:
        current_day = date.fromisoformat(item["day"])
        if current_day != expected_day:
            raise ValueError(f"daily partition gap: expected {expected_day}, got {current_day}")
        if previous_max is None:
            if item["min_withdrawal_index"] != 0:
                raise ValueError("global withdrawal sequence does not start at zero")
        elif item["min_withdrawal_index"] != previous_max + 1:
            raise ValueError(
                "global withdrawal-index discontinuity: "
                f"previous={previous_max}, next={item['min_withdrawal_index']}"
            )
        previous_max = item["max_withdrawal_index"]
        expected_day += timedelta(days=1)
    if expected_day - timedelta(days=1) != END:
        raise ValueError("full pre-2024 source chronology did not reach end date")


def assert_hourly_continuity(hourly: list[dict[str, Any]]) -> None:
    if not hourly:
        raise ValueError("no hourly source rows")
    ordered = sorted(row["source_hour_start"] for row in hourly)
    expected = ordered[0]
    for observed in ordered:
        if observed != expected:
            raise ValueError(f"hourly source gap: expected {expected}, got {observed}")
        expected += timedelta(hours=1)


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty parquet: {path}")
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="zstd")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifact"))
    parser.add_argument("--download-workers", type=int, default=8)
    parser.add_argument("--batch-days", type=int, default=16)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    work = args.output / "downloads"
    work.mkdir(parents=True, exist_ok=True)

    requested_days = list(source.days(START, END))
    daily_rows: list[dict[str, Any]] = []
    hourly_rows: list[dict[str, Any]] = []
    global_validators: set[int] = set()
    global_addresses: set[str] = set()

    for offset in range(0, len(requested_days), args.batch_days):
        batch = requested_days[offset : offset + args.batch_days]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.download_workers) as pool:
            downloaded = list(pool.map(lambda day: download_day(day, work), batch))
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
                    "total_rows": sum(item["rows"] for item in daily_rows),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    assert_global_continuity(daily_rows)
    assert_hourly_continuity(hourly_rows)
    if len(daily_rows) != 264:
        raise ValueError(f"expected 264 days, found {len(daily_rows)}")

    write_parquet(args.output / "DAILY_SOURCE.parquet", daily_rows)
    write_parquet(args.output / "HOURLY_SOURCE.parquet", hourly_rows)
    (args.output / "FILE_MANIFEST.json").write_text(
        json.dumps(daily_rows, indent=2, sort_keys=True)
    )

    total_rows = sum(item["rows"] for item in daily_rows)
    total_gwei = sum(item["total_gwei"] for item in daily_rows)
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260730-ETH-VALIDATOR-WITHDRAWAL-CORE-001",
        "result_id": "RES-20260730-ETH-VALIDATOR-WITHDRAWAL-SOURCE-001",
        "status": "SOURCE_PASS_FULL_PRE2024_CHRONOLOGY",
        "source_period": [START.isoformat(), END.isoformat()],
        "daily_partitions": len(daily_rows),
        "hourly_rows": len(hourly_rows),
        "withdrawal_rows": total_rows,
        "min_withdrawal_index": daily_rows[0]["min_withdrawal_index"],
        "max_withdrawal_index": daily_rows[-1]["max_withdrawal_index"],
        "global_index_contiguous": True,
        "hourly_chronology_contiguous": True,
        "total_gwei": total_gwei,
        "total_eth": total_gwei / 1e9,
        "unique_validators": len(global_validators),
        "unique_addresses": len(global_addresses),
        "source_confirmation_delay_seconds": int(SOURCE_CONFIRMATION_DELAY.total_seconds()),
        "market_outcomes_opened": False,
        "bybit_data_opened": False,
        "model_opened": False,
        "orders_submitted": False,
        "decision": "Source authority passes. Conditional pre-2024 mechanism economics may now open under the frozen contract.",
    }
    (args.output / "SOURCE_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True)
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
