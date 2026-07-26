from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Iterable

import requests

CLAIM_ID = "CLM-20260726-2020-ML-BINANCE-LIQ-DENSE-001"
MARKET_SCOPE = "COIN_M_EXTERNAL_SIGNAL"
BUCKET_BASE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DOWNLOAD_BASE = "https://data.binance.vision"
SOURCE_SYMBOLS = ("BTCUSD_PERP", "ETHUSD_PERP")
BYBIT_SIGNAL_MAP = {
    "BTCUSD_PERP": "BTCUSDT",
    "ETHUSD_PERP": "ETHUSDT",
}
START_DATE = dt.date(2021, 1, 1)
END_DATE = dt.date(2023, 12, 31)
FIXED_SAMPLE_DATES = (
    "2021-01-29",
    "2021-05-19",
    "2021-09-07",
    "2021-12-04",
    "2022-05-12",
    "2022-06-13",
    "2022-11-09",
    "2023-03-10",
    "2023-08-17",
    "2023-10-23",
)
EXPECTED_FIELDS = (
    "time",
    "side",
    "order_type",
    "time_in_force",
    "original_quantity",
    "price",
    "average_price",
    "order_status",
    "last_filled_quantity",
    "accumulated_filled_quantity",
)
_HEADER_ALIASES = {
    "time": "time",
    "side": "side",
    "ordertype": "order_type",
    "order_type": "order_type",
    "timeinforce": "time_in_force",
    "time_in_force": "time_in_force",
    "originalquantity": "original_quantity",
    "original_quantity": "original_quantity",
    "origqty": "original_quantity",
    "price": "price",
    "averageprice": "average_price",
    "average_price": "average_price",
    "avgprice": "average_price",
    "orderstatus": "order_status",
    "order_status": "order_status",
    "status": "order_status",
    "lastfilledquantity": "last_filled_quantity",
    "last_filled_quantity": "last_filled_quantity",
    "executedqty": "last_filled_quantity",
    "accumulatedfilledquantity": "accumulated_filled_quantity",
    "accumulated_filled_quantity": "accumulated_filled_quantity",
    "cumqty": "accumulated_filled_quantity",
}
_KEY_RE = re.compile(
    r"^(?P<prefix>data/futures/cm/daily/liquidationSnapshot/)"
    r"(?P<symbol>[A-Z0-9_]+)/"
    r"(?P=symbol)-liquidationSnapshot-(?P<date>\d{4}-\d{2}-\d{2})\.zip$"
)


class SourceGateError(RuntimeError):
    pass


def stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def date_sequence(start: dt.date = START_DATE, end: dt.date = END_DATE) -> list[str]:
    values: list[str] = []
    cursor = start
    while cursor <= end:
        values.append(cursor.isoformat())
        cursor += dt.timedelta(days=1)
    return values


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", value.strip().lower().replace(" ", "_"))


