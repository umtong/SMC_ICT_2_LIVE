"""Frozen public-source acquisition and causal bar construction."""
from __future__ import annotations

import calendar
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .common import (
    EPS,
    CachedDownloader,
    MarketData,
    SourceGateError,
    month_range,
    sha256_file,
    sha256_json,
)


def bybit_month_spec(symbol: str, year: int, month: int) -> tuple[str, str]:
    last = calendar.monthrange(year, month)[1]
    filename = f"{symbol}_1_{year:04d}-{month:02d}-01_{year:04d}-{month:02d}-{last:02d}.csv.gz"
    url = f"https://public.bybit.com/kline_for_metatrader4/{symbol}/{year}/{filename}"
    return filename, url


def download_bybit_months(
    downloader: CachedDownloader,
    symbols: Sequence[str],
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> dict[str, list[Path]]:
    jobs: list[tuple[str, str, str]] = []
    for symbol in symbols:
        for year, month in month_range(start, end_exclusive):
            filename, url = bybit_month_spec(symbol, year, month)
            jobs.append((symbol, url, f"bybit/{symbol}/{year}/{filename}"))
    paths: dict[str, list[Path]] = defaultdict(list)
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(downloader.get, url, rel, 128): (symbol, rel)
            for symbol, url, rel in jobs
        }
        for future in as_completed(futures):
            symbol, _ = futures[future]
            paths[symbol].append(future.result())
    for symbol in paths:
        paths[symbol].sort()
    return paths


