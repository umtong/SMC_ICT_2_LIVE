from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

import run_screen as core

BASE = "https://data.binance.vision/data/futures/um"
KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_base_volume",
    "taker_buy_quote_volume", "ignore",
]
FUNDING_COLUMNS = ["calc_time", "funding_interval_hours", "last_funding_rate"]


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def month_labels(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return [str(item) for item in pd.period_range(start=start, end=end, freq="M")]


def request_bytes(
    session: requests.Session,
    url: str,
    *,
    allow_not_found: bool = False,
    attempts: int = 6,
) -> bytes | None:
    errors: list[str] = []
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=(30, 300))
            if response.status_code == 200:
                return response.content
            if response.status_code == 404 and allow_not_found:
                return None
            errors.append(f"HTTP {response.status_code}: {response.text[:160]}")
            if response.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(0.5 * 2**attempt, 8.0))
    raise RuntimeError(f"archive request failed {url}: {' | '.join(errors[-6:])}")


def parse_checksum(payload: bytes) -> str:
    text = payload.decode("utf-8-sig").strip()
    token = text.split()[0] if text else ""
    if len(token) != 64 or any(char not in "0123456789abcdefABCDEF" for char in token):
        raise ValueError(f"invalid Binance checksum payload: {text[:120]!r}")
    return token.lower()


def get_archive(
    session: requests.Session,
    cache: Path,
    url: str,
    *,
    allow_not_found: bool = False,
) -> tuple[bytes, dict[str, Any]] | None:
    cache.mkdir(parents=True, exist_ok=True)
    name = url.rsplit("/", 1)[-1]
    target = cache / name
    checksum_target = cache / f"{name}.CHECKSUM"
    cache_hit = target.exists() and checksum_target.exists()
    if cache_hit:
        payload = target.read_bytes()
        checksum_payload = checksum_target.read_bytes()
    else:
        payload = request_bytes(session, url, allow_not_found=allow_not_found)
        if payload is None:
            return None
        checksum_payload = request_bytes(session, url + ".CHECKSUM", allow_not_found=False)
        assert checksum_payload is not None
        target.write_bytes(payload)
        checksum_target.write_bytes(checksum_payload)
    expected = parse_checksum(checksum_payload)
    actual = sha256(payload)
    if actual != expected:
        raise ValueError(f"checksum mismatch {url}: expected={expected} actual={actual}")
    return payload, {
        "url": url,
        "bytes": len(payload),
        "sha256": actual,
        "checksum_url": url + ".CHECKSUM",
        "checksum_sha256": sha256(checksum_payload),
        "checksum_verified": True,
        "cache_hit": cache_hit,
    }


def csv_from_zip(payload: bytes, columns: list[str]) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in archive, found {names}")
        raw = archive.read(names[0])
    frame = pd.read_csv(io.BytesIO(raw), header=None, dtype=str)
    if frame.empty:
        return pd.DataFrame(columns=columns)
    first = str(frame.iloc[0, 0]).strip().lower()
    if first in {columns[0].lower(), "open_time", "calc_time"}:
        frame = frame.iloc[1:].reset_index(drop=True)
    if frame.shape[1] < len(columns):
        raise ValueError(f"archive CSV has {frame.shape[1]} columns, expected at least {len(columns)}")
    frame = frame.iloc[:, : len(columns)].copy()
    frame.columns = columns
    return frame


