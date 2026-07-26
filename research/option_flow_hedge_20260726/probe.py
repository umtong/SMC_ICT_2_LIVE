from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
PREREG_PATH = ROOT / "preregistration.json"
BASE_URL = "https://datasets.tardis.dev/v1"
OPTION_RE = re.compile(r"^(BTC|ETH)-.+-(C|P)$")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_content_range(value: str | None) -> int | None:
    if not value or "/" not in value:
        return None
    total = value.rsplit("/", 1)[-1]
    return int(total) if total.isdigit() else None


def source_url(exchange: str, data_type: str, date: str, symbol: str) -> str:
    year, month, day = date.split("-")
    return f"{BASE_URL}/{exchange}/{data_type}/{year}/{month}/{day}/{symbol}.csv.gz"


def download_prefix(
    session: requests.Session,
    url: str,
    target: Path,
    maximum_bytes: int,
) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    headers = {"Range": f"bytes=0-{maximum_bytes - 1}"}
    with session.get(url, headers=headers, stream=True, timeout=(30, 600)) as response:
        status = response.status_code
        response.raise_for_status()
        content_length = int(response.headers.get("Content-Length", "0") or 0)
        total_bytes = parse_content_range(response.headers.get("Content-Range"))
        if total_bytes is None and status == 200 and content_length:
            total_bytes = content_length
        written = 0
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                remaining = maximum_bytes - written
                if remaining <= 0:
                    break
                payload = chunk[:remaining]
                handle.write(payload)
                written += len(payload)
                if written >= maximum_bytes:
                    break
    complete = total_bytes is not None and written >= total_bytes
    return {
        "http_status": status,
        "content_length_header": content_length,
        "content_range_header": response.headers.get("Content-Range"),
        "reported_total_bytes": total_bytes,
        "retrieved_bytes": written,
        "complete_file_retrieved": complete,
        "retrieved_sha256": sha256_file(target),
    }


def timestamp_value(raw: str) -> int | None:
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return None
    return value


def inspect_gzip_csv(
    path: Path,
    required_columns: list[str],
    maximum_rows: int,
    sample_output: Path,
) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    error: str | None = None
    header: list[str] = []
    gzip_header_valid = False
    try:
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = list(reader.fieldnames or [])
            gzip_header_valid = True
            for row_number, row in enumerate(reader, 1):
                rows.append({key: value for key, value in row.items() if key is not None})
                if row_number >= maximum_rows:
                    break
    except (EOFError, OSError, UnicodeDecodeError, csv.Error) as exc:
        error = f"{type(exc).__name__}: {exc}"

    sample_output.parent.mkdir(parents=True, exist_ok=True)
    if header:
        with sample_output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header)
            writer.writeheader()
            for row in rows[:20]:
                writer.writerow({key: row.get(key, "") for key in header})

    missing = sorted(set(required_columns) - set(header))
    symbols = [row.get("symbol", "") for row in rows if row.get("symbol")]
    unique_symbols = sorted(set(symbols))
    option_underliers = {"BTC": 0, "ETH": 0, "other": 0}
    option_types = {"C": 0, "P": 0, "other": 0}
    for symbol in symbols:
        match = OPTION_RE.match(symbol)
        if match:
            option_underliers[match.group(1)] += 1
            option_types[match.group(2)] += 1
        else:
            option_underliers["other"] += 1
            option_types["other"] += 1

    timestamps = [timestamp_value(row.get("timestamp", "")) for row in rows]
    local_timestamps = [timestamp_value(row.get("local_timestamp", "")) for row in rows]
    timestamps = [value for value in timestamps if value is not None]
    local_timestamps = [value for value in local_timestamps if value is not None]

    numeric_coverage: dict[str, dict[str, Any]] = {}
    for column in ("price", "amount", "underlying_price", "delta", "gamma", "bid_price", "ask_price"):
        if column not in header:
            continue
        finite = 0
        nonzero = 0
        values: list[float] = []
        for row in rows:
            try:
                value = float(row.get(column, ""))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                finite += 1
                nonzero += int(value != 0.0)
                if len(values) < 1000:
                    values.append(value)
        numeric_coverage[column] = {
            "finite_count": finite,
            "nonzero_count": nonzero,
            "minimum_first_1000": min(values) if values else None,
            "maximum_first_1000": max(values) if values else None,
        }

    return {
        "gzip_header_valid": gzip_header_valid,
        "parse_error": error,
        "columns": header,
        "required_columns": required_columns,
        "missing_required_columns": missing,
        "sample_row_count": len(rows),
        "unique_symbol_count_in_sample": len(unique_symbols),
        "first_symbols": unique_symbols[:20],
        "option_underlier_row_counts": option_underliers,
        "option_type_row_counts": option_types,
        "exchange_timestamp_first": timestamps[0] if timestamps else None,
        "exchange_timestamp_last": timestamps[-1] if timestamps else None,
        "exchange_timestamp_monotonic_in_sample": all(left <= right for left, right in zip(timestamps, timestamps[1:])),
        "local_timestamp_first": local_timestamps[0] if local_timestamps else None,
        "local_timestamp_last": local_timestamps[-1] if local_timestamps else None,
        "local_timestamp_monotonic_in_sample": all(left <= right for left, right in zip(local_timestamps, local_timestamps[1:])),
        "numeric_coverage": numeric_coverage,
    }


