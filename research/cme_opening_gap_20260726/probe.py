from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent
PREREG_PATH = ROOT / "preregistration.json"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
NASDAQ = "https://data.nasdaq.com/api/v3/datasets/{dataset}.csv"
BINANCE = "https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/15m/{symbol}-15m-2021-01.zip"
PERIOD1 = 1609459200
PERIOD2 = 1704067200


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def request_bytes(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    allow_error: bool = False,
    attempts: int = 5,
) -> tuple[bytes, dict[str, Any]]:
    errors: list[str] = []
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=(30, 300))
            metadata = {
                "requested_url": response.url,
                "http_status": int(response.status_code),
                "content_type": response.headers.get("Content-Type"),
                "content_length_header": response.headers.get("Content-Length"),
            }
            if response.status_code == 200:
                return response.content, metadata
            if allow_error:
                metadata["error_excerpt"] = response.text[:300]
                return response.content, metadata
            errors.append(f"HTTP {response.status_code}: {response.text[:200]}")
            if response.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(0.5 * 2**attempt, 8.0))
    raise RuntimeError(f"request failed {url}: {' | '.join(errors[-5:])}")


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def parse_yahoo(payload: bytes, expected_symbol: str) -> dict[str, Any]:
    decoded = json.loads(payload)
    chart = decoded.get("chart", {})
    if chart.get("error"):
        raise ValueError(f"Yahoo chart error: {chart['error']}")
    results = chart.get("result") or []
    if len(results) != 1:
        raise ValueError(f"expected one Yahoo result, found {len(results)}")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quote_blocks = (result.get("indicators") or {}).get("quote") or []
    if len(quote_blocks) != 1:
        raise ValueError("Yahoo quote block missing")
    quote_data = quote_blocks[0]
    columns = {name: quote_data.get(name) or [] for name in ("open", "high", "low", "close", "volume")}
    lengths = {len(timestamps), *(len(values) for values in columns.values())}
    if len(lengths) != 1:
        raise ValueError(f"Yahoo array lengths differ: {sorted(lengths)}")
    rows = []
    for index, timestamp in enumerate(timestamps):
        row = {"timestamp": int(timestamp)}
        for name, values in columns.items():
            row[name] = values[index]
        if all(finite(row[name]) for name in ("open", "high", "low", "close")):
            rows.append(row)
    meta = result.get("meta") or {}
    first = rows[0]["timestamp"] if rows else None
    last = rows[-1]["timestamp"] if rows else None
    chronological = all(left["timestamp"] < right["timestamp"] for left, right in zip(rows, rows[1:]))
    years = sorted({time.gmtime(row["timestamp"]).tm_year for row in rows})
    return {
        "expected_symbol": expected_symbol,
        "returned_symbol": meta.get("symbol"),
        "exchange_name": meta.get("exchangeName"),
        "exchange_timezone_name": meta.get("exchangeTimezoneName"),
        "currency": meta.get("currency"),
        "instrument_type": meta.get("instrumentType"),
        "gmtoffset": meta.get("gmtoffset"),
        "raw_timestamp_count": len(timestamps),
        "finite_row_count": len(rows),
        "first_timestamp": first,
        "last_timestamp": last,
        "years_utc": years,
        "strictly_chronological": chronological,
        "null_or_nonfinite_row_count": len(timestamps) - len(rows),
        "sample_rows": rows[:3] + rows[-3:],
        "coverage_pass": (
            len(rows) >= 600
            and chronological
            and {2021, 2022, 2023}.issubset(set(years))
            and (last is None or time.gmtime(last).tm_year <= 2023)
            and meta.get("symbol") == expected_symbol
        ),
    }


def parse_checksum(payload: bytes) -> str:
    text = payload.decode("utf-8-sig").strip()
    token = text.split()[0] if text else ""
    if len(token) != 64 or any(char not in "0123456789abcdefABCDEF" for char in token):
        raise ValueError(f"invalid checksum payload: {text[:120]!r}")
    return token.lower()


