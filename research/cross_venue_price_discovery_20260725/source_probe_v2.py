from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import requests

import source_probe as v1


@dataclass(frozen=True, slots=True)
class ProbeRecordV2:
    venue: str
    data_type: str
    symbol: str
    date: str
    canonical_url: str
    http_status: int
    bytes: int
    sha256: str | None
    columns: list[str]
    row_count: int
    first_exchange_timestamp_ms: int | None
    last_exchange_timestamp_ms: int | None
    first_local_timestamp_ms: int | None
    last_local_timestamp_ms: int | None
    local_timestamp_monotonic: bool
    exchange_timestamp_monotonic: bool
    negative_exchange_to_local_latency_count: int
    exchange_to_local_latency_ms_median: float | None
    exchange_to_local_latency_ms_p95: float | None
    required_columns_present: bool
    gzip_valid: bool
    error: str | None


def to_ms(raw: str) -> int:
    value = int(raw)
    if value >= 10**17:
        return value // 1_000_000
    if value >= 10**14:
        return value // 1_000
    if value >= 10**11:
        return value
    return value * 1000


def inspect_v2(payload: bytes, required: set[str]) -> dict:
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        columns = list(reader.fieldnames or [])
        missing = sorted(required.difference(columns))
        if missing:
            raise ValueError(f"missing required columns: {missing}; got={columns}")
        count = 0
        first_exchange = last_exchange = first_local = last_local = None
        previous_exchange = previous_local = None
        exchange_monotonic = local_monotonic = True
        delays: list[int] = []
        for row in reader:
            exchange = to_ms(row["timestamp"])
            local = to_ms(row["local_timestamp"])
            if first_exchange is None:
                first_exchange, first_local = exchange, local
            if previous_exchange is not None and exchange < previous_exchange:
                exchange_monotonic = False
            if previous_local is not None and local < previous_local:
                local_monotonic = False
            previous_exchange, previous_local = exchange, local
            last_exchange, last_local = exchange, local
            delays.append(local - exchange)
            count += 1
        if count == 0:
            raise ValueError("empty normalized CSV")
        values = np.asarray(delays, dtype=np.int64)
        return {
            "columns": columns,
            "row_count": count,
            "first_exchange_timestamp_ms": first_exchange,
            "last_exchange_timestamp_ms": last_exchange,
            "first_local_timestamp_ms": first_local,
            "last_local_timestamp_ms": last_local,
            "local_timestamp_monotonic": local_monotonic,
            "exchange_timestamp_monotonic": exchange_monotonic,
            "negative_exchange_to_local_latency_count": int((values < 0).sum()),
            "exchange_to_local_latency_ms_median": float(np.median(values)),
            "exchange_to_local_latency_ms_p95": float(np.quantile(values, 0.95)),
        }


def probe_one(session: requests.Session, venue: str, data_type: str, symbol: str, date: str) -> ProbeRecordV2:
    source_url = v1.canonical_url(venue, data_type, symbol, date)
    status, payload, fetch_error = v1.fetch(session, source_url)
    if not payload:
        return ProbeRecordV2(venue, data_type, symbol, date, source_url, status, 0, None, [], 0, None, None, None, None, False, False, 0, None, None, False, False, fetch_error)
    digest = hashlib.sha256(payload).hexdigest()
    try:
        info = inspect_v2(payload, v1.REQUIRED[data_type])
        error = None if info["local_timestamp_monotonic"] else "local_timestamp is not monotonic"
        return ProbeRecordV2(
            venue, data_type, symbol, date, source_url, status, len(payload), digest,
            info["columns"], info["row_count"],
            info["first_exchange_timestamp_ms"], info["last_exchange_timestamp_ms"],
            info["first_local_timestamp_ms"], info["last_local_timestamp_ms"],
            info["local_timestamp_monotonic"], info["exchange_timestamp_monotonic"],
            info["negative_exchange_to_local_latency_count"],
            info["exchange_to_local_latency_ms_median"], info["exchange_to_local_latency_ms_p95"],
            True, True, error,
        )
    except (OSError, EOFError, UnicodeError, ValueError, csv.Error) as exc:
        return ProbeRecordV2(venue, data_type, symbol, date, source_url, status, len(payload), digest, [], 0, None, None, None, None, False, False, 0, None, None, False, False, f"{type(exc).__name__}: {exc}")


def run(output: Path, date: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    records: list[ProbeRecordV2] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-venue-probe-v2/1.0"
        for venue in v1.VENUES:
            for data_type in v1.DATA_TYPES:
                for symbol in v1.SYMBOLS:
                    item = probe_one(session, venue, data_type, symbol, date)
                    records.append(item)
                    print(json.dumps(asdict(item), sort_keys=True), flush=True)
    usable = all(
        item.http_status == 200
        and item.gzip_valid
        and item.required_columns_present
        and item.row_count > 0
        and item.local_timestamp_monotonic
        and item.error is None
        for item in records
    )
    result = {
        "schema_version": 2,
        "claim_id": "CLM-20260725-1850-XVENUE-001",
        "causal_version": 2,
        "availability_clock": "local_timestamp",
        "date": date,
        "records": [asdict(item) for item in records],
        "all_required_sources_usable": usable,
        "strategy_or_pnl_computed": False,
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
    }
    path = output / "SOURCE_PROBE_V2.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "SOURCE_PROBE_V2.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8"
    )
    return result


def self_test() -> None:
    raw = (
        "exchange,symbol,timestamp,local_timestamp,id,side,price,amount\n"
        "bybit,BTCUSDT,2000000,3000000,1,buy,100,1\n"
        "bybit,BTCUSDT,1000000,3100000,2,sell,100,1\n"
    )
    payload = gzip.compress(raw.encode())
    info = inspect_v2(payload, v1.REQUIRED["trades"])
    assert info["local_timestamp_monotonic"] is True
    assert info["exchange_timestamp_monotonic"] is False
    assert info["row_count"] == 2
    print("source probe V2 self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--date", default="2023-07-01")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    result = run(args.output, args.date)
    return 0 if result["all_required_sources_usable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