def role_required_columns(prereg: dict[str, Any], data_type: str, exchange: str) -> list[str]:
    required = prereg["required_schema"]
    if exchange == "deribit" and data_type == "trades":
        return required["option_trades"]
    if exchange == "deribit" and data_type == "options_chain":
        return required["option_chain_core"]
    if exchange == "bybit" and data_type == "quotes":
        return required["bybit_quotes"]
    if exchange == "bybit" and data_type == "trades":
        return required["bybit_trades"]
    raise KeyError((exchange, data_type))


def run(output: Path) -> dict[str, Any]:
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    contract = prereg["probe_contract"]
    date = contract["date"]
    maximum_rows = int(contract["maximum_sample_rows_per_file"])
    maximum_bytes = int(contract["maximum_download_bytes_per_file"])
    output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    with requests.Session() as session:
        session.headers.update({"User-Agent": "SMC-ICT-2-LIVE-option-flow-probe/1.0"})
        for item in contract["datasets"]:
            exchange = item["exchange"]
            data_type = item["data_type"]
            symbol = item["symbol"]
            url = source_url(exchange, data_type, date, symbol)
            name = f"{exchange}__{data_type}__{symbol}__{date}"
            compressed = output / "partial_sources" / f"{name}.csv.gz.part"
            sample = output / "samples" / f"{name}_head.csv"
            record: dict[str, Any] = {
                **item,
                "date": date,
                "url": url,
                "probe_only_partial_or_complete_prefix": True,
            }
            try:
                record.update(download_prefix(session, url, compressed, maximum_bytes))
                record.update(inspect_gzip_csv(
                    compressed,
                    role_required_columns(prereg, data_type, exchange),
                    maximum_rows,
                    sample,
                ))
            except Exception as exc:
                record["fatal_error"] = f"{type(exc).__name__}: {exc}"
            records.append(record)
            print(json.dumps({
                "exchange": exchange,
                "data_type": data_type,
                "symbol": symbol,
                "http_status": record.get("http_status"),
                "retrieved_bytes": record.get("retrieved_bytes"),
                "sample_rows": record.get("sample_row_count"),
                "missing": record.get("missing_required_columns"),
                "fatal_error": record.get("fatal_error"),
            }, sort_keys=True), flush=True)

    option_trades = next((row for row in records if row["exchange"] == "deribit" and row["data_type"] == "trades"), {})
    option_chain = next((row for row in records if row["exchange"] == "deribit" and row["data_type"] == "options_chain"), {})
    bybit_records = [row for row in records if row["exchange"] == "bybit"]
    all_schema_pass = all(not row.get("fatal_error") and not row.get("missing_required_columns") for row in records)
    underliers_present = (
        option_trades.get("option_underlier_row_counts", {}).get("BTC", 0) > 0
        and option_trades.get("option_underlier_row_counts", {}).get("ETH", 0) > 0
    )
    greeks_populated = all(
        option_chain.get("numeric_coverage", {}).get(column, {}).get("finite_count", 0) > 0
        for column in ("underlying_price", "delta", "gamma")
    )
    executable_bybit_present = all(
        row.get("sample_row_count", 0) > 0 and not row.get("missing_required_columns")
        for row in bybit_records
    )
    probe_pass = all_schema_pass and underliers_present and greeks_populated and executable_bybit_present
    result = {
        "schema_version": 1,
        "claim_id": prereg["claim_id"],
        "probe_id": prereg["probe_id"],
        "stage": prereg["research_stage"],
        "date": date,
        "probe_pass": probe_pass,
        "all_required_schema_present": all_schema_pass,
        "btc_and_eth_option_trades_present_in_sample": underliers_present,
        "option_underlying_delta_gamma_populated": greeks_populated,
        "bybit_btc_eth_executable_sources_present": executable_bybit_present,
        "strategy_pnl_opened": False,
        "candidate_grid_opened": False,
        "official_2024_opened": False,
        "official_2025_opened": False,
        "official_2026_opened": False,
        "orders_submitted": False,
        "records": records,
        "next_action_if_pass": "freeze exact full-file source manifest, clock normalization, flow-to-Greeks join and chronological fit/development dates before any PnL",
        "next_action_if_fail": "do not approximate missing core fields without a new preregistration; close or change the data source",
    }
    write_json(output / "SOURCE_PROBE.json", result)
    (output / "SOURCE_PROBE.sha256").write_text(
        f"{sha256_file(output / 'SOURCE_PROBE.json')}  SOURCE_PROBE.json\n",
        encoding="utf-8",
    )
    print("OPTION_FLOW_SOURCE_PROBE=" + json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
    return result


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.csv.gz"
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["exchange", "symbol", "timestamp", "local_timestamp", "side", "price", "amount", "underlying_price", "delta", "gamma"])
        writer.writerow(["deribit", "BTC-30JUN23-30000-C", "100", "110", "buy", "0.01", "2", "30000", "0.5", "0.0001"])
        writer.writerow(["deribit", "ETH-30JUN23-2000-P", "120", "130", "sell", "0.02", "3", "2000", "-0.5", "0.001"])
        path.write_bytes(gzip.compress(buffer.getvalue().encode("utf-8")))
        result = inspect_gzip_csv(
            path,
            ["symbol", "timestamp", "local_timestamp", "side", "price", "amount", "underlying_price", "delta", "gamma"],
            10,
            Path(tmp) / "head.csv",
        )
        assert result["missing_required_columns"] == []
        assert result["option_underlier_row_counts"]["BTC"] == 1
        assert result["option_underlier_row_counts"]["ETH"] == 1
        assert result["exchange_timestamp_monotonic_in_sample"] is True
        assert result["numeric_coverage"]["gamma"]["finite_count"] == 2
    print("SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