def parse_epoch(values: pd.Series) -> pd.DatetimeIndex:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric.dropna()
    if finite.empty:
        return pd.DatetimeIndex([pd.NaT] * len(numeric), tz="UTC")
    unit = "us" if float(finite.median()) >= 1e14 else "ms"
    return pd.DatetimeIndex(pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce"))


def kline_url(symbol: str, label: str, *, daily: bool = False) -> str:
    periodicity = "daily" if daily else "monthly"
    return f"{BASE}/{periodicity}/klines/{symbol}/15m/{symbol}-15m-{label}.zip"


def funding_url(symbol: str, label: str) -> str:
    return f"{BASE}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{label}.zip"


def normalize_klines(parts: list[pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=KLINE_COLUMNS)
    frame["timestamp"] = parse_epoch(frame["open_time"])
    for name in ("open", "high", "low", "close", "volume", "quote_volume"):
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    frame = frame.rename(columns={"quote_volume": "turnover"})
    frame = frame[["timestamp", "open", "high", "low", "close", "volume", "turnover"]]
    frame = frame.dropna().drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    frame = frame.loc[(frame["timestamp"] >= start) & (frame["timestamp"] <= end)].set_index("timestamp")
    return frame


def proxy_download_klines(
    session: requests.Session,
    cache: Path,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    root = cache / "binance_usdm" / "klines" / symbol
    target = root / f"{symbol}_15m_2022_2023.csv"
    manifest_path = root / f"{symbol}_15m_manifest.json"
    if target.exists() and manifest_path.exists():
        frame = pd.read_csv(target)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["cache_hit"] = True
        return frame.set_index("timestamp").sort_index(), manifest

    parts: list[pd.DataFrame] = []
    pages: list[dict[str, Any]] = []
    with requests.Session() as local:
        local.headers.update(session.headers)
        for label in month_labels(start, end):
            url = kline_url(symbol, label)
            loaded = get_archive(local, root / "archives", url)
            assert loaded is not None
            payload, record = loaded
            parsed = csv_from_zip(payload, KLINE_COLUMNS)
            record.update({"periodicity": "monthly", "label": label, "returned_rows": int(len(parsed))})
            pages.append(record)
            parts.append(parsed)

        frame = normalize_klines(parts, start, end)
        expected = pd.date_range(start=start, end=end.floor("15min"), freq="15min")
        missing_before = expected.difference(frame.index)
        missing_dates = sorted({str(value.date()) for value in missing_before})
        if len(missing_dates) > 60:
            raise RuntimeError(f"too many missing Binance kline dates for {symbol}: {len(missing_dates)}")
        repair_parts: list[pd.DataFrame] = []
        for label in missing_dates:
            url = kline_url(symbol, label, daily=True)
            loaded = get_archive(local, root / "daily_repairs", url, allow_not_found=True)
            if loaded is None:
                pages.append({
                    "url": url,
                    "periodicity": "daily_repair",
                    "label": label,
                    "not_found": True,
                    "bytes": 0,
                    "sha256": sha256(b""),
                    "returned_rows": 0,
                })
                continue
            payload, record = loaded
            parsed = csv_from_zip(payload, KLINE_COLUMNS)
            record.update({"periodicity": "daily_repair", "label": label, "returned_rows": int(len(parsed))})
            pages.append(record)
            repair_parts.append(parsed)
        if repair_parts:
            frame = normalize_klines(parts + repair_parts, start, end)

    if frame.empty:
        raise RuntimeError(f"no Binance kline rows for {symbol}")
    if frame.index.max() >= pd.Timestamp("2024-01-01T00:00:00Z"):
        raise AssertionError("official 2024 data opened by Binance proxy loader")
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.reset_index().to_csv(target, index=False)
    expected = pd.date_range(start=start, end=end.floor("15min"), freq="15min")
    missing_after = expected.difference(frame.index)
    manifest = {
        "kind": "binance_usdm_kline_proxy",
        "venue": "Binance USD-M",
        "symbol": symbol,
        "interval": "15m",
        "start": str(start),
        "end": str(end),
        "page_count": len(pages),
        "pages": pages,
        "row_count": int(len(frame)),
        "normalized_sha256": sha256(target.read_bytes()),
        "first_timestamp": str(frame.index.min()),
        "last_timestamp": str(frame.index.max()),
        "missing_bar_count_before_daily_repair": int(len(missing_before)),
        "missing_bar_count_after_daily_repair": int(len(missing_after)),
        "missing_bar_fraction_after_daily_repair": float(len(missing_after) / max(len(expected), 1)),
        "cache_hit": False,
    }
    write_json(manifest_path, manifest)
    return frame, manifest


def normalize_funding(parts: list[pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=FUNDING_COLUMNS)
    frame["timestamp"] = parse_epoch(frame["calc_time"])
    frame["rate"] = pd.to_numeric(frame["last_funding_rate"], errors="coerce")
    frame = frame[["timestamp", "rate"]].dropna().drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    frame = frame.loc[(frame["timestamp"] >= start) & (frame["timestamp"] <= end)]
    return frame.set_index("timestamp")["rate"].astype(float)


def proxy_download_funding(
    session: requests.Session,
    cache: Path,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.Series, dict[str, Any]]:
    root = cache / "binance_usdm" / "funding" / symbol
    target = root / f"{symbol}_funding_2022_2023.csv"
    manifest_path = root / f"{symbol}_funding_manifest.json"
    if target.exists() and manifest_path.exists():
        frame = pd.read_csv(target)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        series = frame.set_index("timestamp")["rate"].sort_index().astype(float)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["cache_hit"] = True
        return series, manifest

    parts: list[pd.DataFrame] = []
    pages: list[dict[str, Any]] = []
    with requests.Session() as local:
        local.headers.update(session.headers)
        for label in month_labels(start, end):
            url = funding_url(symbol, label)
            loaded = get_archive(local, root / "archives", url)
            assert loaded is not None
            payload, record = loaded
            parsed = csv_from_zip(payload, FUNDING_COLUMNS)
            record.update({"periodicity": "monthly", "label": label, "returned_rows": int(len(parsed))})
            pages.append(record)
            parts.append(parsed)
    series = normalize_funding(parts, start, end)
    if series.empty:
        raise RuntimeError(f"no Binance funding rows for {symbol}")
    if series.index.max() >= pd.Timestamp("2024-01-01T00:00:00Z"):
        raise AssertionError("official 2024 data opened by Binance proxy funding loader")
    target.parent.mkdir(parents=True, exist_ok=True)
    series.rename("rate").reset_index().to_csv(target, index=False)
    manifest = {
        "kind": "binance_usdm_funding_proxy",
        "venue": "Binance USD-M",
        "symbol": symbol,
        "start": str(start),
        "end": str(end),
        "page_count": len(pages),
        "pages": pages,
        "row_count": int(len(series)),
        "normalized_sha256": sha256(target.read_bytes()),
        "first_timestamp": str(series.index.min()),
        "last_timestamp": str(series.index.max()),
        "cache_hit": False,
    }
    write_json(manifest_path, manifest)
    return series, manifest


def run(cache: Path, output: Path) -> dict[str, Any]:
    core.download_klines = proxy_download_klines
    core.download_funding = proxy_download_funding
    result = core.run_screen(cache, output)
    result.update({
        "hard_validity_status": "PRELIMINARY_CAUSAL_PASS_BINANCE_USDM_PROXY",
        "data_contract_role": "Official Binance USD-M 15m and funding fatal-screen proxy; exact Bybit replay required for any survivor.",
        "failed_bybit_api_run_id": 30191857335,
        "bybit_api_data_opened_before_amendment": False,
    })
    write_json(output / "result_summary.json", result)
    manifest_path = output / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "source_contract": "official Binance USD-M public monthly archives as preregistered source-amendment proxy",
        "final_execution_venue_required": "Bybit USDT linear perpetual",
        "bybit_api_data_opened_before_amendment": False,
    })
    write_json(manifest_path, manifest)
    return result


def self_test() -> None:
    rows = [
        ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"],
        ["1640995200000", "100", "101", "99", "100.5", "2", "1640996099999", "200", "3", "1", "100", "0"],
    ]
    buffer = io.StringIO()
    for row in rows:
        buffer.write(",".join(row) + "\n")
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sample.csv", buffer.getvalue())
    parsed = csv_from_zip(zipped.getvalue(), KLINE_COLUMNS)
    frame = normalize_klines(
        [parsed],
        pd.Timestamp("2022-01-01T00:00:00Z"),
        pd.Timestamp("2022-01-01T00:15:00Z"),
    )
    assert len(frame) == 1 and float(frame.iloc[0]["close"]) == 100.5

    funding_rows = "calc_time,funding_interval_hours,last_funding_rate\n1640995200000,8,0.0001\n"
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("funding.csv", funding_rows)
    parsed_funding = csv_from_zip(zipped.getvalue(), FUNDING_COLUMNS)
    series = normalize_funding(
        [parsed_funding],
        pd.Timestamp("2022-01-01T00:00:00Z"),
        pd.Timestamp("2022-01-01T01:00:00Z"),
    )
    assert len(series) == 1 and abs(float(series.iloc[0]) - 0.0001) < 1e-12
    print("PROXY_SOURCE_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        run(args.cache, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