def inspect_zip_csv(payload: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV, found {names}")
        raw = archive.read(names[0])
    lines = raw.splitlines()
    if not lines:
        raise ValueError("empty CSV archive")
    header_or_first = lines[0].decode("utf-8-sig", errors="replace").split(",")
    header_present = header_or_first[0].strip().lower() in {"open_time", "opentime"}
    data_lines = lines[1:] if header_present else lines
    first_columns = data_lines[0].decode("utf-8", errors="replace").split(",") if data_lines else []
    return {
        "csv_name": names[0],
        "uncompressed_bytes": len(raw),
        "line_count": len(lines),
        "header_present": header_present,
        "first_data_column_count": len(first_columns),
        "first_data_line_sha256": sha256(data_lines[0]) if data_lines else None,
        "schema_pass": len(first_columns) >= 12 and len(data_lines) > 1000,
    }


def run(output: Path) -> dict[str, Any]:
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    yahoo_passes: list[bool] = []
    binance_passes: list[bool] = []

    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "Mozilla/5.0 SMC-ICT-2-LIVE-CME-gap-probe/1.0",
            "Accept": "application/json,text/plain,*/*",
        })
        for symbol in ("BTC=F", "ETH=F"):
            url = YAHOO.format(symbol=quote(symbol, safe=""))
            params = {
                "period1": PERIOD1,
                "period2": PERIOD2,
                "interval": "1d",
                "events": "history",
                "includeAdjustedClose": "true",
            }
            payload, transport = request_bytes(session, url, params=params)
            raw_path = output / "raw" / f"yahoo_{symbol.replace('=', '_')}.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(payload)
            parsed = parse_yahoo(payload, symbol)
            record = {
                "source": "Yahoo Finance chart",
                "role": "CME continuous-front daily OHLCV fatal-screen source probe",
                "symbol": symbol,
                **transport,
                "retrieved_bytes": len(payload),
                "raw_sha256": sha256(payload),
                **parsed,
            }
            yahoo_passes.append(bool(record["coverage_pass"]))
            records.append(record)
            print(json.dumps({
                "source": "yahoo",
                "symbol": symbol,
                "rows": record["finite_row_count"],
                "years": record["years_utc"],
                "coverage_pass": record["coverage_pass"],
            }, sort_keys=True), flush=True)

        for dataset in ("CHRIS/CME_BTC1", "CHRIS/CME_ETH1"):
            url = NASDAQ.format(dataset=dataset)
            params = {
                "start_date": "2021-01-01",
                "end_date": "2023-12-31",
                "order": "asc",
            }
            payload, transport = request_bytes(session, url, params=params, allow_error=True)
            record = {
                "source": "Nasdaq Data Link",
                "role": "optional continuous-futures cross-check",
                "dataset": dataset,
                **transport,
                "retrieved_bytes": len(payload),
                "raw_sha256": sha256(payload),
                "required_for_probe_pass": False,
            }
            if transport["http_status"] == 200:
                text = payload.decode("utf-8-sig", errors="replace")
                lines = [line for line in text.splitlines() if line.strip()]
                header = lines[0].split(",") if lines else []
                record.update({
                    "line_count": len(lines),
                    "header": header,
                    "schema_has_date_open": "Date" in header and "Open" in header,
                    "sample_first": lines[1] if len(lines) > 1 else None,
                    "sample_last": lines[-1] if len(lines) > 1 else None,
                })
            records.append(record)
            print(json.dumps({
                "source": "nasdaq",
                "dataset": dataset,
                "http_status": record["http_status"],
                "line_count": record.get("line_count"),
            }, sort_keys=True), flush=True)

        for symbol in ("BTCUSDT", "ETHUSDT"):
            url = BINANCE.format(symbol=symbol)
            payload, transport = request_bytes(session, url)
            checksum_payload, checksum_transport = request_bytes(session, url + ".CHECKSUM")
            expected = parse_checksum(checksum_payload)
            actual = sha256(payload)
            inspected = inspect_zip_csv(payload)
            record = {
                "source": "Binance Vision",
                "role": "official USD-M 15-minute execution-proxy source probe",
                "symbol": symbol,
                **transport,
                "retrieved_bytes": len(payload),
                "raw_sha256": actual,
                "checksum_url": checksum_transport["requested_url"],
                "checksum_http_status": checksum_transport["http_status"],
                "checksum_payload_sha256": sha256(checksum_payload),
                "checksum_expected_sha256": expected,
                "checksum_verified": actual == expected,
                **inspected,
            }
            record["coverage_pass"] = bool(record["checksum_verified"] and record["schema_pass"])
            binance_passes.append(record["coverage_pass"])
            records.append(record)
            print(json.dumps({
                "source": "binance",
                "symbol": symbol,
                "checksum_verified": record["checksum_verified"],
                "line_count": record["line_count"],
                "schema_pass": record["schema_pass"],
            }, sort_keys=True), flush=True)

    probe_pass = all(yahoo_passes) and all(binance_passes)
    result = {
        "schema_version": 1,
        "claim_id": prereg["claim_id"],
        "probe_id": prereg["probe_id"],
        "stage": "SOURCE_PROBE_ONLY_NO_PNL",
        "probe_pass": probe_pass,
        "yahoo_cme_daily_pass": all(yahoo_passes),
        "binance_execution_archive_pass": all(binance_passes),
        "nasdaq_cross_check_required": False,
        "strategy_pnl_opened": False,
        "candidate_metrics_opened": False,
        "fit_opened": False,
        "development_opened": False,
        "confirmation_opened": False,
        "official_2024_opened": False,
        "official_2025_opened": False,
        "official_2026_opened": False,
        "orders_submitted": False,
        "paper_or_testnet_started": False,
        "records": records,
        "next_action_if_pass": "Run the already-preregistered 432-policy 2021 fit and 2022 development screen; request 2023 execution archives only for fit/development survivors.",
        "next_action_if_fail": "Close or replace the CME daily data source before any strategy PnL; do not approximate the institutional gap from 24/7 crypto alone.",
    }
    write_json(output / "SOURCE_PROBE.json", result)
    (output / "SOURCE_PROBE.sha256").write_text(
        f"{sha256((output / 'SOURCE_PROBE.json').read_bytes())}  SOURCE_PROBE.json\n",
        encoding="utf-8",
    )
    print("CME_OPENING_GAP_SOURCE_PROBE=" + json.dumps({
        "probe_pass": probe_pass,
        "yahoo_cme_daily_pass": all(yahoo_passes),
        "binance_execution_archive_pass": all(binance_passes),
    }, sort_keys=True), flush=True)
    return result


