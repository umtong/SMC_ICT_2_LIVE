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
    "canonical_beacon_block_deposit"
)
REQUIRED_COLUMNS = {
    "slot",
    "slot_start_date_time",
    "block_root",
    "deposit_data_pubkey",
    "deposit_data_withdrawal_credentials",
    "deposit_data_amount",
    "deposit_data_signature",
}
SOURCE_DELAY_SECONDS = 180
HEX_32 = re.compile(r"^0x[0-9a-fA-F]{64}$")


def days(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def url_for(day: date) -> str:
    return f"{BASE_URL}/{day.year}/{day.month}/{day.day}.parquet"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(day: date, target: Path, retries: int = 4) -> tuple[date, Path]:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url_for(day),
                headers={"User-Agent": "SMC-ICT-net-staking-source/1"},
            )
            with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
            if target.stat().st_size <= 0:
                raise RuntimeError("empty source file")
            return day, target
        except Exception as exc:  # noqa: BLE001 - preserved as source evidence
            last = exc
            target.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(attempt)
    raise RuntimeError(f"download failed for {day}: {last}")


def decode_integer(value: Any) -> int:
    if value is None:
        raise ValueError("unexpected null integer")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return int.from_bytes(bytes(value), byteorder="little", signed=False)
    return int(value)


def decode_datetime(value: Any) -> datetime:
    if value is None:
        raise ValueError("unexpected null timestamp")
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


def normalize_text(value: Any) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        try:
            return raw.rstrip(b"\x00").decode("ascii")
        except UnicodeDecodeError:
            return "0x" + raw.hex()
    return str(value)


