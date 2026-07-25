from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import requests

BASE = "https://datasets.tardis.dev/v1"
VENUES = ("binance-futures", "bybit")
DATA_TYPES = ("trades", "quotes")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
REQUIRED = {
    "trades": {"exchange", "symbol", "timestamp", "local_timestamp", "id", "side", "price", "amount"},
    "quotes": {"exchange", "symbol", "timestamp", "local_timestamp", "ask_price", "ask_amount", "bid_price", "bid_amount"},
}


@dataclass(frozen=True, slots=True)
class ProbeRecord:
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
    first_timestamp: int | None
    last_timestamp: int | None
    monotonic_timestamp: bool
    timestamp_unit: str | None
    required_columns_present: bool
    gzip_valid: bool
    error: str | None


def canonical_url(venue: str, data_type: str, symbol: str, date: str) -> str:
    year, month, day = date.split("-")
    return f"{BASE}/{venue}/{data_type}/{year}/{month}/{day}/{symbol}.csv.gz"


def infer_timestamp_unit(value: int) -> str:
    magnitude = abs(int(value))
    if magnitude >= 10**17:
        return "ns"
    if magnitude >= 10**14:
        return "us"
    if magnitude >= 10**11:
        return "ms"
    return "s"


def fetch(session: requests.Session, url: str, attempts: int = 5) -> tuple[int, bytes, str | None]:
    errors: list[str] = []
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=(30, 300))
            if response.status_code == 200:
                return response.status_code, response.content, None
            errors.append(f"HTTP {response.status_code}")
            if response.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(2**attempt, 16))
    return 0, b"", "; ".join(errors[-5:]) or "download failed"


def inspect_payload(payload: bytes, required: set[str]) -> tuple[list[str], int, int | None, int | None, bool, str | None]:
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        columns = list(reader.fieldnames or [])
        missing = sorted(required.difference(columns))
        if missing:
            raise ValueError(f"missing required columns: {missing}; got={columns}")
        count = 0
        first: int | None = None
        last: int | None = None
        monotonic = True
        previous: int | None = None
        for row in reader:
            raw = row.get("timestamp")
            if raw is None or raw == "":
                raise ValueError(f"empty timestamp at row {count + 2}")
            timestamp = int(raw)
            if first is None:
                first = timestamp
            if previous is not None and timestamp < previous:
                monotonic = False
            previous = timestamp
            last = timestamp
            count += 1
        if count == 0:
            raise ValueError("empty normalized CSV")
        return columns, count, first, last, monotonic, None


def probe_one(session: requests.Session, venue: str, data_type: str, symbol: str, date: str) -> ProbeRecord:
    url = canonical_url(venue, data_type, symbol, date)
    status, payload, fetch_error = fetch(session, url)
    if not payload:
        return ProbeRecord(venue, data_type, symbol, date, url, status, 0, None, [], 0, None, None, False, None, False, False, fetch_error)
    digest = hashlib.sha256(payload).hexdigest()
    try:
        columns, count, first, last, monotonic, _ = inspect_payload(payload, REQUIRED[data_type])
        unit = infer_timestamp_unit(first) if first is not None else None
        return ProbeRecord(venue, data_type, symbol, date, url, status, len(payload), digest, columns, count, first, last, monotonic, unit, True, True, None)
    except (OSError, EOFError, UnicodeError, ValueError, csv.Error) as exc:
        return ProbeRecord(venue, data_type, symbol, date, url, status, len(payload), digest, [], 0, None, None, False, None, False, False, f"{type(exc).__name__}: {exc}")


def run_probe(output: Path, date: str, venues: Iterable[str] = VENUES, symbols: Iterable[str] = SYMBOLS) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    records: list[ProbeRecord] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-venue-probe/1.0"
        for venue in venues:
            for data_type in DATA_TYPES:
                for symbol in symbols:
                    record = probe_one(session, venue, data_type, symbol, date)
                    records.append(record)
                    print(json.dumps(asdict(record), sort_keys=True), flush=True)
    all_usable = all(
        record.http_status == 200
        and record.gzip_valid
        and record.required_columns_present
        and record.row_count > 0
        and record.monotonic_timestamp
        for record in records
    )
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-1850-XVENUE-001",
        "date": date,
        "records": [asdict(record) for record in records],
        "all_required_sources_usable": all_usable,
        "strategy_or_pnl_computed": False,
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
    }
    path = output / "SOURCE_PROBE.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "SOURCE_PROBE.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8"
    )
    return result


def self_test() -> None:
    rows = [
        {
            "exchange": "bybit",
            "symbol": "BTCUSDT",
            "timestamp": "1688169600000000",
            "local_timestamp": "1688169600000100",
            "id": "1",
            "side": "buy",
            "price": "30000",
            "amount": "0.1",
        },
        {
            "exchange": "bybit",
            "symbol": "BTCUSDT",
            "timestamp": "1688169600001000",
            "local_timestamp": "1688169600001100",
            "id": "2",
            "side": "sell",
            "price": "29999.5",
            "amount": "0.2",
        },
    ]
    raw = io.StringIO()
    writer = csv.DictWriter(raw, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    payload = gzip.compress(raw.getvalue().encode())
    columns, count, first, last, monotonic, error = inspect_payload(payload, REQUIRED["trades"])
    assert count == 2 and first < last and monotonic and error is None
    assert infer_timestamp_unit(first) == "us"
    assert REQUIRED["trades"].issubset(columns)
    bad = gzip.compress(b"timestamp,price\n1,1\n")
    try:
        inspect_payload(bad, REQUIRED["trades"])
    except ValueError:
        pass
    else:
        raise AssertionError("missing schema did not fail closed")
    print("source-probe self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--date", default="2023-07-01")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    result = run_probe(args.output, args.date)
    return 0 if result["all_required_sources_usable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
