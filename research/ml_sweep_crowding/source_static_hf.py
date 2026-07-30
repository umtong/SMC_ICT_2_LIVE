"""Official static Bybit one-minute prices plus a pinned public Bybit funding mirror.

This transport is used only after the REST source failed before any market or
strategy outcome.  The economic contract is unchanged.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote, urljoin

import numpy as np
import pandas as pd

from .common import CachedDownloader, MarketData, SourceGateError, sha256_file, sha256_json
from .source_data import (
    build_five_minute_features,
    construct_funding_cumulative,
    load_binance_metrics,
)

STATIC_ROOT = "https://public.bybit.com/kline_for_metatrader4"
SOURCE_CORRECTION_ID = "CORRECTION-20260727-ML-SWEEP-STATIC-MT4-PINNED-FUNDING-003"
MONTH_PATTERN = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)_1_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv\.gz$"
)
HREF_PATTERN = re.compile(r"href=[\"']([^\"']+\.csv\.gz)[\"']", re.IGNORECASE)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _request_listing(downloader: CachedDownloader, symbol: str, year: int) -> list[dict[str, Any]]:
    cache = downloader.cache_dir / "bybit_static" / symbol / str(year) / "LISTING.json"
    if cache.exists() and cache.stat().st_size > 32:
        payload = json.loads(cache.read_text(encoding="utf-8"))
        return list(payload.get("files", []))
    url = f"{STATIC_ROOT}/{symbol}/{year}/"
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = downloader.session.get(url, timeout=downloader.timeout)
            if response.status_code == 404:
                raw = response.content
                files: list[dict[str, Any]] = []
            else:
                response.raise_for_status()
                raw = response.content
                text = raw.decode("utf-8", errors="replace")
                names = sorted({Path(name).name for name in HREF_PATTERN.findall(text)})
                files = []
                for name in names:
                    match = MONTH_PATTERN.match(name)
                    if not match or match.group("symbol") != symbol:
                        continue
                    files.append(
                        {
                            "filename": name,
                            "start": match.group("start"),
                            "end_inclusive": match.group("end"),
                            "url": urljoin(url, name),
                        }
                    )
            payload = {
                "schema_version": 1,
                "source_correction_id": SOURCE_CORRECTION_ID,
                "symbol": symbol,
                "year": year,
                "url": url,
                "http_status": response.status_code,
                "body_sha256": _sha256_bytes(raw),
                "files": files,
            }
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return files
        except Exception as exc:
            last_error = exc
            time.sleep(min(2**attempt, 20))
    raise SourceGateError(f"Bybit static listing failed: {url}: {last_error}")


def download_bybit_months_static(
    downloader: CachedDownloader,
    symbols: Sequence[str],
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> dict[str, list[Path]]:
    jobs: list[tuple[str, str, str]] = []
    for symbol in symbols:
        for year in range(start.year, end_exclusive.year + 1):
            for item in _request_listing(downloader, symbol, year):
                file_start = pd.Timestamp(item["start"], tz="UTC")
                file_end = pd.Timestamp(item["end_inclusive"], tz="UTC") + pd.Timedelta(days=1)
                if file_end <= start or file_start >= end_exclusive:
                    continue
                relative = f"bybit_static/{symbol}/{year}/{item['filename']}"
                jobs.append((symbol, str(item["url"]), relative))
    paths: dict[str, list[Path]] = defaultdict(list)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(downloader.get, url, relative, 128): (symbol, relative)
            for symbol, url, relative in jobs
        }
        for future in as_completed(futures):
            symbol, _relative = futures[future]
            paths[symbol].append(future.result())
    for symbol in symbols:
        paths[symbol].sort()
        if not paths[symbol]:
            raise SourceGateError(f"no official static Bybit 1m files discovered for {symbol}")
    return dict(paths)


def parse_bybit_one_minute_static(
    symbol: str,
    files: Sequence[Path],
    requested_start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    minimum_coverage: float,
) -> tuple[pd.DataFrame, float, str, pd.Timestamp]:
    names = ["timestamp", "open", "high", "low", "close", "volume"]
    frames: list[pd.DataFrame] = []
    hashes: list[dict[str, Any]] = []
    for path in files:
        frame = pd.read_csv(
            path,
            compression="gzip",
            names=names,
            header=None,
            dtype={name: "float64" for name in names[1:]},
        )
        frame["timestamp"] = pd.to_datetime(
            frame["timestamp"], format="%Y.%m.%d %H:%M", utc=True, errors="coerce"
        )
        frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
        frames.append(frame)
        hashes.append(
            {"file": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
    if not frames:
        raise SourceGateError(f"no parseable official static Bybit files for {symbol}")
    data = pd.concat(frames, ignore_index=True)
    data = data.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
    data = data.loc[(data.index >= requested_start) & (data.index < end_exclusive), names[1:]]
    if data.empty:
        raise SourceGateError(f"official static Bybit interval empty for {symbol}")
    effective_start = max(requested_start, pd.Timestamp(data.index.min()).floor("1min"))
    expected_index = pd.date_range(effective_start, end_exclusive, freq="1min", inclusive="left")
    data = data.loc[data.index >= effective_start]
    observed = int(data.index.nunique())
    coverage = observed / max(len(expected_index), 1)
    if coverage < minimum_coverage:
        raise SourceGateError(
            f"{symbol} official static Bybit 1m coverage {coverage:.6%} below {minimum_coverage:.6%} "
            f"from first observed {effective_start.isoformat()}"
        )
    if data.index.max() < end_exclusive - pd.Timedelta(minutes=2):
        raise SourceGateError(
            f"{symbol} official static Bybit history ends early at {data.index.max()}"
        )
    data = data.reindex(expected_index)
    impossible = (
        (data["high"] < data[["open", "close", "low"]].max(axis=1))
        | (data["low"] > data[["open", "close", "high"]].min(axis=1))
        | (data[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    if bool(impossible.fillna(False).any()):
        raise SourceGateError(f"{symbol} official static Bybit contains impossible OHLC")
    return data, coverage, sha256_json(hashes), effective_start


def _normalize_funding(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {str(column).lower(): str(column) for column in frame.columns}
    time_name = next(
        (
            columns[name]
            for name in ("date", "timestamp", "time", "datetime", "funding_time")
            if name in columns
        ),
        None,
    )
    rate_name = next(
        (
            columns[name]
            for name in ("funding_rate", "fundingrate", "rate", "close")
            if name in columns
        ),
        None,
    )
    if time_name is None or rate_name is None:
        raise SourceGateError(f"funding mirror schema unsupported: {list(frame.columns)}")
    raw_time = frame[time_name]
    if pd.api.types.is_numeric_dtype(raw_time):
        numeric = pd.to_numeric(raw_time, errors="coerce")
        median = float(numeric.dropna().median()) if numeric.notna().any() else math.nan
        unit = "ms" if median > 1e11 else "s"
        timestamp = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    else:
        timestamp = pd.to_datetime(raw_time, utc=True, errors="coerce")
    rate = pd.to_numeric(frame[rate_name], errors="coerce")
    normalized = pd.DataFrame({"timestamp": timestamp, "funding_rate": rate})
    return (
        normalized.dropna()
        .drop_duplicates("timestamp", keep="last")
        .set_index("timestamp")
        .sort_index()
    )


def load_pinned_bybit_funding(
    downloader: CachedDownloader,
    symbol: str,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, str]:
    spec = contract["data"]["pinned_bybit_funding_mirror"]
    dataset = str(spec["dataset_id"])
    revision = str(spec["revision"])
    repository_path = str(spec["files"][symbol])
    expected_sha = str(spec["sha256"][symbol])
    encoded = quote(repository_path, safe="/")
    url = f"https://huggingface.co/datasets/{dataset}/resolve/{revision}/{encoded}?download=true"
    local = downloader.get(
        url,
        f"hf_bybit_funding/{revision}/{Path(repository_path).name}",
        64,
    )
    observed_sha = sha256_file(local)
    if observed_sha != expected_sha:
        raise SourceGateError(
            f"{symbol} pinned Bybit funding hash mismatch: {observed_sha} != {expected_sha}"
        )
    frame = _normalize_funding(pd.read_parquet(local))
    frame = frame.loc[(frame.index >= start) & (frame.index < end_exclusive)]
    if frame.empty:
        raise SourceGateError(f"{symbol} pinned Bybit funding interval empty")
    gaps = frame.index.to_series().diff().dropna()
    median_gap = gaps.median() if len(gaps) else pd.Timedelta(0)
    max_gap = gaps.max() if len(gaps) else pd.Timedelta(0)
    if not (pd.Timedelta(hours=4) <= median_gap <= pd.Timedelta(hours=12, minutes=1)):
        raise SourceGateError(f"{symbol} funding cadence is not settlement-like: median={median_gap}")
    if max_gap > pd.Timedelta(hours=24, minutes=1):
        raise SourceGateError(f"{symbol} funding gap exceeds 24h: {max_gap}")
    if frame.index.min() > start + pd.Timedelta(hours=16):
        raise SourceGateError(f"{symbol} funding starts too late: {frame.index.min()}")
    if frame.index.max() < end_exclusive - pd.Timedelta(hours=16):
        raise SourceGateError(f"{symbol} funding ends too early: {frame.index.max()}")
    rates = frame["funding_rate"].to_numpy(dtype=float)
    if not np.isfinite(rates).all() or float(np.max(np.abs(rates))) > 0.10:
        raise SourceGateError(f"{symbol} funding rates fail finite/range gate")
    return frame[["funding_rate"]], observed_sha


def load_market_static_hf(
    symbol: str,
    bybit_files: Sequence[Path],
    downloader: CachedDownloader,
    contract: Mapping[str, Any],
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> MarketData:
    one, coverage, one_hash, effective_start = parse_bybit_one_minute_static(
        symbol,
        bybit_files,
        start,
        end_exclusive,
        float(contract["data"]["minimum_one_minute_coverage"]),
    )
    metrics, metrics_hash = load_binance_metrics(
        downloader,
        symbol,
        effective_start,
        end_exclusive,
        contract["data"]["binance_metrics_mirror_pattern"],
    )
    funding, funding_hash = load_pinned_bybit_funding(
        downloader,
        symbol,
        effective_start,
        end_exclusive,
        contract,
    )
    five = build_five_minute_features(symbol, one, metrics, contract)
    funding_cum = construct_funding_cumulative(one, funding)
    return MarketData(
        symbol=symbol,
        one_minute=one,
        five_minute=five,
        funding=funding,
        funding_long_cum=funding_cum,
        minute_open=one["open"].to_numpy(dtype=np.float64, copy=True),
        minute_high=one["high"].to_numpy(dtype=np.float64, copy=True),
        minute_low=one["low"].to_numpy(dtype=np.float64, copy=True),
        minute_close=one["close"].to_numpy(dtype=np.float64, copy=True),
        coverage=coverage,
        one_minute_sha256=one_hash,
        metrics_sha256=metrics_hash,
        funding_sha256=funding_hash,
    )
