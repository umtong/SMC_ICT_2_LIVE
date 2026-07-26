#!/usr/bin/env python3
"""Inventory official public.bybit.com archives without downloading full history.

The inventory is strategy-agnostic. It enumerates date coverage, identifies
monthly 1-minute kline packages, samples compressed sizes, and records the
published CSV schema for the four project symbols.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests

BASE = "https://public.bybit.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
PERIODS = {
    "PRE_2024_2023": (date(2023, 1, 1), date(2024, 1, 1)),
    "2024_H1": (date(2024, 1, 1), date(2024, 7, 1)),
    "2024_H2": (date(2024, 7, 1), date(2025, 1, 1)),
    "2025_H1": (date(2025, 1, 1), date(2025, 7, 1)),
    "2025_H2": (date(2025, 7, 1), date(2026, 1, 1)),
    "2026_H1": (date(2026, 1, 1), date(2026, 7, 1)),
}


@dataclass(frozen=True)
class RemoteSample:
    url: str
    status: int
    content_length: int | None
    etag: str | None
    last_modified: str | None


def daterange(start: date, end_exclusive: date) -> Iterable[date]:
    current = start
    while current < end_exclusive:
        yield current
        current += timedelta(days=1)


def get_text(session: requests.Session, url: str, timeout: int) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def remote_metadata(session: requests.Session, url: str, timeout: int) -> RemoteSample:
    response = session.head(url, timeout=timeout, allow_redirects=True)
    if response.status_code in {403, 405} or response.status_code >= 500:
        response = session.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"Range": "bytes=0-0"},
            stream=True,
        )
    length: int | None = None
    content_range = response.headers.get("Content-Range")
    if content_range and "/" in content_range:
        try:
            length = int(content_range.rsplit("/", 1)[1])
        except ValueError:
            length = None
    if length is None:
        raw_length = response.headers.get("Content-Length")
        if raw_length:
            try:
                length = int(raw_length)
            except ValueError:
                length = None
    return RemoteSample(
        url=url,
        status=response.status_code,
        content_length=length,
        etag=response.headers.get("ETag"),
        last_modified=response.headers.get("Last-Modified"),
    )


def read_gzip_prefix(session: requests.Session, url: str, timeout: int) -> dict[str, object]:
    response = session.get(url, timeout=timeout, stream=True)
    response.raise_for_status()
    response.raw.decode_content = False
    with gzip.GzipFile(fileobj=response.raw) as gz:
        lines: list[str] = []
        for _ in range(3):
            raw = gz.readline()
            if not raw:
                break
            lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
    return {
        "url": url,
        "lines": lines,
        "prefix_sha256": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
    }


def evenly_spaced(values: list[str], count: int = 5) -> list[str]:
    if len(values) <= count:
        return values
    positions = sorted({round(i * (len(values) - 1) / (count - 1)) for i in range(count)})
    return [values[index] for index in positions]


def inventory_symbol(symbol: str, timeout: int) -> dict[str, object]:
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC_ICT_2_LIVE canonical archive inventory/1"})
    trading_dir = f"{BASE}/trading/{symbol}/"
    html = get_text(session, trading_dir, timeout)
    daily_pattern = re.compile(rf'href="({re.escape(symbol)}(\d{{4}}-\d{{2}}-\d{{2}})\.csv\.gz)"')
    available: dict[date, str] = {}
    for filename, iso_date in daily_pattern.findall(html):
        available[date.fromisoformat(iso_date)] = f"{trading_dir}{filename}"

    periods: dict[str, object] = {}
    all_samples: list[str] = []
    for period_id, (start, end_exclusive) in PERIODS.items():
        expected = list(daterange(start, end_exclusive))
        present_dates = [day for day in expected if day in available]
        missing = [day.isoformat() for day in expected if day not in available]
        urls = [available[day] for day in present_dates]
        sample_urls = evenly_spaced(urls)
        all_samples.extend(sample_urls)
        periods[period_id] = {
            "start": start.isoformat(),
            "end_exclusive": end_exclusive.isoformat(),
            "expected_days": len(expected),
            "present_days": len(present_dates),
            "missing_days": missing,
            "first_file": urls[0] if urls else None,
            "last_file": urls[-1] if urls else None,
            "sample_urls": sample_urls,
        }

    unique_samples = sorted(set(all_samples))
    metadata: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(remote_metadata, session, url, timeout): url for url in unique_samples}
        for future in as_completed(futures):
            sample = future.result()
            metadata[sample.url] = asdict(sample)

    for period in periods.values():
        sample_rows = [metadata[url] for url in period["sample_urls"] if url in metadata]
        lengths = [row["content_length"] for row in sample_rows if row["content_length"] is not None]
        period["samples"] = sample_rows
        period["sample_compressed_bytes_median"] = int(statistics.median(lengths)) if lengths else None
        period["estimated_compressed_bytes_from_sample_median"] = (
            int(statistics.median(lengths)) * period["present_days"] if lengths else None
        )

    kline: dict[str, object] = {}
    for year in (2023, 2024):
        year_url = f"{BASE}/kline_for_metatrader4/{symbol}/{year}/"
        try:
            year_html = get_text(session, year_url, timeout)
        except requests.HTTPError as exc:
            kline[str(year)] = {"url": year_url, "status": exc.response.status_code, "files": []}
            continue
        pattern = re.compile(
            rf'href="({re.escape(symbol)}_1_(\d{{4}}-\d{{2}}-\d{{2}})_(\d{{4}}-\d{{2}}-\d{{2}})\.csv\.gz)"'
        )
        files = [
            {
                "url": f"{year_url}{filename}",
                "start": start,
                "end": end,
            }
            for filename, start, end in pattern.findall(year_html)
        ]
        kline[str(year)] = {"url": year_url, "status": 200, "files": files}

    schema_urls: list[str] = []
    for target in (date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1), date(2026, 6, 30)):
        if target in available:
            schema_urls.append(available[target])
    schema_samples: list[dict[str, object]] = []
    for url in schema_urls:
        try:
            schema_samples.append(read_gzip_prefix(session, url, timeout))
        except Exception as exc:  # inventory must preserve failures as evidence
            schema_samples.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    return {
        "symbol": symbol,
        "trading_directory": trading_dir,
        "directory_daily_file_count": len(available),
        "directory_first_date": min(available).isoformat() if available else None,
        "directory_last_date": max(available).isoformat() if available else None,
        "periods": periods,
        "monthly_kline_1m": kline,
        "schema_samples": schema_samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    symbols: list[dict[str, object]] = []
    for symbol in SYMBOLS:
        symbols.append(inventory_symbol(symbol, args.timeout))

    result = {
        "schema_version": 1,
        "inventory_id": "INV-BYBIT-PUBLIC-4ASSET-HALFYEAR-20260727-R1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE,
        "symbols": symbols,
        "interpretation": {
            "directory_presence_is_source_availability_only": True,
            "sample_size_estimates_are_not_file_manifests": True,
            "no_market_outcomes_or_strategy_logic": True,
        },
    }
    path = args.out / "PUBLIC_ARCHIVE_INVENTORY.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.out / "PUBLIC_ARCHIVE_INVENTORY.sha256").write_text(
        f"{sha}  {path.name}\n", encoding="utf-8"
    )
    print(json.dumps({"path": str(path), "sha256": sha}, indent=2))


if __name__ == "__main__":
    main()
