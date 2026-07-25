from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import requests

BASE = "https://data.binance.vision/data/futures/um"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT")
DATA_TYPES = ("aggTrades", "klines", "markPriceKlines", "fundingRate")


@dataclass(frozen=True, slots=True)
class ProbeRecord:
    symbol: str
    data_type: str
    partition: str
    canonical_url: str
    checksum_url: str
    http_status: int
    checksum_http_status: int
    bytes: int
    sha256: str | None
    expected_sha256: str | None
    checksum_match: bool
    zip_valid: bool
    member_name: str | None
    columns: list[str]
    row_count: int
    timestamp_column: str | None
    first_timestamp_ms: int | None
    last_timestamp_ms: int | None
    timestamp_monotonic: bool
    minimum_width: int
    maximum_width: int
    error: str | None


def normalize_timestamp_ms(raw: str) -> int:
    value = int(float(raw))
    if value >= 10**17:
        return value // 1_000_000
    if value >= 10**14:
        return value // 1_000
    if value >= 10**11:
        return value
    return value * 1_000


def archive_urls(symbol: str, data_type: str, date: str) -> tuple[str, str, str]:
    if data_type == "aggTrades":
        name = f"{symbol}-aggTrades-{date}.zip"
        url = f"{BASE}/daily/aggTrades/{symbol}/{name}"
        partition = date
    elif data_type == "klines":
        name = f"{symbol}-1m-{date}.zip"
        url = f"{BASE}/daily/klines/{symbol}/1m/{name}"
        partition = date
    elif data_type == "markPriceKlines":
        name = f"{symbol}-1m-{date}.zip"
        url = f"{BASE}/daily/markPriceKlines/{symbol}/1m/{name}"
        partition = date
    elif data_type == "fundingRate":
        month = date[:7]
        name = f"{symbol}-fundingRate-{month}.zip"
        url = f"{BASE}/monthly/fundingRate/{symbol}/{name}"
        partition = month
    else:
        raise ValueError(f"unsupported data type: {data_type}")
    return url, f"{url}.CHECKSUM", partition


def _download(
    session: requests.Session,
    url: str,
    target: Path,
    *,
    attempts: int = 4,
) -> tuple[int, bytes, str | None]:
    if target.exists() and target.stat().st_size > 0:
        payload = target.read_bytes()
        return 200, payload, None
    errors: list[str] = []
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=(30, 300))
            status = int(response.status_code)
            if status == 200:
                target.write_bytes(response.content)
                return status, response.content, None
            errors.append(f"HTTP {status}")
            if status in (400, 401, 403, 404):
                return status, b"", errors[-1]
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(2**attempt, 8))
    return 0, b"", "; ".join(errors[-4:]) or "download failed"


def parse_expected_checksum(payload: bytes) -> str | None:
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    token = text.split()[0].lower()
    if len(token) != 64 or any(character not in "0123456789abcdef" for character in token):
        return None
    return token


def _is_header(row: list[str]) -> bool:
    if not row:
        return False
    try:
        float(row[0])
    except (TypeError, ValueError):
        return True
    return False


def _timestamp_index(data_type: str, columns: list[str], header: bool) -> tuple[int, str]:
    if not header:
        if data_type == "aggTrades":
            return 5, "c5"
        return 0, "c0"
    normalized = {name.strip().lower(): index for index, name in enumerate(columns)}
    candidates = (
        "transact_time",
        "timestamp",
        "time",
        "open_time",
        "calc_time",
        "funding_time",
        "fundingtime",
    )
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate], columns[normalized[candidate]]
    if data_type == "aggTrades" and len(columns) > 5:
        return 5, columns[5]
    return 0, columns[0]


def inspect_zip(path: Path, data_type: str) -> dict:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        if len(members) != 1:
            raise ValueError(f"expected one CSV member, got {members}")
        member = members[0]
        with archive.open(member, "r") as raw:
            text = (line.decode("utf-8-sig", errors="strict") for line in raw)
            reader = csv.reader(text)
            first = next(reader, None)
            if first is None:
                raise ValueError("empty CSV member")
            header = _is_header(first)
            columns = [item.strip() for item in first] if header else [f"c{index}" for index in range(len(first))]
            timestamp_index, timestamp_name = _timestamp_index(data_type, columns, header)
            rows: Iterable[list[str]] = reader if header else _prepend(first, reader)
            count = 0
            first_timestamp: int | None = None
            last_timestamp: int | None = None
            previous: int | None = None
            monotonic = True
            minimum_width = math.inf
            maximum_width = 0
            for row in rows:
                if not row or all(not item.strip() for item in row):
                    continue
                width = len(row)
                minimum_width = min(minimum_width, width)
                maximum_width = max(maximum_width, width)
                if timestamp_index >= width:
                    raise ValueError(f"timestamp column {timestamp_index} outside row width {width}")
                timestamp = normalize_timestamp_ms(row[timestamp_index])
                if first_timestamp is None:
                    first_timestamp = timestamp
                if previous is not None and timestamp < previous:
                    monotonic = False
                previous = timestamp
                last_timestamp = timestamp
                count += 1
            if count == 0:
                raise ValueError("no data rows")
            return {
                "member_name": member,
                "columns": columns,
                "row_count": count,
                "timestamp_column": timestamp_name,
                "first_timestamp_ms": first_timestamp,
                "last_timestamp_ms": last_timestamp,
                "timestamp_monotonic": monotonic,
                "minimum_width": int(minimum_width),
                "maximum_width": int(maximum_width),
            }


