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

import numpy as np
import requests

BASE = "https://datasets.tardis.dev/v1"
ROUTES = {
    "BTC": {"coin_m": ("binance-delivery", "BTCUSD_PERP"), "usd_m": ("binance-futures", "BTCUSDT")},
    "ETH": {"coin_m": ("binance-delivery", "ETHUSD_PERP"), "usd_m": ("binance-futures", "ETHUSDT")},
}
DATA_TYPES = ("trades", "quotes")
REQUIRED = {
    "trades": {"exchange", "symbol", "timestamp", "local_timestamp", "id", "side", "price", "amount"},
    "quotes": {"exchange", "symbol", "timestamp", "local_timestamp", "ask_price", "ask_amount", "bid_price", "bid_amount"},
}


@dataclass(frozen=True, slots=True)
class Record:
    asset: str
    leg: str
    venue: str
    symbol: str
    data_type: str
    date: str
    canonical_url: str
    http_status: int
    bytes: int
    sha256: str | None
    columns: list[str]
    row_count: int
    first_exchange_ms: int | None
    last_exchange_ms: int | None
    first_local_ms: int | None
    last_local_ms: int | None
    local_monotonic: bool
    exchange_monotonic: bool
    negative_latency_count: int
    latency_ms_median: float | None
    latency_ms_p95: float | None
    gzip_valid: bool
    schema_valid: bool
    error: str | None


def canonical_url(venue: str, data_type: str, symbol: str, date: str) -> str:
    year, month, day = date.split("-")
    return f"{BASE}/{venue}/{data_type}/{year}/{month}/{day}/{symbol}.csv.gz"


def to_ms(raw: str) -> int:
    value = int(raw)
    if value >= 10**17:
        return value // 1_000_000
    if value >= 10**14:
        return value // 1_000
    if value >= 10**11:
        return value
    return value * 1000


def fetch(session: requests.Session, source: str) -> tuple[int, bytes, str | None]:
    errors: list[str] = []
    for attempt in range(5):
        try:
            response = session.get(source, timeout=(30, 300))
            if response.status_code == 200:
                return response.status_code, response.content, None
            errors.append(f"HTTP {response.status_code}")
            if response.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(2**attempt, 16))
    return 0, b"", "; ".join(errors[-5:]) or "download failed"


def inspect(payload: bytes, required: set[str]) -> dict:
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        columns = list(reader.fieldnames or [])
        missing = sorted(required.difference(columns))
        if missing:
            raise ValueError(f"missing required columns {missing}; got={columns}")
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
            "first_exchange_ms": first_exchange,
            "last_exchange_ms": last_exchange,
            "first_local_ms": first_local,
            "last_local_ms": last_local,
            "local_monotonic": local_monotonic,
            "exchange_monotonic": exchange_monotonic,
            "negative_latency_count": int((values < 0).sum()),
            "latency_ms_median": float(np.median(values)),
            "latency_ms_p95": float(np.quantile(values, 0.95)),
        }


def probe_one(session: requests.Session, asset: str, leg: str, venue: str, symbol: str, data_type: str, date: str) -> Record:
    source = canonical_url(venue, data_type, symbol, date)
    status, payload, error = fetch(session, source)
    if not payload:
        return Record(asset, leg, venue, symbol, data_type, date, source, status, 0, None, [], 0, None, None, None, None, False, False, 0, None, None, False, False, error)
    digest = hashlib.sha256(payload).hexdigest()
    try:
        info = inspect(payload, REQUIRED[data_type])
        local_ok = bool(info["local_monotonic"])
        return Record(
            asset, leg, venue, symbol, data_type, date, source, status, len(payload), digest,
            info["columns"], info["row_count"], info["first_exchange_ms"], info["last_exchange_ms"],
            info["first_local_ms"], info["last_local_ms"], local_ok, info["exchange_monotonic"],
            info["negative_latency_count"], info["latency_ms_median"], info["latency_ms_p95"],
            True, True, (None if local_ok else "local_timestamp is not monotonic"),
        )
    except (OSError, EOFError, UnicodeError, ValueError, csv.Error) as exc:
        return Record(asset, leg, venue, symbol, data_type, date, source, status, len(payload), digest, [], 0, None, None, None, None, False, False, 0, None, None, False, False, f"{type(exc).__name__}: {exc}")


def run(output: Path, date: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    records: list[Record] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-margin-tardis-probe/1.0"
        for asset, route in ROUTES.items():
            for leg, (venue, symbol) in route.items():
                for data_type in DATA_TYPES:
                    item = probe_one(session, asset, leg, venue, symbol, data_type, date)
                    records.append(item)
                    print(json.dumps(asdict(item), sort_keys=True), flush=True)
    usable = all(
        item.http_status == 200
        and item.gzip_valid
        and item.schema_valid
        and item.local_monotonic
        and item.row_count > 0
        and item.error is None
        for item in records
    )
    result = {
        "schema_version": 2,
        "claim_id": "CLM-20260725-2120-CROSS-MARGIN-001",
        "dataset_revision": "TARDIS_PUBLIC_NORMALIZED_SAMPLE_V1",
        "date": date,
        "records": [asdict(item) for item in records],
        "all_required_sources_usable": usable,
        "strategy_or_pnl_computed": False,
        "development_opened": False,
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "champion_eligible": False,
    }
    path = output / "TARDIS_SOURCE_PROBE.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "TARDIS_SOURCE_PROBE.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8"
    )
    return result


def self_test() -> None:
    raw = (
        "exchange,symbol,timestamp,local_timestamp,id,side,price,amount\n"
        "binance-delivery,BTCUSD_PERP,1700000000200000,1700000000300000,1,buy,30000,1\n"
        "binance-delivery,BTCUSD_PERP,1700000000100000,1700000000400000,2,sell,29999,1\n"
    )
    info = inspect(gzip.compress(raw.encode()), REQUIRED["trades"])
    assert info["row_count"] == 2
    assert info["local_monotonic"] is True
    assert info["exchange_monotonic"] is False
    print("cross-margin Tardis source probe self-test passed")


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