def parse_timestamp(value: Any) -> int:
    text = str(value).strip()
    if not text or not re.fullmatch(r"\d+", text):
        raise SourceGateError(f"invalid timestamp {value!r}")
    number = int(text)
    while number >= 10**15:
        number //= 1000
    if number < 10**12:
        number *= 1000
    try:
        observed = dt.datetime.fromtimestamp(number / 1000, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise SourceGateError(f"timestamp outside supported range: {value!r}") from exc
    if not (
        dt.datetime(2019, 1, 1, tzinfo=dt.timezone.utc)
        <= observed
        < dt.datetime(2024, 1, 2, tzinfo=dt.timezone.utc)
    ):
        raise SourceGateError(f"timestamp outside source envelope: {observed.isoformat()}")
    return number


def parse_float(value: Any, name: str, *, allow_zero: bool = True) -> float:
    try:
        number = float(str(value).strip())
    except Exception as exc:
        raise SourceGateError(f"invalid {name}: {value!r}") from exc
    if not math.isfinite(number) or number < 0 or (not allow_zero and number <= 0):
        raise SourceGateError(f"invalid {name}: {value!r}")
    return number


def parse_checksum(payload: bytes, expected_filename: str) -> str:
    text = payload.decode("utf-8-sig").strip()
    parts = text.replace("*", " ").split()
    if len(parts) < 2:
        raise SourceGateError(f"invalid checksum payload for {expected_filename}")
    digest, filename = parts[0].lower(), parts[-1].strip()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SourceGateError(f"invalid checksum digest for {expected_filename}")
    if Path(filename).name != expected_filename:
        raise SourceGateError(
            f"checksum filename mismatch: {filename!r} != {expected_filename!r}"
        )
    return digest


def _row_mapping(raw: list[str], header: list[str] | None) -> dict[str, str]:
    if header is None:
        if len(raw) < len(EXPECTED_FIELDS):
            raise SourceGateError(f"headerless row has {len(raw)} columns")
        return dict(zip(EXPECTED_FIELDS, raw[: len(EXPECTED_FIELDS)], strict=True))
    if len(raw) != len(header):
        raise SourceGateError(f"row/header length mismatch: {len(raw)} != {len(header)}")
    output: dict[str, str] = {}
    for key, value in zip(header, raw, strict=True):
        canonical = _HEADER_ALIASES.get(normalize_header(key))
        if canonical is not None:
            output[canonical] = value
    missing = [field for field in EXPECTED_FIELDS if field not in output]
    if missing:
        raise SourceGateError(f"missing liquidation columns: {missing}")
    return output


def iter_liquidation_rows(payload: bytes) -> Iterable[dict[str, Any]]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
                raise SourceGateError("archive must contain exactly one CSV")
            raw = archive.read(members[0])
    except (zipfile.BadZipFile, OSError) as exc:
        raise SourceGateError("invalid liquidation ZIP") from exc

    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    first = next(reader, None)
    if first is None:
        return
    normalized = {normalize_header(value) for value in first}
    has_header = "time" in normalized and "side" in normalized
    header = first if has_header else None
    rows = reader if has_header else iter([first, *reader])

    for ordinal, raw_row in enumerate(rows):
        if not raw_row or not any(str(value).strip() for value in raw_row):
            continue
        mapped = _row_mapping([str(value) for value in raw_row], header)
        timestamp = parse_timestamp(mapped["time"])
        side = mapped["side"].strip().upper()
        if side not in {"BUY", "SELL"}:
            raise SourceGateError(f"invalid liquidation side {side!r}")
        original_quantity = parse_float(
            mapped["original_quantity"], "original_quantity", allow_zero=False
        )
        price = parse_float(mapped["price"], "price", allow_zero=True)
        average_price = parse_float(
            mapped["average_price"], "average_price", allow_zero=True
        )
        last_filled_quantity = parse_float(
            mapped["last_filled_quantity"], "last_filled_quantity", allow_zero=True
        )
        accumulated_filled_quantity = parse_float(
            mapped["accumulated_filled_quantity"],
            "accumulated_filled_quantity",
            allow_zero=True,
        )
        effective_price = average_price if average_price > 0 else price
        effective_quantity = (
            accumulated_filled_quantity
            if accumulated_filled_quantity > 0
            else last_filled_quantity
            if last_filled_quantity > 0
            else original_quantity
        )
        if effective_price <= 0 or effective_quantity <= 0:
            raise SourceGateError("liquidation row lacks positive executable price/quantity")
        yield {
            "ordinal": ordinal,
            "time": timestamp,
            "side": side,
            "order_type": mapped["order_type"].strip().upper(),
            "time_in_force": mapped["time_in_force"].strip().upper(),
            "order_status": mapped["order_status"].strip().upper(),
            "original_quantity": original_quantity,
            "price": price,
            "average_price": average_price,
            "last_filled_quantity": last_filled_quantity,
            "accumulated_filled_quantity": accumulated_filled_quantity,
            "effective_price": effective_price,
            "effective_quantity": effective_quantity,
        }


def request_bytes(
    session: requests.Session,
    url: str,
    *,
    attempts: int = 5,
    timeout: tuple[int, int] = (20, 120),
) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=timeout)
            if response.status_code == 404:
                raise FileNotFoundError(url)
            if response.status_code == 429 or response.status_code >= 500:
                raise SourceGateError(f"HTTP {response.status_code}: {response.text[:200]}")
            response.raise_for_status()
            return response.content
        except FileNotFoundError:
            raise
        except Exception as exc:
            last = exc
            if attempt + 1 >= attempts:
                break
            time.sleep(min(10.0, 0.75 * (2**attempt)))
    raise SourceGateError(f"request failed for {url}: {last!r}")


