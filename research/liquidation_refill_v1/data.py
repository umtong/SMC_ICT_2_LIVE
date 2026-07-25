from __future__ import annotations

import csv
import gzip
import shutil
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from core import PriceSeries, ResearchError, SourceRecord, sha256_file

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trade_count", "taker_buy_base",
    "taker_buy_quote", "ignore",
]

def atomic_download(url: str, path: Path, *, retries: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return
    tmp = path.with_suffix(path.suffix + ".part")
    headers = {"User-Agent": "SMC-ICT-2-LIVE-liquidation-research/1.0"}
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as response, tmp.open("wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            if tmp.stat().st_size <= 0:
                raise ResearchError(f"empty download: {url}")
            tmp.replace(path)
            return
        except Exception as exc:  # pragma: no cover - exercised in Actions network path
            last = exc
            tmp.unlink(missing_ok=True)
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise ResearchError(f"download failed after {retries} attempts: {url}: {last}")


def read_text_url(url: str, *, retries: int = 4) -> str:
    headers = {"User-Agent": "SMC-ICT-2-LIVE-liquidation-research/1.0"}
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read().decode("utf-8")
        except Exception as exc:  # pragma: no cover
            last = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise ResearchError(f"text download failed: {url}: {last}")


def tardis_url(d: date) -> str:
    return (
        "https://datasets.tardis.dev/v1/binance-futures/liquidations/"
        f"{d.year:04d}/{d.month:02d}/{d.day:02d}/PERPETUALS.csv.gz"
    )


def binance_kline_url(symbol: str, d: date) -> str:
    ds = d.isoformat()
    return (
        "https://data.binance.vision/data/futures/um/daily/klines/"
        f"{symbol}/1m/{symbol}-1m-{ds}.zip"
    )


def download_liquidation_day(d: date, cache: Path) -> SourceRecord:
    url = tardis_url(d)
    path = cache / "tardis" / f"binance-futures_liquidations_{d.isoformat()}_PERPETUALS.csv.gz"
    atomic_download(url, path)
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            row_count = sum(1 for _ in reader)
    except Exception as exc:
        raise ResearchError(f"invalid liquidation gzip {path}: {exc}") from exc
    required = {"exchange", "symbol", "timestamp", "local_timestamp", "side", "price", "amount"}
    if not required.issubset(set(header)):
        raise ResearchError(f"unexpected liquidation schema {header}")
    return SourceRecord(
        source_type="liquidations",
        exchange="binance-futures",
        symbol="PERPETUALS",
        data_date=d.isoformat(),
        url=url,
        path=str(path),
        bytes=path.stat().st_size,
        sha256=sha256_file(path),
        checksum_verified=False,
        row_count=row_count,
    )


def download_kline_day(symbol: str, d: date, cache: Path) -> SourceRecord:
    url = binance_kline_url(symbol, d)
    path = cache / "binance_vision" / symbol / f"{symbol}-1m-{d.isoformat()}.zip"
    atomic_download(url, path)
    checksum_url = url + ".CHECKSUM"
    checksum_text = read_text_url(checksum_url)
    expected = checksum_text.strip().split()[0].lower()
    actual = sha256_file(path)
    if len(expected) != 64 or actual != expected:
        raise ResearchError(
            f"checksum mismatch for {url}: expected={expected!r} actual={actual}"
        )
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != 1:
                raise ResearchError(f"unexpected kline zip members for {path}: {names}")
            with archive.open(names[0]) as fh:
                row_count = sum(1 for _ in fh)
    except Exception as exc:
        raise ResearchError(f"invalid kline zip {path}: {exc}") from exc
    return SourceRecord(
        source_type="klines_1m",
        exchange="binance-futures-official-vision",
        symbol=symbol,
        data_date=d.isoformat(),
        url=url,
        path=str(path),
        bytes=path.stat().st_size,
        sha256=actual,
        checksum_verified=True,
        row_count=row_count,
    )


def download_period_sources(
    dates: Sequence[date], assets: Sequence[str], cache: Path
) -> tuple[list[SourceRecord], dict[date, Path], dict[tuple[str, date], Path]]:
    records: list[SourceRecord] = []
    liq_paths: dict[date, Path] = {}
    kline_paths: dict[tuple[str, date], Path] = {}

    with ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {pool.submit(download_liquidation_day, d, cache): ("liq", d) for d in dates}
        for future in as_completed(future_map):
            _, d = future_map[future]
            record = future.result()
            records.append(record)
            liq_paths[d] = Path(record.path)

    price_dates = sorted({d + timedelta(days=offset) for d in dates for offset in (0, 1)})
    with ThreadPoolExecutor(max_workers=10) as pool:
        future_map = {
            pool.submit(download_kline_day, symbol, d, cache): (symbol, d)
            for symbol in assets
            for d in price_dates
        }
        for future in as_completed(future_map):
            symbol, d = future_map[future]
            record = future.result()
            records.append(record)
            kline_paths[(symbol, d)] = Path(record.path)

    records.sort(key=lambda r: (r.data_date, r.source_type, r.symbol))
    return records, liq_paths, kline_paths


def load_liquidations(paths: Mapping[date, Path], assets: Sequence[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    row_offset = 0
    for d, path in sorted(paths.items()):
        frame = pd.read_csv(
            path,
            compression="gzip",
            dtype={"exchange": "string", "symbol": "string", "id": "string", "side": "string"},
        )
        required = {"symbol", "timestamp", "local_timestamp", "side", "price", "amount"}
        if not required.issubset(frame.columns):
            raise ResearchError(f"missing liquidation columns in {path}")
        frame = frame.loc[frame["symbol"].isin(assets)].copy()
        frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
        frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
        frame["local_timestamp"] = pd.to_numeric(frame["local_timestamp"], errors="coerce")
        frame = frame.dropna(subset=["price", "amount", "local_timestamp", "side"])
        frame = frame.loc[(frame["price"] > 0) & (frame["amount"] > 0)]
        frame["row_order"] = np.arange(row_offset, row_offset + len(frame), dtype=np.int64)
        row_offset += len(frame)
        frame["event_time"] = pd.to_datetime(frame["local_timestamp"], unit="us", utc=True)
        frame["minute"] = frame["event_time"].dt.floor("min")
        frame["notional"] = frame["price"] * frame["amount"]
        frame["force_direction"] = frame["side"].map({"buy": 1, "sell": -1})
        frame = frame.dropna(subset=["force_direction"])
        frame["force_direction"] = frame["force_direction"].astype(int)
        frame["source_date"] = d.isoformat()
        frames.append(frame)
    if not frames:
        raise ResearchError("no liquidation rows loaded")
    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["event_time", "row_order"], kind="stable").reset_index(drop=True)
    return out


def _normalize_epoch(values: pd.Series) -> pd.DatetimeIndex:
    numeric = pd.to_numeric(values, errors="coerce")
    max_value = float(numeric.dropna().max())
    unit = "us" if max_value >= 1e14 else "ms"
    return pd.to_datetime(numeric, unit=unit, utc=True)


def load_klines(paths: Mapping[tuple[str, date], Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for (symbol, d), path in sorted(paths.items(), key=lambda item: (item[0][0], item[0][1])):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != 1:
                raise ResearchError(f"unexpected kline members: {path}")
            with archive.open(names[0]) as fh:
                frame = pd.read_csv(fh, header=None, names=KLINE_COLUMNS)
        # Some newer archives may include a header row. Numeric coercion removes it safely.
        for column in ("open_time", "open", "high", "low", "close"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["open_time", "open", "high", "low", "close"])
        frame["minute"] = _normalize_epoch(frame["open_time"])
        frame["symbol"] = symbol
        frame["source_date"] = d.isoformat()
        frames.append(frame[["symbol", "minute", "open", "high", "low", "close", "source_date"]])
    if not frames:
        raise ResearchError("no kline rows loaded")
    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["symbol", "minute"], kind="stable").drop_duplicates(
        ["symbol", "minute"], keep="last"
    )
    if bool((out[["open", "high", "low", "close"]] <= 0).any().any()):
        raise ResearchError("non-positive kline price")
    return out.reset_index(drop=True)


def aggregate_liquidations(liquidations: pd.DataFrame) -> pd.DataFrame:
    work = liquidations.copy()
    work["buy_notional"] = np.where(work["force_direction"] > 0, work["notional"], 0.0)
    work["sell_notional"] = np.where(work["force_direction"] < 0, work["notional"], 0.0)
    work["buy_count"] = (work["force_direction"] > 0).astype(int)
    work["sell_count"] = (work["force_direction"] < 0).astype(int)
    grouped = (
        work.groupby(["symbol", "minute"], sort=True)
        .agg(
            buy_notional=("buy_notional", "sum"),
            sell_notional=("sell_notional", "sum"),
            buy_count=("buy_count", "sum"),
            sell_count=("sell_count", "sum"),
            first_event_time=("event_time", "min"),
            last_event_time=("event_time", "max"),
        )
        .reset_index()
    )
    return grouped


def build_features(
    liquidations: pd.DataFrame,
    klines: pd.DataFrame,
    signal_dates: Sequence[date],
    assets: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    aggregated = aggregate_liquidations(liquidations)
    signal_date_set = {d.isoformat() for d in signal_dates}
    feature_frames: list[pd.DataFrame] = []

    for symbol in assets:
        symbol_prices = klines.loc[klines["symbol"] == symbol].copy()
        symbol_liq = aggregated.loc[aggregated["symbol"] == symbol].copy()
        for d in signal_dates:
            start = pd.Timestamp(d, tz="UTC")
            end = start + pd.Timedelta(days=1)
            price_day = symbol_prices.loc[
                (symbol_prices["minute"] >= start) & (symbol_prices["minute"] < end)
            ].copy()
            if len(price_day) < 1400:
                raise ResearchError(f"incomplete one-minute price day: {symbol} {d}: {len(price_day)}")
            liq_day = symbol_liq.loc[
                (symbol_liq["minute"] >= start) & (symbol_liq["minute"] < end)
            ].copy()
            merged = price_day.merge(liq_day, on=["symbol", "minute"], how="left")
            for column in ("buy_notional", "sell_notional", "buy_count", "sell_count"):
                merged[column] = merged[column].fillna(0.0)
            merged["abs_notional"] = merged["buy_notional"] + merged["sell_notional"]
            merged["signed_notional"] = merged["buy_notional"] - merged["sell_notional"]
            merged["force_direction"] = np.sign(merged["signed_notional"]).astype(int)
            merged["dominant_notional"] = np.maximum(
                merged["buy_notional"], merged["sell_notional"]
            )
            merged["dominance"] = np.where(
                merged["abs_notional"] > 0,
                np.abs(merged["signed_notional"]) / merged["abs_notional"],
                0.0,
            )
            buy_prev = merged["buy_notional"].shift(1).rolling(3, min_periods=1).mean()
            sell_prev = merged["sell_notional"].shift(1).rolling(3, min_periods=1).mean()
            prev_same = np.where(merged["force_direction"] > 0, buy_prev, sell_prev)
            # Denominator uses prior completed minutes only. A fixed one-USDT floor avoids
            # allowing a future same-day liquidation to alter an earlier feature.
            merged["acceleration"] = merged["dominant_notional"] / (
                np.nan_to_num(prev_same, nan=0.0) + 1.0
            )
            range_ = np.maximum(merged["high"] - merged["low"], merged["open"] * 1e-9)
            merged["directional_return_bps"] = (
                merged["force_direction"] * np.log(merged["close"] / merged["open"]) * 1e4
            )
            merged["close_location"] = np.where(
                merged["force_direction"] > 0,
                (merged["close"] - merged["low"]) / range_,
                (merged["high"] - merged["close"]) / range_,
            )
            merged["next_buy_notional"] = merged["buy_notional"].shift(-1)
            merged["next_sell_notional"] = merged["sell_notional"].shift(-1)
            merged["next_open"] = merged["open"].shift(-1)
            merged["next_high"] = merged["high"].shift(-1)
            merged["next_low"] = merged["low"].shift(-1)
            merged["next_close"] = merged["close"].shift(-1)
            merged["entry_open_continuation"] = merged["open"].shift(-1)
            merged["entry_open_reversal"] = merged["open"].shift(-2)
            next_same = np.where(
                merged["force_direction"] > 0,
                merged["next_buy_notional"],
                merged["next_sell_notional"],
            )
            merged["deceleration"] = next_same / np.maximum(
                merged["dominant_notional"], 1.0
            )
            combined_high = np.maximum(merged["high"], merged["next_high"])
            combined_low = np.minimum(merged["low"], merged["next_low"])
            combined_range = np.maximum(combined_high - combined_low, merged["open"] * 1e-9)
            merged["recovery"] = np.where(
                merged["force_direction"] > 0,
                (combined_high - merged["next_close"]) / combined_range,
                (merged["next_close"] - combined_low) / combined_range,
            )
            merged["event_high_continuation"] = merged["high"]
            merged["event_low_continuation"] = merged["low"]
            merged["event_high_reversal"] = combined_high
            merged["event_low_reversal"] = combined_low
            merged["event_date"] = d.isoformat()
            merged["continuation_entry_time"] = merged["minute"] + pd.Timedelta(minutes=1)
            merged["reversal_entry_time"] = merged["minute"] + pd.Timedelta(minutes=2)
            merged["reversal_decision_time"] = merged["minute"] + pd.Timedelta(minutes=1)
            feature_frames.append(merged)

    features = pd.concat(feature_frames, ignore_index=True)
    features = features.loc[features["event_date"].isin(signal_date_set)].copy()
    features = features.sort_values(["minute", "symbol"], kind="stable").reset_index(drop=True)
    positive_minutes = features.loc[features["dominant_notional"] > 0].copy()
    if positive_minutes.empty:
        raise ResearchError("no target-asset liquidation minutes")
    return features, positive_minutes


def threshold_table(positive_fit: pd.DataFrame, quantiles: Sequence[float]) -> dict[float, dict[str, float]]:
    out: dict[float, dict[str, float]] = {}
    for q in quantiles:
        q_map: dict[str, float] = {}
        for symbol, group in positive_fit.groupby("symbol"):
            values = group["dominant_notional"].to_numpy(float)
            if len(values) < 20:
                raise ResearchError(f"insufficient positive liquidation minutes for {symbol}: {len(values)}")
            q_map[str(symbol)] = float(np.quantile(values, q, method="higher"))
        out[float(q)] = q_map
    return out


def make_price_series(klines: pd.DataFrame) -> dict[str, PriceSeries]:
    return {
        str(symbol): PriceSeries.from_frame(group)
        for symbol, group in klines.groupby("symbol", sort=True)
    }