def parse_bybit_one_minute(
    symbol: str,
    files: Sequence[Path],
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    minimum_coverage: float,
) -> tuple[pd.DataFrame, float, str]:
    frames: list[pd.DataFrame] = []
    hashes: list[dict[str, str]] = []
    names = ["timestamp", "open", "high", "low", "close", "volume"]
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
        hashes.append({"file": path.name, "sha256": sha256_file(path)})
    if not frames:
        raise SourceGateError(f"no Bybit 1m files for {symbol}")
    data = pd.concat(frames, ignore_index=True)
    data = data.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
    data = data.loc[(data.index >= start) & (data.index < end_exclusive), names[1:]]
    expected_index = pd.date_range(start, end_exclusive, freq="1min", inclusive="left")
    observed = int(data.index.nunique())
    coverage = observed / len(expected_index)
    if coverage < minimum_coverage:
        raise SourceGateError(
            f"{symbol} Bybit 1m coverage {coverage:.6%} below {minimum_coverage:.6%}"
        )
    data = data.reindex(expected_index)
    impossible = (
        (data["high"] + EPS < data[["open", "close", "low"]].max(axis=1))
        | (data["low"] - EPS > data[["open", "close", "high"]].min(axis=1))
        | (data[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    if bool(impossible.fillna(False).any()):
        raise SourceGateError(f"{symbol} impossible OHLC rows")
    manifest_hash = sha256_json(hashes)
    return data, coverage, manifest_hash


def parse_metric_timestamp(series: pd.Series) -> pd.DatetimeIndex:
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.DatetimeIndex(pd.to_datetime(series, utc=True, errors="coerce"))
    numeric = pd.to_numeric(series, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    if len(finite) and float(finite.median()) > 1e15:
        unit = "ns"
    elif len(finite) and float(finite.median()) > 1e12:
        unit = "ms"
    elif len(finite) and float(finite.median()) > 1e9:
        unit = "s"
    else:
        return pd.DatetimeIndex(pd.to_datetime(series, utc=True, errors="coerce"))
    return pd.DatetimeIndex(pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce"))


def load_binance_metrics(
    downloader: CachedDownloader,
    symbol: str,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    mirror_pattern: str,
) -> tuple[pd.DataFrame, str]:
    url = mirror_pattern.format(symbol=symbol)
    path = downloader.get(url, f"binance/{symbol}/{symbol}_metrics.parquet", 1024)
    required = [
        "create_time",
        "sum_open_interest",
        "sum_open_interest_value",
        "count_toptrader_long_short_ratio",
        "sum_toptrader_long_short_ratio",
        "count_long_short_ratio",
        "sum_taker_long_short_vol_ratio",
    ]
    frame = pd.read_parquet(path, columns=required)
    frame.index = parse_metric_timestamp(frame.pop("create_time"))
    frame = frame[~frame.index.isna()].sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.loc[(frame.index >= start - pd.Timedelta(days=2)) & (frame.index < end_exclusive)]
    if frame.empty:
        raise SourceGateError(f"{symbol} Binance metrics are empty")
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    expected = len(pd.date_range(start, end_exclusive, freq="5min", inclusive="left"))
    observed = int(frame.loc[frame.index >= start].index.floor("5min").nunique())
    if observed / max(expected, 1) < 0.90:
        raise SourceGateError(f"{symbol} Binance metric clock coverage is below 90%")
    return frame, sha256_file(path)


def load_bybit_funding(
    downloader: CachedDownloader,
    symbol: str,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    endpoint: str,
    cache_dir: Path,
) -> tuple[pd.DataFrame, str]:
    cache_path = cache_dir / "bybit" / symbol / "funding.json"
    if cache_path.exists() and cache_path.stat().st_size > 100:
        payload_rows = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        rows: dict[int, dict[str, Any]] = {}
        cursor_end = int((end_exclusive - pd.Timedelta(milliseconds=1)).timestamp() * 1000)
        start_ms = int(start.timestamp() * 1000)
        while cursor_end >= start_ms:
            payload = downloader.get_json(
                endpoint,
                {
                    "category": "linear",
                    "symbol": symbol,
                    "endTime": cursor_end,
                    "limit": 200,
                },
            )
            if int(payload.get("retCode", -1)) != 0:
                raise SourceGateError(f"{symbol} funding API retCode: {payload}")
            batch = payload.get("result", {}).get("list", [])
            if not batch:
                break
            timestamps: list[int] = []
            for item in batch:
                ts = int(item["fundingRateTimestamp"])
                timestamps.append(ts)
                if start_ms <= ts < int(end_exclusive.timestamp() * 1000):
                    rows[ts] = {
                        "timestamp_ms": ts,
                        "funding_rate": float(item["fundingRate"]),
                    }
            oldest = min(timestamps)
            if oldest <= start_ms:
                break
            if oldest >= cursor_end:
                raise SourceGateError(f"{symbol} funding pagination did not advance")
            cursor_end = oldest - 1
            time.sleep(0.06)
        payload_rows = [rows[key] for key in sorted(rows)]
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload_rows, sort_keys=True), encoding="utf-8")
    if not payload_rows:
        raise SourceGateError(f"{symbol} funding history empty")
    frame = pd.DataFrame(payload_rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
    frame = frame.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
    frame = frame.loc[(frame.index >= start) & (frame.index < end_exclusive), ["funding_rate"]]
    if frame.index.min() > start + pd.Timedelta(hours=12):
        raise SourceGateError(f"{symbol} funding history starts too late: {frame.index.min()}")
    gaps = frame.index.to_series().diff().dropna()
    if len(gaps) and gaps.max() > pd.Timedelta(hours=12, minutes=1):
        raise SourceGateError(f"{symbol} funding history gap exceeds 12h: {gaps.max()}")
    if frame.index.max() < end_exclusive - pd.Timedelta(hours=12):
        raise SourceGateError(f"{symbol} funding history ends too early: {frame.index.max()}")
    return frame, sha256_file(cache_path)


def rolling_z(series: pd.Series, bars: int) -> pd.Series:
    mean = series.rolling(bars, min_periods=max(12, bars // 4)).mean()
    std = series.rolling(bars, min_periods=max(12, bars // 4)).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def build_five_minute_features(
    symbol: str,
    one: pd.DataFrame,
    metrics: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    signal = contract["signal"]
    five = one.resample("5min", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        count=("close", "count"),
    )
    five = five.loc[five["count"] == 5].drop(columns="count")
    previous_close = five["close"].shift(1)
    true_range = pd.concat(
        [
            five["high"] - five["low"],
            (five["high"] - previous_close).abs(),
            (five["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(int(signal["atr_bars"]), min_periods=int(signal["atr_bars"])).mean()
    window = int(signal["external_liquidity_window_bars"])
    five["prior_high"] = five["high"].shift(1).rolling(window, min_periods=window).max()
    five["prior_low"] = five["low"].shift(1).rolling(window, min_periods=window).min()
    five["atr"] = atr
    five["log_return"] = np.log(five["close"]).diff()
    five["volume_z_24h"] = rolling_z(five["volume"], int(signal["rolling_state_bars"]))
    five["return_5m_atr"] = (five["close"] - previous_close) / atr
    five["return_1h_atr"] = (five["close"] - five["close"].shift(12)) / atr
    five["realized_vol_1h"] = five["log_return"].rolling(12, min_periods=12).std(ddof=0)

    metric = metrics.copy()
    oi = metric["sum_open_interest_value"].where(metric["sum_open_interest_value"] > 0)
    metric_features = pd.DataFrame(index=metric.index)
    metric_features["open_interest_log"] = np.log(oi)
    metric_features["open_interest_change_15m"] = np.log(oi).diff(3)
    metric_features["open_interest_change_1h"] = np.log(oi).diff(12)
    metric_features["open_interest_change_6h"] = np.log(oi).diff(72)
    metric_features["open_interest_z_24h"] = rolling_z(np.log(oi), 288)
    aliases = {
        "top_account_ls": "count_toptrader_long_short_ratio",
        "top_position_ls": "sum_toptrader_long_short_ratio",
        "global_account_ls": "count_long_short_ratio",
        "taker_buy_sell_ratio": "sum_taker_long_short_vol_ratio",
    }
    for alias, raw in aliases.items():
        base = metric[raw].where(metric[raw] > 0)
        metric_features[alias] = base
        change_name = alias.replace("_ls", "_change_1h").replace(
            "taker_buy_sell_ratio", "taker_ratio_change_1h"
        )
        z_name = alias.replace("_ls", "_z_24h").replace(
            "taker_buy_sell_ratio", "taker_ratio_z_24h"
        )
        metric_features[change_name] = np.log(base).diff(12)
        metric_features[z_name] = rolling_z(np.log(base), 288)
    metric_features = metric_features.shift(int(contract["data"]["metrics_delay_bars"]))
    metric_features = metric_features.reset_index(names="metric_timestamp")
    five_reset = five.reset_index(names="timestamp")
    merged = pd.merge_asof(
        five_reset.sort_values("timestamp"),
        metric_features.sort_values("metric_timestamp"),
        left_on="timestamp",
        right_on="metric_timestamp",
        direction="backward",
        tolerance=pd.Timedelta(minutes=6),
        allow_exact_matches=True,
    ).set_index("timestamp")
    merged["asset_flag"] = 0.0 if symbol == "BTCUSDT" else 1.0
    return merged


def construct_funding_cumulative(one: pd.DataFrame, funding: pd.DataFrame) -> pd.Series:
    flow = pd.Series(0.0, index=one.index)
    for timestamp, row in funding.iterrows():
        if timestamp not in flow.index:
            continue
        mark = one.at[timestamp, "open"]
        if not np.isfinite(mark):
            nearest = one.loc[:timestamp, "close"].dropna()
            if nearest.empty:
                raise SourceGateError(f"no price for funding settlement {timestamp}")
            mark = float(nearest.iloc[-1])
        flow.at[timestamp] += -float(mark) * float(row["funding_rate"])
    return flow.cumsum()


def load_market(
    symbol: str,
    bybit_files: Sequence[Path],
    downloader: CachedDownloader,
    contract: Mapping[str, Any],
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> MarketData:
    one, coverage, one_hash = parse_bybit_one_minute(
        symbol,
        bybit_files,
        start,
        end_exclusive,
        float(contract["data"]["minimum_one_minute_coverage"]),
    )
    metrics, metrics_hash = load_binance_metrics(
        downloader,
        symbol,
        start,
        end_exclusive,
        contract["data"]["binance_metrics_mirror_pattern"],
    )
    funding, funding_hash = load_bybit_funding(
        downloader,
        symbol,
        start,
        end_exclusive,
        contract["data"]["bybit_funding_endpoint"],
        downloader.cache_dir,
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