def inspect_day(day: date, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], set[str], set[str], set[str]]:
    table = pq.read_table(path, columns=sorted(REQUIRED_COLUMNS), use_threads=True)
    missing = sorted(REQUIRED_COLUMNS - set(table.column_names))
    if missing:
        raise ValueError(f"missing columns: {missing}")
    if table.num_rows <= 0:
        raise ValueError(f"empty deposit partition: {day}")

    slots = [decode_integer(value) for value in table["slot"].to_pylist()]
    timestamps = [decode_datetime(value) for value in table["slot_start_date_time"].to_pylist()]
    amounts = [decode_integer(value) for value in table["deposit_data_amount"].to_pylist()]
    roots = [normalize_text(value) for value in table["block_root"].to_pylist()]
    pubkeys = [normalize_text(value) for value in table["deposit_data_pubkey"].to_pylist()]
    credentials = [normalize_text(value) for value in table["deposit_data_withdrawal_credentials"].to_pylist()]
    signatures = [normalize_text(value) for value in table["deposit_data_signature"].to_pylist()]

    if any(amount <= 0 for amount in amounts):
        raise ValueError("non-positive deposit amount")
    if any(timestamp.date() != day for timestamp in timestamps):
        raise ValueError("slot timestamp outside daily partition")
    if any(not root.startswith("0x") or len(root) != 66 for root in roots):
        raise ValueError("invalid block root")
    if any(not value for value in pubkeys + credentials + signatures):
        raise ValueError("empty deposit identity field")

    event_keys = {
        f"{root}:{pubkey}:{signature}"
        for root, pubkey, signature in zip(roots, pubkeys, signatures, strict=True)
    }
    if len(event_keys) != table.num_rows:
        raise ValueError("duplicate deposit event key")

    hourly: dict[datetime, dict[str, Any]] = defaultdict(
        lambda: {
            "event_count": 0,
            "amount_gwei": 0,
            "pubkeys": set(),
            "credentials": set(),
            "credential_amount": Counter(),
            "max_amount_gwei": 0,
        }
    )
    for timestamp, amount, pubkey, credential in zip(
        timestamps, amounts, pubkeys, credentials, strict=True
    ):
        hour = timestamp.replace(minute=0, second=0, microsecond=0)
        item = hourly[hour]
        item["event_count"] += 1
        item["amount_gwei"] += amount
        item["pubkeys"].add(pubkey)
        item["credentials"].add(credential)
        item["credential_amount"][credential] += amount
        item["max_amount_gwei"] = max(item["max_amount_gwei"], amount)

    hourly_rows: list[dict[str, Any]] = []
    for hour, item in sorted(hourly.items()):
        total = int(item["amount_gwei"])
        shares = [amount / total for amount in item["credential_amount"].values()]
        hourly_rows.append(
            {
                "source_hour_start": hour,
                "deposit_event_count": int(item["event_count"]),
                "deposit_amount_gwei": total,
                "deposit_eth": total / 1e9,
                "deposit_unique_pubkeys": len(item["pubkeys"]),
                "deposit_unique_credentials": len(item["credentials"]),
                "deposit_max_amount_eth": int(item["max_amount_gwei"]) / 1e9,
                "deposit_credential_amount_hhi": sum(share * share for share in shares),
            }
        )

    total_gwei = sum(amounts)
    summary = {
        "day": day.isoformat(),
        "url": url_for(day),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "rows": table.num_rows,
        "min_slot": min(slots),
        "max_slot": max(slots),
        "min_slot_time": min(timestamps).isoformat(),
        "max_slot_time": max(timestamps).isoformat(),
        "total_gwei": total_gwei,
        "total_eth": total_gwei / 1e9,
        "median_amount_eth": sorted(amounts)[len(amounts) // 2] / 1e9,
        "max_amount_eth": max(amounts) / 1e9,
        "unique_pubkeys": len(set(pubkeys)),
        "unique_credentials": len(set(credentials)),
        "hour_count": len(hourly_rows),
        "validation": "PASS",
    }
    return summary, hourly_rows, set(event_keys), set(pubkeys), set(credentials)


def assert_daily_continuity(rows: list[dict[str, Any]]) -> None:
    if len(rows) != 264:
        raise ValueError(f"expected 264 deposit partitions, found {len(rows)}")
    expected = START
    for item in rows:
        observed = date.fromisoformat(item["day"])
        if observed != expected:
            raise ValueError(f"deposit daily gap: expected {expected}, got {observed}")
        expected += timedelta(days=1)
    if expected - timedelta(days=1) != END:
        raise ValueError("deposit chronology did not reach end date")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--principal-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-days", type=int, default=16)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    work = args.output / "deposit_files"
    work.mkdir(parents=True, exist_ok=True)

    requested = list(days(START, END))
    daily_rows: list[dict[str, Any]] = []
    deposit_hours: list[dict[str, Any]] = []
    event_keys: set[str] = set()
    pubkeys: set[str] = set()
    credentials: set[str] = set()

    for offset in range(0, len(requested), args.batch_days):
        batch = requested[offset : offset + args.batch_days]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [
                pool.submit(download, day, work / f"{day.isoformat()}.parquet")
                for day in batch
            ]
            downloaded = [future.result() for future in futures]
        for day, path in sorted(downloaded):
            summary, hours, keys, day_pubkeys, day_credentials = inspect_day(day, path)
            overlap = event_keys.intersection(keys)
            if overlap:
                raise ValueError("deposit event key repeated across partitions")
            event_keys.update(keys)
            pubkeys.update(day_pubkeys)
            credentials.update(day_credentials)
            daily_rows.append(summary)
            deposit_hours.extend(hours)
            path.unlink()
        print(
            json.dumps(
                {
                    "processed_days": len(daily_rows),
                    "latest_day": daily_rows[-1]["day"],
                    "deposit_rows": sum(item["rows"] for item in daily_rows),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    assert_daily_continuity(daily_rows)
    deposit_table = pa.Table.from_pylist(deposit_hours)
    deposit_frame = deposit_table.to_pandas()
    deposit_frame["source_hour_start"] = deposit_frame["source_hour_start"].astype("datetime64[us, UTC]")

    principal = pq.read_table(args.principal_source).to_pandas()
    principal["source_hour_start"] = principal["source_hour_start"].astype("datetime64[us, UTC]")
    principal["available_at"] = principal["available_at"].astype("datetime64[us, UTC]")
    required_principal = {
        "source_hour_start",
        "available_at",
        "principal_amount_eth",
        "principal_event_count",
        "principal_unique_validators",
        "principal_unique_addresses",
        "principal_max_amount_eth",
        "principal_address_amount_hhi",
    }
    missing_principal = sorted(required_principal - set(principal.columns))
    if missing_principal:
        raise ValueError(f"principal dependency missing columns: {missing_principal}")

    merged = principal.merge(deposit_frame, on="source_hour_start", how="left")
    deposit_columns = [column for column in merged.columns if column.startswith("deposit_")]
    merged[deposit_columns] = merged[deposit_columns].fillna(0)
    merged["principal_release_eth"] = merged["principal_amount_eth"]
    merged["net_locked_eth"] = merged["deposit_eth"] - merged["principal_release_eth"]
    merged["source_hour_end"] = merged["source_hour_start"] + timedelta(hours=1)
    expected_available = merged["source_hour_end"] + timedelta(seconds=SOURCE_DELAY_SECONDS)
    if not (merged["available_at"] == expected_available).all():
        raise ValueError("principal and deposit source availability mismatch")
    merged["net_abs_eth"] = merged["net_locked_eth"].abs()
    merged["deposit_to_release_ratio"] = merged["deposit_eth"] / merged["principal_release_eth"].replace(0, float("nan"))
    merged["deposit_amount_share"] = merged["deposit_eth"] / (
        merged["deposit_eth"] + merged["principal_release_eth"]
    ).replace(0, float("nan"))

    if len(merged) != 6314:
        raise ValueError(f"expected 6314 merged source hours, found {len(merged)}")
    expected_hour = merged["source_hour_start"].iloc[0]
    for observed in merged["source_hour_start"]:
        if observed != expected_hour:
            raise ValueError(f"net-staking hourly gap at {expected_hour}")
        expected_hour += timedelta(hours=1)

    total_deposit_gwei = sum(item["total_gwei"] for item in daily_rows)
    total_principal_eth = float(merged["principal_release_eth"].sum())
    total_deposit_eth = total_deposit_gwei / 1e9
    total_net_eth = float(merged["net_locked_eth"].sum())
    if abs((total_deposit_eth - total_principal_eth) - total_net_eth) > 1e-6:
        raise ValueError("net-staking amount conservation failed")

    pq.write_table(
        pa.Table.from_pandas(merged, preserve_index=False),
        args.output / "HOURLY_NET_STAKING_SOURCE.parquet",
        compression="zstd",
    )
    pq.write_table(
        pa.Table.from_pylist(daily_rows),
        args.output / "DAILY_DEPOSIT_SOURCE.parquet",
        compression="zstd",
    )
    (args.output / "DEPOSIT_FILE_MANIFEST.json").write_text(
        json.dumps(daily_rows, indent=2, sort_keys=True)
    )
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260730-ETH-NET-STAKING-INVENTORY-CORE-001",
        "result_id": "RES-20260730-ETH-NET-STAKING-SOURCE-001",
        "status": "SOURCE_PASS_NET_STAKING_PRE2024",
        "source_period": [START.isoformat(), END.isoformat()],
        "deposit_daily_partitions": len(daily_rows),
        "deposit_rows": sum(item["rows"] for item in daily_rows),
        "deposit_event_keys_unique": len(event_keys),
        "deposit_total_eth": total_deposit_eth,
        "deposit_unique_pubkeys": len(pubkeys),
        "deposit_unique_credentials": len(credentials),
        "principal_release_total_eth": total_principal_eth,
        "net_locked_total_eth": total_net_eth,
        "hourly_rows": len(merged),
        "hourly_chronology_contiguous": True,
        "source_confirmation_delay_seconds": SOURCE_DELAY_SECONDS,
        "amount_conservation_pass": True,
        "principal_dependency": {
            "workflow_run": 30517717123,
            "artifact_id": 8749615475,
            "artifact_zip_sha256": "001a60aedf845175164fbd14377bc350d698893b742d9fc09b7e51c2f1c01c54",
        },
        "known_official_source_limitation": "canonical_beacon_block_deposit public-file documentation ends 2025-05-14",
        "market_outcomes_opened": False,
        "bybit_data_opened": False,
        "orders_submitted": False,
        "decision": "Source passes for the frozen pre-2024 economic diagnostic only.",
    }
    (args.output / "SOURCE_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True)
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
