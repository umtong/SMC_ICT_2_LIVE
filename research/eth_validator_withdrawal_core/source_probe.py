from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq

BASE_URL = (
    "https://data.ethpandaops.io/xatu/mainnet/databases/default/"
    "canonical_beacon_block_withdrawal"
)
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
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
PROBE_DATES = (
    date(2023, 4, 12),
    date(2023, 4, 13),
    date(2023, 7, 1),
    date(2023, 12, 31),
    date(2024, 1, 1),
    date(2025, 10, 5),
    date(2026, 6, 30),
)


@dataclass(frozen=True)
class Availability:
    day: str
    url: str
    status: int
    available: bool
    content_length: int | None
    attempts: int
    error: str | None


def days(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def url_for(day: date) -> str:
    return f"{BASE_URL}/{day.year}/{day.month}/{day.day}.parquet"


def _content_length(headers: Any) -> int | None:
    value = headers.get("Content-Length")
    if value is not None:
        try:
            return int(value)
        except ValueError:
            pass
    content_range = headers.get("Content-Range")
    if content_range and "/" in content_range:
        try:
            return int(content_range.rsplit("/", 1)[1])
        except ValueError:
            pass
    return None


def check_url(day: date, retries: int = 2) -> Availability:
    url = url_for(day)
    last_error: str | None = None
    last_status = 0
    for attempt in range(1, retries + 2):
        try:
            request = urllib.request.Request(
                url,
                method="HEAD",
                headers={"User-Agent": "SMC-ICT-validator-withdrawal-source-gate/1"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                status = int(response.status)
                return Availability(
                    day=day.isoformat(),
                    url=url,
                    status=status,
                    available=status == 200,
                    content_length=_content_length(response.headers),
                    attempts=attempt,
                    error=None,
                )
        except urllib.error.HTTPError as exc:
            last_status = int(exc.code)
            # Some object stores reject HEAD even when GET is available.
            if exc.code in {403, 405}:
                try:
                    request = urllib.request.Request(
                        url,
                        method="GET",
                        headers={
                            "Range": "bytes=0-0",
                            "User-Agent": "SMC-ICT-validator-withdrawal-source-gate/1",
                        },
                    )
                    with urllib.request.urlopen(request, timeout=30) as response:
                        status = int(response.status)
                        return Availability(
                            day=day.isoformat(),
                            url=url,
                            status=status,
                            available=status in {200, 206},
                            content_length=_content_length(response.headers),
                            attempts=attempt,
                            error=None,
                        )
                except Exception as inner:  # noqa: BLE001 - preserved as evidence
                    last_error = f"{type(inner).__name__}: {inner}"
            else:
                last_error = f"HTTPError: {exc.code}"
                if exc.code == 404:
                    break
        except Exception as exc:  # noqa: BLE001 - preserved as evidence
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt <= retries:
            time.sleep(0.5 * attempt)
    return Availability(
        day=day.isoformat(),
        url=url,
        status=last_status,
        available=False,
        content_length=None,
        attempts=retries + 1,
        error=last_error,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, target: Path, retries: int = 3) -> None:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "SMC-ICT-validator-withdrawal-source-gate/1"},
            )
            with urllib.request.urlopen(request, timeout=120) as response, target.open(
                "wb"
            ) as output:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
            if target.stat().st_size == 0:
                raise RuntimeError("empty download")
            return
        except Exception as exc:  # noqa: BLE001 - retained in final failure
            last = exc
            target.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(attempt)
    raise RuntimeError(f"download failed for {url}: {last}")


def normalize_address(value: Any) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            value = "0x" + value.hex()
    return str(value)


def integer_values(array: pa.ChunkedArray) -> list[int]:
    values: list[int] = []
    for value in array.to_pylist():
        if value is None:
            raise ValueError("unexpected null integer")
        values.append(int(value))
    return values


def datetime_values(array: pa.ChunkedArray) -> list[datetime]:
    values: list[datetime] = []
    for value in array.to_pylist():
        if value is None:
            raise ValueError("unexpected null datetime")
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        values.append(dt.astimezone(timezone.utc))
    return values


def inspect_file(day: date, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    table = pq.read_table(
        path,
        columns=sorted(REQUIRED_COLUMNS),
        use_threads=True,
    )
    columns = set(table.column_names)
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise ValueError(f"missing columns: {missing}")
    rows = table.num_rows
    if rows <= 0:
        raise ValueError("empty parquet")

    indices = integer_values(table["withdrawal_index"])
    validators = integer_values(table["withdrawal_validator_index"])
    amounts_gwei = integer_values(table["withdrawal_amount"])
    slots = integer_values(table["slot"])
    timestamps = datetime_values(table["slot_start_date_time"])
    addresses = [normalize_address(value) for value in table["withdrawal_address"].to_pylist()]
    roots = [normalize_address(value) for value in table["block_root"].to_pylist()]

    if indices != sorted(indices):
        raise ValueError("withdrawal indices are not monotonic within file")
    if len(indices) != len(set(indices)):
        raise ValueError("duplicate withdrawal indices within file")
    if any(amount <= 0 for amount in amounts_gwei):
        raise ValueError("non-positive withdrawal amount")
    if any(not ADDRESS_RE.match(address) for address in addresses):
        bad = next(address for address in addresses if not ADDRESS_RE.match(address))
        raise ValueError(f"invalid withdrawal address: {bad!r}")
    if any(not root.startswith("0x") or len(root) != 66 for root in roots):
        raise ValueError("invalid block root")
    if any(ts.date() != day for ts in timestamps):
        raise ValueError("slot timestamp falls outside partition day")

    hourly: dict[datetime, dict[str, Any]] = defaultdict(
        lambda: {
            "event_count": 0,
            "amount_gwei": 0,
            "validators": set(),
            "addresses": Counter(),
            "max_amount_gwei": 0,
        }
    )
    for ts, amount, validator, address in zip(
        timestamps, amounts_gwei, validators, addresses, strict=True
    ):
        hour = ts.replace(minute=0, second=0, microsecond=0)
        item = hourly[hour]
        item["event_count"] += 1
        item["amount_gwei"] += amount
        item["validators"].add(validator)
        item["addresses"][address] += amount
        item["max_amount_gwei"] = max(item["max_amount_gwei"], amount)

    hourly_rows: list[dict[str, Any]] = []
    for hour, item in sorted(hourly.items()):
        total = item["amount_gwei"]
        shares = [amount / total for amount in item["addresses"].values()]
        hhi = sum(share * share for share in shares)
        hourly_rows.append(
            {
                "partition_day": day.isoformat(),
                "hour": hour.isoformat().replace("+00:00", "Z"),
                "event_count": item["event_count"],
                "amount_eth": total / 1e9,
                "unique_validators": len(item["validators"]),
                "unique_addresses": len(item["addresses"]),
                "max_amount_eth": item["max_amount_gwei"] / 1e9,
                "address_amount_hhi": hhi,
            }
        )

    summary = {
        "day": day.isoformat(),
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "rows": rows,
        "schema": str(table.schema),
        "min_withdrawal_index": min(indices),
        "max_withdrawal_index": max(indices),
        "min_slot": min(slots),
        "max_slot": max(slots),
        "min_slot_time": min(timestamps).isoformat(),
        "max_slot_time": max(timestamps).isoformat(),
        "total_eth": sum(amounts_gwei) / 1e9,
        "median_amount_eth": sorted(amounts_gwei)[len(amounts_gwei) // 2] / 1e9,
        "max_amount_eth": max(amounts_gwei) / 1e9,
        "unique_validators": len(set(validators)),
        "unique_addresses": len(set(addresses)),
        "hour_count": len(hourly_rows),
        "validation": "PASS",
    }
    return summary, hourly_rows


def contiguous_ranges(records: list[Availability], available: bool) -> list[list[str]]:
    selected = [date.fromisoformat(item.day) for item in records if item.available == available]
    if not selected:
        return []
    selected.sort()
    ranges: list[list[str]] = []
    start = previous = selected[0]
    for current in selected[1:]:
        if current != previous + timedelta(days=1):
            ranges.append([start.isoformat(), previous.isoformat()])
            start = current
        previous = current
    ranges.append([start.isoformat(), previous.isoformat()])
    return ranges


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifact"))
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    downloads = args.output / "probe_files"
    downloads.mkdir(parents=True, exist_ok=True)

    all_dates = list(days(date(2023, 4, 12), date(2026, 6, 30)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(check_url, all_dates))
    records.sort(key=lambda item: item.day)

    pre_records = [item for item in records if item.day <= "2023-12-31"]
    official_records = [item for item in records if item.day >= "2024-01-01"]
    availability_by_day = {item.day: item for item in records}

    probe_summaries: list[dict[str, Any]] = []
    hourly_rows: list[dict[str, Any]] = []
    probe_errors: dict[str, str] = {}
    for probe_day in PROBE_DATES:
        record = availability_by_day[probe_day.isoformat()]
        if not record.available:
            probe_errors[probe_day.isoformat()] = record.error or f"HTTP {record.status}"
            continue
        target = downloads / f"{probe_day.isoformat()}.parquet"
        try:
            download(record.url, target)
            summary, rows = inspect_file(probe_day, target)
            probe_summaries.append(summary)
            hourly_rows.extend(rows)
        except Exception as exc:  # noqa: BLE001 - source evidence
            probe_errors[probe_day.isoformat()] = f"{type(exc).__name__}: {exc}"

    expected_pre = len(pre_records)
    available_pre = sum(item.available for item in pre_records)
    expected_official = len(official_records)
    available_official = sum(item.available for item in official_records)
    pre_complete = available_pre == expected_pre
    required_pre_probes = {day.isoformat() for day in PROBE_DATES if day.year == 2023}
    valid_probe_days = {item["day"] for item in probe_summaries}
    probes_valid = required_pre_probes.issubset(valid_probe_days)

    source_status = (
        "PRELIMINARY_SOURCE_PASS_FULL_PRE2024_URL_COVERAGE_AND_PROBE_VALIDITY"
        if pre_complete and probes_valid
        else "SOURCE_GATE_FAIL"
    )
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260730-ETH-VALIDATOR-WITHDRAWAL-CORE-001",
        "result_id": "RES-20260730-ETH-VALIDATOR-WITHDRAWAL-SOURCE-001",
        "status": source_status,
        "market_outcomes_opened": False,
        "bybit_data_opened": False,
        "orders_submitted": False,
        "source": {
            "provider": "ethPandaOps Xatu",
            "table": "canonical_beacon_block_withdrawal",
            "base_url": BASE_URL,
        },
        "pre2024_coverage": {
            "start": "2023-04-12",
            "end": "2023-12-31",
            "expected_days": expected_pre,
            "available_days": available_pre,
            "coverage_ratio": available_pre / expected_pre,
            "missing_ranges": contiguous_ranges(pre_records, available=False),
            "complete": pre_complete,
        },
        "official_source_coverage": {
            "start": "2024-01-01",
            "end": "2026-06-30",
            "expected_days": expected_official,
            "available_days": available_official,
            "coverage_ratio": available_official / expected_official,
            "available_ranges": contiguous_ranges(official_records, available=True),
            "missing_ranges": contiguous_ranges(official_records, available=False),
            "complete": available_official == expected_official,
        },
        "probe_dates": [day.isoformat() for day in PROBE_DATES],
        "valid_probe_days": sorted(valid_probe_days),
        "probe_errors": probe_errors,
        "probe_summaries": probe_summaries,
        "full_pre2024_chronology_validation_required_before_market_open": True,
        "decision": (
            "Proceed only to full source-only chronology aggregation; market outcomes remain sealed."
            if source_status.startswith("PRELIMINARY_SOURCE_PASS")
            else "Close or repair source transport without opening market outcomes."
        ),
    }

    (args.output / "AVAILABILITY.json").write_text(
        json.dumps([asdict(item) for item in records], indent=2, sort_keys=True)
    )
    (args.output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    with (args.output / "PROBE_HOURLY.csv").open("w", newline="") as handle:
        fields = [
            "partition_day",
            "hour",
            "event_count",
            "amount_eth",
            "unique_validators",
            "unique_addresses",
            "max_amount_eth",
            "address_amount_hhi",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(hourly_rows)

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
