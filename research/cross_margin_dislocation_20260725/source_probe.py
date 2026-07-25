from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

BASES = (
    "https://data.binance.vision",
    "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision",
)
ROUTES = {
    "BTC": {"cm": "BTCUSD_PERP", "um": "BTCUSDT"},
    "ETH": {"cm": "ETHUSD_PERP", "um": "ETHUSDT"},
}


@dataclass(frozen=True, slots=True)
class Record:
    asset: str
    market: str
    symbol: str
    data_type: str
    source_path: str | None
    source_url: str | None
    checksum_url: str | None
    http_status: int
    checksum_verified: bool
    sha256: str | None
    bytes: int
    csv_name: str | None
    columns: list[str]
    width: int
    sample_rows: int
    first_timestamp_candidate: int | None
    last_timestamp_candidate: int | None
    error: str | None


def candidates(market: str, symbol: str, data_type: str, date: str) -> list[str]:
    month = date[:7]
    daily = f"{symbol}-{data_type}-{date}.zip"
    monthly = f"{symbol}-{data_type}-{month}.zip"
    return [
        f"/data/futures/{market}/daily/{data_type}/{symbol}/{daily}",
        f"/data/futures/{market}/monthly/{data_type}/{symbol}/{monthly}",
    ]


def get(session: requests.Session, path: str) -> tuple[bytes | None, str | None, int, str | None]:
    errors: list[str] = []
    final_status = 0
    for base in BASES:
        for attempt in range(4):
            url = base + path
            try:
                response = session.get(url, timeout=(30, 180))
                final_status = response.status_code
                if response.status_code == 200:
                    return response.content, url, response.status_code, None
                errors.append(f"{url}: HTTP {response.status_code}")
                if response.status_code in (400, 401, 403, 404):
                    break
            except requests.RequestException as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
            time.sleep(min(2**attempt, 8))
    return None, None, final_status, "; ".join(errors[-8:])


def parse_checksum(payload: bytes) -> str:
    value = payload.decode("utf-8-sig").strip().split()[0].lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"invalid checksum payload: {value!r}")
    return value


def numeric(value: str) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def inspect_zip(payload: bytes) -> tuple[str, list[str], int, int, int | None, int | None]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV, got {names}")
        raw = archive.read(names[0])
    lines = raw.decode("utf-8-sig", errors="strict").splitlines()
    if not lines:
        raise ValueError("empty CSV")
    first = next(csv.reader([lines[0]]))
    header = any(not item.strip().lstrip("-").replace(".", "", 1).isdigit() for item in first)
    columns = [item.strip() for item in first] if header else [f"column_{index}" for index in range(len(first))]
    data_lines = lines[1:] if header else lines
    sample = data_lines[:1000]
    parsed = [next(csv.reader([line])) for line in sample if line.strip()]
    if not parsed:
        raise ValueError("no data rows")
    width = len(parsed[0])
    if any(len(row) != width for row in parsed):
        raise ValueError("inconsistent CSV width")
    timestamp_values: list[int] = []
    timestamp_names = [
        "transact_time", "transaction_time", "event_time", "time", "timestamp", "T", "E"
    ]
    if header:
        indexes = [columns.index(name) for name in timestamp_names if name in columns]
    else:
        indexes = list(range(width))
    for row in parsed:
        values = [numeric(row[index]) for index in indexes if index < len(row)]
        values = [value for value in values if value is not None and value >= 10**11]
        if values:
            timestamp_values.append(min(values))
    return names[0], columns, width, len(parsed), (min(timestamp_values) if timestamp_values else None), (max(timestamp_values) if timestamp_values else None)


def probe_one(session: requests.Session, asset: str, market: str, symbol: str, data_type: str, date: str) -> Record:
    errors: list[str] = []
    last_status = 0
    for path in candidates(market, symbol, data_type, date):
        payload, source_url, status, error = get(session, path)
        last_status = status
        if payload is None:
            errors.append(error or f"missing {path}")
            continue
        checksum_payload, checksum_url, checksum_status, checksum_error = get(session, path + ".CHECKSUM")
        if checksum_payload is None:
            errors.append(checksum_error or f"checksum missing {path}")
            continue
        actual = hashlib.sha256(payload).hexdigest()
        try:
            expected = parse_checksum(checksum_payload)
            verified = actual == expected
            if not verified:
                raise ValueError(f"checksum mismatch expected={expected} actual={actual}")
            csv_name, columns, width, sample_rows, first_ts, last_ts = inspect_zip(payload)
            return Record(asset, market, symbol, data_type, path, source_url, checksum_url, status, True, actual, len(payload), csv_name, columns, width, sample_rows, first_ts, last_ts, None)
        except (ValueError, UnicodeError, zipfile.BadZipFile, csv.Error) as exc:
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
    return Record(asset, market, symbol, data_type, None, None, None, last_status, False, None, 0, None, [], 0, 0, None, None, "; ".join(errors[-8:]))


def run(output: Path, date: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    records: list[Record] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-margin-probe/1.0"
        for asset, route in ROUTES.items():
            for market, symbol in route.items():
                for data_type in ("aggTrades", "bookTicker", "klines"):
                    item = probe_one(session, asset, market, symbol, data_type, date)
                    records.append(item)
                    print(json.dumps(asdict(item), sort_keys=True), flush=True)
    required = [
        item for item in records
        if item.data_type in ("aggTrades", "bookTicker")
    ]
    usable = all(
        item.checksum_verified
        and item.bytes > 0
        and item.width >= 5
        and item.sample_rows > 0
        and item.first_timestamp_candidate is not None
        for item in required
    )
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-2120-CROSS-MARGIN-001",
        "date": date,
        "records": [asdict(item) for item in records],
        "all_required_tick_and_bbo_sources_usable": usable,
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
    raw = b"agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n1,30000,0.1,1,1,1688169600000,true\n"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sample.csv", raw)
    name, columns, width, rows, first_ts, last_ts = inspect_zip(stream.getvalue())
    assert name == "sample.csv" and width == 7 and rows == 1
    assert first_ts == last_ts == 1688169600000
    digest = hashlib.sha256(b"abc").hexdigest()
    assert parse_checksum(f"{digest}  file.zip\n".encode()) == digest
    print("cross-margin source probe self-test passed")


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
    return 0 if result["all_required_tick_and_bbo_sources_usable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