def _prepend(first: list[str], rows: Iterable[list[str]]) -> Iterable[list[str]]:
    yield first
    yield from rows


def probe_one(
    session: requests.Session,
    cache: Path,
    symbol: str,
    data_type: str,
    date: str,
) -> ProbeRecord:
    url, checksum_url, partition = archive_urls(symbol, data_type, date)
    archive_target = cache / data_type / symbol / Path(url).name
    checksum_target = cache / data_type / symbol / Path(checksum_url).name
    archive_status, archive_payload, archive_error = _download(session, url, archive_target)
    checksum_status, checksum_payload, checksum_error = _download(session, checksum_url, checksum_target)
    digest = hashlib.sha256(archive_payload).hexdigest() if archive_payload else None
    expected = parse_expected_checksum(checksum_payload) if checksum_payload else None
    checksum_match = digest is not None and expected is not None and digest == expected
    base = {
        "symbol": symbol,
        "data_type": data_type,
        "partition": partition,
        "canonical_url": url,
        "checksum_url": checksum_url,
        "http_status": archive_status,
        "checksum_http_status": checksum_status,
        "bytes": len(archive_payload),
        "sha256": digest,
        "expected_sha256": expected,
        "checksum_match": checksum_match,
    }
    if archive_status != 200 or checksum_status != 200 or not checksum_match:
        error = "; ".join(item for item in (archive_error, checksum_error, "checksum mismatch" if archive_payload else None) if item)
        return ProbeRecord(**base, zip_valid=False, member_name=None, columns=[], row_count=0,
                           timestamp_column=None, first_timestamp_ms=None, last_timestamp_ms=None,
                           timestamp_monotonic=False, minimum_width=0, maximum_width=0,
                           error=error or "source unavailable")
    try:
        inspected = inspect_zip(archive_target, data_type)
        return ProbeRecord(**base, zip_valid=True, error=None, **inspected)
    except (OSError, UnicodeError, ValueError, csv.Error, zipfile.BadZipFile) as exc:
        return ProbeRecord(**base, zip_valid=False, member_name=None, columns=[], row_count=0,
                           timestamp_column=None, first_timestamp_ms=None, last_timestamp_ms=None,
                           timestamp_monotonic=False, minimum_width=0, maximum_width=0,
                           error=f"{type(exc).__name__}: {exc}")


def run(output: Path, cache: Path, date: str, symbols: tuple[str, ...] = SYMBOLS) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    records: list[ProbeRecord] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-quarter-hour-source-probe/1.0"
        for symbol in symbols:
            for data_type in DATA_TYPES:
                record = probe_one(session, cache, symbol, data_type, date)
                records.append(record)
                print(json.dumps(asdict(record), sort_keys=True), flush=True)
    usable = all(
        record.http_status == 200
        and record.checksum_http_status == 200
        and record.checksum_match
        and record.zip_valid
        and record.row_count > 0
        and record.timestamp_monotonic
        and record.error is None
        for record in records
    )
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-0240-QHOUR-001",
        "stage": "OFFICIAL_SOURCE_PROBE",
        "date": date,
        "symbols": list(symbols),
        "data_types": list(DATA_TYPES),
        "records": [asdict(record) for record in records],
        "all_required_sources_usable": usable,
        "strategy_or_pnl_computed": False,
        "pilot_opened": False,
        "development_opened": False,
        "selection_opened": False,
        "validation_opened": False,
        "2025_2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
    }
    path = output / "SOURCE_PROBE.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "SOURCE_PROBE.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
        encoding="utf-8",
    )
    return result


def self_test(tmp: Path) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    archive = tmp / "synthetic.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(
            "synthetic.csv",
            "1,100,2,1,1,1640995200000,false\n2,101,3,2,2,1640995200100,true\n",
        )
    inspected = inspect_zip(archive, "aggTrades")
    assert inspected["row_count"] == 2
    assert inspected["first_timestamp_ms"] == 1_640_995_200_000
    assert inspected["last_timestamp_ms"] == 1_640_995_200_100
    assert inspected["timestamp_monotonic"] is True
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert parse_expected_checksum(f"{digest}  synthetic.zip\n".encode()) == digest
    print("quarter-hour source probe self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--date", default="2022-01-01")
    parser.add_argument("--symbols", nargs="*", default=list(SYMBOLS))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test(args.output)
        return 0
    result = run(args.output, args.cache, args.date, tuple(args.symbols))
    print(json.dumps({
        "stage": result["stage"],
        "all_required_sources_usable": result["all_required_sources_usable"],
        "strategy_or_pnl_computed": False,
    }, indent=2))
    return 0 if result["all_required_sources_usable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
