from __future__ import annotations

import hashlib
import io
import re
import time
import zipfile
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests


BINANCE_VISION_BASE = "https://data.binance.vision/data/futures/um/monthly"
BAR_MS = 5 * 60 * 1000
FEATURE_COLUMNS = ["return_z", "range_z", "body_efficiency", "wick_skew", "flow_imbalance"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def months_for_years(years: Iterable[int]) -> list[str]:
    return [f"{year:04d}-{month:02d}" for year in sorted(set(int(x) for x in years)) for month in range(1, 13)]


def _request(session: requests.Session, url: str, stream: bool = False) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            response = session.get(url, timeout=(20, 180), stream=stream)
            response.raise_for_status()
            return response
        except Exception as exc:  # pragma: no cover - network retry path
            last_error = exc
            if attempt == 4:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def download_verified(
    session: requests.Session,
    url: str,
    destination: Path,
    kind: str,
    symbol: str,
    month: str,
    records: list[dict[str, object]],
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    checksum_response = _request(session, url + ".CHECKSUM")
    checksum_text = checksum_response.text.strip()
    match = re.search(r"\b([0-9a-fA-F]{64})\b", checksum_text)
    if match is None:
        raise RuntimeError(f"official checksum missing for {url}")
    expected = match.group(1).lower()

    valid_cache = destination.exists() and sha256_file(destination) == expected
    if not valid_cache:
        temporary = destination.with_suffix(destination.suffix + ".part")
        if temporary.exists():
            temporary.unlink()
        response = _request(session, url, stream=True)
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        actual = sha256_file(temporary)
        if actual != expected:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"SHA-256 mismatch for {url}: {actual} != {expected}")
        temporary.replace(destination)

    records.append(
        {
            "kind": kind,
            "symbol": symbol,
            "month": month,
            "url": url,
            "sha256": expected,
            "compressed_bytes": int(destination.stat().st_size),
        }
    )
    return destination


def _zip_csv_bytes(path: Path) -> bytes:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != 1:
            raise RuntimeError(f"unexpected ZIP inventory for {path}: {names}")
        return archive.read(names[0])


def _normalize_ms(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").astype("float64")
    finite = numeric[np.isfinite(numeric)]
    if finite.empty:
        return numeric.astype("Int64")
    median = float(finite.median())
    while median > 1e14:
        numeric /= 1000.0
        median /= 1000.0
    return numeric.round().astype("Int64")


def parse_kline_zip(path: Path) -> pd.DataFrame:
    raw = _zip_csv_bytes(path)
    frame = pd.read_csv(io.BytesIO(raw), header=None, low_memory=False)
    if frame.empty:
        raise RuntimeError(f"empty kline archive: {path}")
    if not re.fullmatch(r"\d+", str(frame.iloc[0, 0]).strip()):
        frame = frame.iloc[1:].reset_index(drop=True)
    if frame.shape[1] < 11:
        raise RuntimeError(f"unexpected kline width {frame.shape[1]} in {path}")
    frame = frame.iloc[:, :12].copy()
    frame.columns = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trade_count",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore",
    ]
    frame["open_time"] = _normalize_ms(frame["open_time"])
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trade_count",
        "taker_buy_base",
        "taker_buy_quote",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open_time", "open", "high", "low", "close", "quote_volume", "taker_buy_quote"])
    frame["open_time"] = frame["open_time"].astype("int64")
    frame = frame.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise RuntimeError(f"non-positive price in {path}")
    return frame[
        [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "quote_volume",
            "trade_count",
            "taker_buy_quote",
        ]
    ]


def parse_funding_zip(path: Path) -> pd.DataFrame:
    raw = _zip_csv_bytes(path)
    with_header = pd.read_csv(io.BytesIO(raw), low_memory=False)
    lower = {str(column).lower(): column for column in with_header.columns}
    timestamp_name = next(
        (lower[name] for name in ("calc_time", "funding_time", "timestamp", "time") if name in lower),
        None,
    )
    rate_name = next(
        (lower[name] for name in ("last_funding_rate", "funding_rate", "rate") if name in lower),
        None,
    )
    if timestamp_name is None or rate_name is None:
        no_header = pd.read_csv(io.BytesIO(raw), header=None, low_memory=False)
        if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", str(no_header.iloc[0, 0]).strip()):
            no_header = no_header.iloc[1:].reset_index(drop=True)
        if no_header.shape[1] < 2:
            raise RuntimeError(f"unexpected funding archive width in {path}")
        timestamp = no_header.iloc[:, 0]
        rate = no_header.iloc[:, -1]
    else:
        timestamp = with_header[timestamp_name]
        rate = with_header[rate_name]

    frame = pd.DataFrame({"funding_time": _normalize_ms(timestamp), "funding_rate": pd.to_numeric(rate, errors="coerce")})
    frame = frame.dropna().copy()
    frame["funding_time"] = frame["funding_time"].astype("int64")
    frame = frame.sort_values("funding_time").drop_duplicates("funding_time", keep="last").reset_index(drop=True)
    if (frame["funding_rate"].abs() > 0.05).any():
        raise RuntimeError(f"implausible funding rate in {path}")
    return frame


def load_market_data(
    symbols: list[str],
    bar_years: list[int],
    funding_years: list[int],
    cache_root: Path,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, object]]:
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-ML-PO3-causal-research/1.0"})
    records: list[dict[str, object]] = []
    bars: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}

    bar_months = months_for_years(bar_years)
    funding_months = months_for_years(funding_years)
    for symbol in symbols:
        monthly_bars: list[pd.DataFrame] = []
        for month in bar_months:
            filename = f"{symbol}-5m-{month}.zip"
            url = f"{BINANCE_VISION_BASE}/klines/{symbol}/5m/{filename}"
            path = download_verified(
                session,
                url,
                cache_root / "klines" / symbol / filename,
                "kline_5m",
                symbol,
                month,
                records,
            )
            parsed = parse_kline_zip(path)
            records[-1]["parsed_rows"] = int(len(parsed))
            monthly_bars.append(parsed)
        combined = pd.concat(monthly_bars, ignore_index=True)
        combined = combined.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)
        bars[symbol] = combined

        monthly_funding: list[pd.DataFrame] = []
        for month in funding_months:
            filename = f"{symbol}-fundingRate-{month}.zip"
            url = f"{BINANCE_VISION_BASE}/fundingRate/{symbol}/{filename}"
            path = download_verified(
                session,
                url,
                cache_root / "funding" / symbol / filename,
                "funding_rate",
                symbol,
                month,
                records,
            )
            parsed = parse_funding_zip(path)
            records[-1]["parsed_rows"] = int(len(parsed))
            monthly_funding.append(parsed)
        if monthly_funding:
            combined_funding = pd.concat(monthly_funding, ignore_index=True)
            combined_funding = combined_funding.sort_values("funding_time").drop_duplicates("funding_time", keep="last").reset_index(drop=True)
        else:
            combined_funding = pd.DataFrame(columns=["funding_time", "funding_rate"])
        funding[symbol] = combined_funding

    manifest = {
        "provider": "Binance Vision official USD-M monthly archive",
        "records": records,
        "record_count": len(records),
        "symbols": symbols,
        "bar_years": sorted(set(bar_years)),
        "funding_years": sorted(set(funding_years)),
        "total_compressed_bytes": int(sum(int(record["compressed_bytes"]) for record in records)),
        "orders_submitted": False,
    }
    return bars, funding, manifest