def self_test() -> None:
    timestamps = [1609545600, 1609632000, 1640995200, 1672531200]
    quote_data = {
        "open": [1.0, 2.0, 3.0, 4.0],
        "high": [2.0, 3.0, 4.0, 5.0],
        "low": [0.5, 1.5, 2.5, 3.5],
        "close": [1.5, 2.5, 3.5, 4.5],
        "volume": [10, 20, 30, 40],
    }
    payload = json.dumps({
        "chart": {
            "result": [{
                "meta": {
                    "symbol": "BTC=F",
                    "exchangeName": "CME",
                    "exchangeTimezoneName": "America/Chicago",
                    "currency": "USD",
                    "instrumentType": "FUTURE",
                    "gmtoffset": -21600,
                },
                "timestamp": timestamps,
                "indicators": {"quote": [quote_data]},
            }],
            "error": None,
        }
    }).encode()
    parsed = parse_yahoo(payload, "BTC=F")
    assert parsed["finite_row_count"] == 4
    assert parsed["strictly_chronological"] is True

    csv_bytes = b"open_time,open,high,low,close,volume,close_time,quote_volume,trades,taker_buy_base_volume,taker_buy_quote_volume,ignore\n" + b"\n".join(
        [f"{i},1,2,0.5,1.5,10,{i+1},15,2,5,7,0".encode() for i in range(1500)]
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sample.csv", csv_bytes)
    inspected = inspect_zip_csv(buffer.getvalue())
    assert inspected["schema_pass"] is True
    assert parse_checksum((sha256(buffer.getvalue()) + "  sample.zip\n").encode()) == sha256(buffer.getvalue())
    print("SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