def list_objects(session: requests.Session, prefix: str) -> tuple[list[str], list[dict[str, Any]]]:
    token: str | None = None
    keys: list[str] = []
    pages: list[dict[str, Any]] = []
    while True:
        params: dict[str, str] = {
            "list-type": "2",
            "prefix": prefix,
            "max-keys": "1000",
        }
        if token:
            params["continuation-token"] = token
        response = session.get(BUCKET_BASE, params=params, timeout=(20, 120))
        response.raise_for_status()
        root = ET.fromstring(response.content)
        namespace = ""
        if root.tag.startswith("{"):
            namespace = root.tag.split("}", 1)[0] + "}"
        page_keys = [
            node.text or ""
            for node in root.findall(f"{namespace}Contents/{namespace}Key")
        ]
        keys.extend(page_keys)
        truncated = (root.findtext(f"{namespace}IsTruncated") or "").lower() == "true"
        next_token = root.findtext(f"{namespace}NextContinuationToken")
        pages.append(
            {
                "request_url": response.url,
                "status_code": response.status_code,
                "key_count": len(page_keys),
                "is_truncated": truncated,
                "response_sha256": sha256_bytes(response.content),
            }
        )
        if not truncated:
            break
        if not next_token or next_token == token:
            raise SourceGateError("S3 listing truncated without a new continuation token")
        token = next_token
    return sorted(set(keys)), pages


def expected_key(symbol: str, date_text: str) -> str:
    return (
        f"data/futures/cm/daily/liquidationSnapshot/{symbol}/"
        f"{symbol}-liquidationSnapshot-{date_text}.zip"
    )


def key_date(key: str, symbol: str) -> str | None:
    match = _KEY_RE.match(key)
    if match is None or match.group("symbol") != symbol:
        return None
    return match.group("date")