def build_feature_frame(bars: pd.DataFrame) -> pd.DataFrame:
    source = bars.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True).copy()
    gap = source["open_time"].diff().fillna(BAR_MS).ne(BAR_MS)
    source["segment"] = gap.cumsum().astype("int64")
    pieces: list[pd.DataFrame] = []

    for _, segment in source.groupby("segment", sort=False):
        part = segment.copy().reset_index(drop=True)
        previous_close = part["close"].shift(1)
        log_return = np.log(part["close"] / previous_close)
        log_range = np.log(part["high"] / part["low"])
        price_range = (part["high"] - part["low"]).replace(0.0, np.nan)
        body_efficiency = (part["close"] - part["open"]) / price_range
        upper_wick = part["high"] - np.maximum(part["open"], part["close"])
        lower_wick = np.minimum(part["open"], part["close"]) - part["low"]
        wick_skew = (upper_wick - lower_wick) / price_range
        flow_imbalance = 2.0 * part["taker_buy_quote"] / part["quote_volume"].replace(0.0, np.nan) - 1.0

        return_scale = log_return.rolling(288, min_periods=96).std(ddof=0).shift(1)
        range_scale = log_range.rolling(288, min_periods=96).median().shift(1)
        part["return_z"] = (log_return / return_scale.replace(0.0, np.nan)).clip(-10.0, 10.0)
        part["range_z"] = (log_range / range_scale.replace(0.0, np.nan)).clip(0.0, 10.0)
        part["body_efficiency"] = body_efficiency.clip(-1.0, 1.0)
        part["wick_skew"] = wick_skew.clip(-1.0, 1.0)
        part["flow_imbalance"] = flow_imbalance.clip(-1.0, 1.0)
        pieces.append(part)

    frame = pd.concat(pieces, ignore_index=True)
    frame["bar_end"] = frame["open_time"] + BAR_MS
    frame = frame.dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)
    if not np.isfinite(frame[FEATURE_COLUMNS].to_numpy(dtype=np.float64)).all():
        raise RuntimeError("non-finite feature frame")
    return frame


def stage_frame(frame: pd.DataFrame, start_ms: int, end_ms: int) -> pd.DataFrame:
    selected = frame.loc[(frame["open_time"] >= int(start_ms)) & (frame["open_time"] <= int(end_ms))].copy()
    return selected.sort_values("open_time").reset_index(drop=True)


def split_contiguous(frame: pd.DataFrame) -> list[pd.DataFrame]:
    if frame.empty:
        return []
    ordered = frame.sort_values("open_time").reset_index(drop=True)
    group = ordered["open_time"].diff().fillna(BAR_MS).ne(BAR_MS).cumsum()
    return [part.reset_index(drop=True) for _, part in ordered.groupby(group, sort=False) if len(part) >= 2]