def inspect_archive(
    session: requests.Session,
    *,
    key: str,
    symbol: str,
    expected_date: str,
    sample_output: gzip.GzipFile,
) -> dict[str, Any]:
    filename = Path(key).name
    checksum_url = f"{DOWNLOAD_BASE}/{key}.CHECKSUM"
    archive_url = f"{DOWNLOAD_BASE}/{key}"
    checksum_payload = request_bytes(session, checksum_url)
    expected_digest = parse_checksum(checksum_payload, filename)
    archive_payload = request_bytes(session, archive_url)
    observed_digest = sha256_bytes(archive_payload)
    if observed_digest != expected_digest:
        raise SourceGateError(f"checksum mismatch for {filename}")

    start = dt.datetime.fromisoformat(expected_date).replace(tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    rows: list[dict[str, Any]] = []
    for row in iter_liquidation_rows(archive_payload):
        observed = dt.datetime.fromtimestamp(row["time"] / 1000, tz=dt.timezone.utc)
        if not (start <= observed < end):
            raise SourceGateError(
                f"{filename} row outside {expected_date}: {observed.isoformat()}"
            )
        enriched = {
            **row,
            "source_symbol": symbol,
            "bybit_symbol": BYBIT_SIGNAL_MAP[symbol],
            "source_key": key,
            "source_date": expected_date,
        }
        sample_output.write((stable_json(enriched) + "\n").encode("utf-8"))
        rows.append(enriched)

    identities = {
        (
            row["time"],
            row["side"],
            round(float(row["effective_price"]), 12),
            round(float(row["effective_quantity"]), 12),
        )
        for row in rows
    }
    return {
        "key": key,
        "filename": filename,
        "date": expected_date,
        "symbol": symbol,
        "archive_bytes": len(archive_payload),
        "archive_sha256": observed_digest,
        "checksum_sha256": sha256_bytes(checksum_payload),
        "row_count": len(rows),
        "unique_identity_count": len(identities),
        "sides": sorted({row["side"] for row in rows}),
    }


def run(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "SMC_ICT_2_LIVE-coinm-liquidation-source/1.0"

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "market_scope": MARKET_SCOPE,
        "bucket_base": BUCKET_BASE,
        "download_base": DOWNLOAD_BASE,
        "source_symbols": list(SOURCE_SYMBOLS),
        "bybit_signal_map": BYBIT_SIGNAL_MAP,
        "fixed_range": [START_DATE.isoformat(), END_DATE.isoformat()],
        "fixed_sample_dates": list(FIXED_SAMPLE_DATES),
        "listings": {},
        "sample_archives": [],
    }
    result: dict[str, Any] = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "market_scope": MARKET_SCOPE,
        "source_gate_pass": False,
        "status": "SOURCE_ERROR",
        "scientific_decision": "CLOSE_OFFICIAL_LIQUIDATION_SNAPSHOT_ROUTE_BEFORE_OUTCOMES",
        "checks": {},
        "market_outcome_opened": False,
        "model_fit": False,
        "trade_or_pnl_opened": False,
        "official_2024_2026_opened": False,
        "credentials_used": False,
        "orders_submitted": False,
    }

    all_dates = set(date_sequence())
    archive_dates_by_symbol: dict[str, set[str]] = {}
    sample_summaries: list[dict[str, Any]] = []
    sample_rows = 0
    nonempty_samples = 0
    sample_sides: set[str] = set()
    duplicate_rows = 0
    total_sample_unique = 0

    sample_path = output / "SAMPLE_ROWS.jsonl.gz"
    try:
        for symbol in SOURCE_SYMBOLS:
            prefix = f"data/futures/cm/daily/liquidationSnapshot/{symbol}/"
            keys, pages = list_objects(session, prefix)
            zip_keys = [
                key
                for key in keys
                if key.endswith(".zip") and key_date(key, symbol) is not None
            ]
            dates = {
                value
                for key in zip_keys
                if (value := key_date(key, symbol)) is not None and value in all_dates
            }
            archive_dates_by_symbol[symbol] = dates
            manifest["listings"][symbol] = {
                "prefix": prefix,
                "pages": pages,
                "listed_key_count": len(keys),
                "listed_zip_count": len(zip_keys),
                "eligible_date_count": len(dates),
                "eligible_date_fraction": len(dates) / len(all_dates),
                "first_date": min(dates) if dates else None,
                "last_date": max(dates) if dates else None,
                "key_set_sha256": sha256_bytes("\n".join(zip_keys).encode("utf-8")),
            }

        with gzip.open(sample_path, "wb", compresslevel=6) as handle:
            for symbol in SOURCE_SYMBOLS:
                dates = archive_dates_by_symbol[symbol]
                for date_text in FIXED_SAMPLE_DATES:
                    key = expected_key(symbol, date_text)
                    if date_text not in dates:
                        sample_summaries.append(
                            {
                                "key": key,
                                "symbol": symbol,
                                "date": date_text,
                                "status": "MISSING",
                                "row_count": 0,
                            }
                        )
                        continue
                    summary = inspect_archive(
                        session,
                        key=key,
                        symbol=symbol,
                        expected_date=date_text,
                        sample_output=handle,
                    )
                    summary["status"] = "PASS"
                    sample_summaries.append(summary)
                    rows = int(summary["row_count"])
                    unique = int(summary["unique_identity_count"])
                    sample_rows += rows
                    total_sample_unique += unique
                    duplicate_rows += rows - unique
                    if rows > 0:
                        nonempty_samples += 1
                    sample_sides.update(summary["sides"])

        manifest["sample_archives"] = sample_summaries
        coverage_checks = {
            symbol: len(archive_dates_by_symbol[symbol]) / len(all_dates) >= 0.80
            for symbol in SOURCE_SYMBOLS
        }
        fixed_sample_checks = {
            symbol: all(
                date_text in archive_dates_by_symbol[symbol]
                for date_text in FIXED_SAMPLE_DATES
            )
            for symbol in SOURCE_SYMBOLS
        }
        sample_count = len(SOURCE_SYMBOLS) * len(FIXED_SAMPLE_DATES)
        duplicate_fraction = duplicate_rows / sample_rows if sample_rows else 1.0
        checks = {
            "coin_m_scope_frozen": MARKET_SCOPE == "COIN_M_EXTERNAL_SIGNAL",
            "both_source_symbols_listed": all(archive_dates_by_symbol.values()),
            "coverage_at_least_80pct_each": all(coverage_checks.values()),
            "all_fixed_samples_present_each": all(fixed_sample_checks.values()),
            "both_liquidation_sides_observed": sample_sides == {"BUY", "SELL"},
            "at_least_500_fixed_sample_rows": sample_rows >= 500,
            "at_least_75pct_fixed_samples_nonempty": nonempty_samples
            >= math.ceil(0.75 * sample_count),
            "duplicate_fraction_below_10pct": duplicate_fraction < 0.10,
            "outcome_seal_intact": True,
        }
        passed = all(checks.values())
        result.update(
            {
                "status": "PASS" if passed else "BELOW_SOURCE_GATE",
                "source_gate_pass": passed,
                "scientific_decision": (
                    "OPEN_FROZEN_PRE2024_DENSE_LIQUIDATION_MODEL_STAGE"
                    if passed
                    else "CLOSE_OFFICIAL_LIQUIDATION_SNAPSHOT_ROUTE_BEFORE_OUTCOMES"
                ),
                "layout": "COIN_M_DAILY_LIQUIDATION_SNAPSHOT",
                "checks": checks,
                "coverage_checks": coverage_checks,
                "fixed_sample_checks": fixed_sample_checks,
                "totals": {
                    "eligible_dates_by_symbol": {
                        symbol: len(dates)
                        for symbol, dates in archive_dates_by_symbol.items()
                    },
                    "fixed_sample_archive_count": sample_count,
                    "nonempty_fixed_sample_archive_count": nonempty_samples,
                    "sample_row_count": sample_rows,
                    "sample_unique_identity_count": total_sample_unique,
                    "sample_duplicate_count": duplicate_rows,
                    "sample_duplicate_fraction": duplicate_fraction,
                    "sample_sides": sorted(sample_sides),
                },
            }
        )
    except Exception as exc:
        result["fatal_error"] = repr(exc)
        result["checks"] = {"outcome_seal_intact": True}

    manifest_path = output / "SOURCE_MANIFEST.json"
    result_path = output / "SOURCE_GATE_RESULT.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def self_test() -> None:
    assert SOURCE_SYMBOLS == ("BTCUSD_PERP", "ETHUSD_PERP")
    assert expected_key("BTCUSD_PERP", "2022-01-01") == (
        "data/futures/cm/daily/liquidationSnapshot/BTCUSD_PERP/"
        "BTCUSD_PERP-liquidationSnapshot-2022-01-01.zip"
    )
    assert key_date(
        expected_key("ETHUSD_PERP", "2023-08-17"), "ETHUSD_PERP"
    ) == "2023-08-17"
    assert len(date_sequence()) == 1095

    header = ",".join(EXPECTED_FIELDS)
    csv_payload = (
        header
        + "\n"
        + "1640995200000,SELL,LIMIT,IOC,2,47000,46990,FILLED,2,2\n"
        + "1640995260000,BUY,LIMIT,IOC,1,47100,47110,FILLED,1,1\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "BTCUSD_PERP-liquidationSnapshot-2022-01-01.csv", csv_payload
        )
    rows = list(iter_liquidation_rows(buffer.getvalue()))
    assert [row["side"] for row in rows] == ["SELL", "BUY"]
    assert rows[0]["effective_price"] == 46990.0
    assert parse_timestamp("1640995200000000") == 1640995200000
    digest = sha256_bytes(b"abc")
    assert parse_checksum(f"{digest}  file.zip\n".encode(), "file.zip") == digest
    print("COIN_M_LIQUIDATION_SOURCE_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        raise SystemExit("--output is required")
    result = run(args.output)
    print(
        json.dumps(
            {
                "status": result["status"],
                "source_gate_pass": result["source_gate_pass"],
                "scientific_decision": result["scientific_decision"],
                "totals": result.get("totals", {}),
                "fatal_error": result.get("fatal_error"),
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
