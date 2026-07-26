from __future__ import annotations

import argparse
import calendar
import gzip
import hashlib
import io
import json
import math
import os
import platform
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingRegressor

CLAIM_ID = "CLM-20260726-2122-ML-DONCHIAN-TAIL-001"
RESULT_ID = "RES-20260726-ML-DONCHIAN-TAIL-001"
EXPERIMENT_ID = "ML-DONCHIAN-CONVEX-TAIL-SELECT-V1"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
SYMBOL_CODE = {symbol: index for index, symbol in enumerate(SYMBOLS)}
PRE_START = pd.Timestamp("2021-01-01T00:00:00Z")
PRE_END = pd.Timestamp("2024-01-01T00:00:00Z")
TRAIN_END = pd.Timestamp("2022-07-01T00:00:00Z")
CAL_END = pd.Timestamp("2023-01-01T00:00:00Z")
CONF_END = PRE_END
VALIDATION_END = pd.Timestamp("2024-07-01T00:00:00Z")
ENTRY_LB = 96
EXIT_LB = 48
ATR_LB = 20
STOP_ATR = 2.0
ROUND_TRIP_COSTS_BPS = (12.0, 18.0, 24.0)
BASE_RISK_FRACTION = 0.005
BASE_NOTIONAL_CAP = 5.0
ADVERSE_FUNDING_BPS_PER_8H = 1.0
CURRENT_RANK_ONE_24BP_GROWTH = 0.0007001887213879954
RISK_FRACTIONS = (0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.20, 0.30, 0.45, 0.60)
NOTIONAL_CAPS = (1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 50.0, 100.0)
FEATURE_COLUMNS = (
    "symbol_code",
    "side",
    "breakout_strength_atr",
    "channel_width_atr",
    "opposite_distance_atr",
    "atr_pct",
    "compression_ratio",
    "signed_ret_1h",
    "signed_ret_4h",
    "signed_ret_24h",
    "signed_efficiency_24h",
    "signed_trend_distance_atr",
    "volume_z20",
    "cross_asset_breadth",
    "same_side_breakout_count",
    "signed_btc_ret24",
    "signed_eth_ret24",
    "utc_hour_sin",
    "utc_hour_cos",
)


class ResearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Event:
    event_key: str
    symbol: str
    side: int
    signal_idx: int
    entry_idx: int
    exit_idx: int
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    stop_price: float
    exit_reason: str
    gross_return: float
    score: float
    stop_fraction: float
    funding_boundaries: int
    target_r_24bp: float
    features: dict[str, float]


@dataclass(frozen=True)
class PathConfig:
    risk_fraction: float
    notional_cap: float
    round_trip_cost_bps: float


@dataclass
class PathResult:
    config: dict[str, float]
    final_nav: float
    total_return: float
    geometric_daily_growth: float
    maximum_drawdown: float
    trade_count: int
    positive_trade_count: int
    mean_account_return_bps: float | None
    median_account_return_bps: float | None
    profit_factor: float | None
    win_rate: float | None
    top5_positive_share: float
    h1_return: float
    h2_return: float
    ruined: bool
    source_gap_stop_count: int
    gap_stop_count: int
    stop_count: int
    channel_exit_count: int
    trade_records: list[dict[str, Any]]
    daily_nav: dict[str, float]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_months(start: pd.Timestamp, end_exclusive: pd.Timestamp) -> Iterable[tuple[int, int]]:
    cursor = pd.Timestamp(year=start.year, month=start.month, day=1, tz="UTC")
    while cursor < end_exclusive:
        yield cursor.year, cursor.month
        cursor = cursor + pd.offsets.MonthBegin(1)


def month_url(symbol: str, year: int, month: int) -> str:
    if year >= 2025:
        raise ResearchError(f"Prohibited source year requested: {year}")
    last = calendar.monthrange(year, month)[1]
    name = f"{symbol}_5_{year:04d}-{month:02d}-01_{year:04d}-{month:02d}-{last:02d}.csv.gz"
    return f"https://public.bybit.com/kline_for_metatrader4/{symbol}/{year:04d}/{name}"


def download(url: str, target: Path, retries: int = 5) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 100:
        return {"url": url, "path": str(target), "bytes": target.stat().st_size, "sha256": sha256_file(target), "cached": True}
    temporary = target.with_suffix(target.suffix + ".part")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            if temporary.exists():
                temporary.unlink()
            with requests.get(url, stream=True, timeout=(30, 240), headers={"User-Agent": "SMC-ICT-2-LIVE/ml-donchian-tail-r13"}) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            if temporary.stat().st_size <= 100:
                raise ResearchError(f"Downloaded file is unexpectedly small: {url}")
            temporary.replace(target)
            return {"url": url, "path": str(target), "bytes": target.stat().st_size, "sha256": sha256_file(target), "cached": False}
        except Exception as exc:  # pragma: no cover - network retry
            last = exc
            if attempt + 1 < retries:
                time.sleep(min(2**attempt, 16))
    raise ResearchError(f"Download failed: {url}: {last}")


def _looks_like_header(row: Sequence[Any]) -> bool:
    text = " ".join(str(item).lower() for item in row)
    return any(token in text for token in ("date", "time", "open", "high", "low", "close"))


def parse_mt4_csv_gz(payload: bytes, symbol: str) -> pd.DataFrame:
    try:
        raw = gzip.decompress(payload)
    except Exception as exc:
        raise ResearchError(f"Invalid gzip for {symbol}: {exc}") from exc
    sample = raw[:4096].decode("utf-8", errors="replace")
    separator = "\t" if sample.count("\t") > sample.count(",") else ","
    frame = pd.read_csv(io.BytesIO(raw), sep=separator, header=None, engine="python", dtype=str)
    frame = frame.dropna(axis=1, how="all")
    if frame.empty:
        raise ResearchError(f"Empty MT4 file for {symbol}")
    if _looks_like_header(frame.iloc[0].tolist()):
        frame = frame.iloc[1:].reset_index(drop=True)
    first = frame.iloc[:, 0].astype(str).str.strip()
    second = frame.iloc[:, 1].astype(str).str.strip() if frame.shape[1] > 1 else pd.Series("", index=frame.index)
    two_column_datetime = second.str.contains(":", regex=False).mean() > 0.5
    if two_column_datetime:
        timestamp = pd.to_datetime(first + " " + second, utc=True, errors="coerce")
        price_start = 2
    else:
        numeric = pd.to_numeric(first, errors="coerce")
        median = float(numeric.dropna().median()) if numeric.notna().any() else math.nan
        if math.isfinite(median) and median > 1e12:
            timestamp = pd.to_datetime(numeric, unit="ms", utc=True, errors="coerce")
        elif math.isfinite(median) and median > 1e9:
            timestamp = pd.to_datetime(numeric, unit="s", utc=True, errors="coerce")
        else:
            timestamp = pd.to_datetime(first, utc=True, errors="coerce")
        price_start = 1
    if frame.shape[1] < price_start + 4:
        raise ResearchError(f"Missing OHLC columns for {symbol}")
    values = {name: pd.to_numeric(frame.iloc[:, price_start + offset], errors="coerce") for offset, name in enumerate(("open", "high", "low", "close"))}
    volume = pd.Series(1.0, index=frame.index)
    for index in range(price_start + 4, frame.shape[1]):
        candidate = pd.to_numeric(frame.iloc[:, index], errors="coerce")
        if candidate.notna().mean() > 0.8 and float(candidate.fillna(0).abs().sum()) > 0:
            volume = candidate.abs()
            break
    output = pd.DataFrame({"timestamp": timestamp, **values, "volume": volume})
    output = output.dropna(subset=["timestamp", "open", "high", "low", "close"])
    output = output[(output[["open", "high", "low", "close"]] > 0).all(axis=1)]
    output = output[(output["high"] >= output[["open", "close"]].max(axis=1)) & (output["low"] <= output[["open", "close"]].min(axis=1))]
    output = output.sort_values("timestamp").drop_duplicates("timestamp", keep="last").set_index("timestamp")
    output.index = pd.DatetimeIndex(output.index).tz_convert("UTC")
    output["volume"] = output["volume"].fillna(0.0)
    if output.empty:
        raise ResearchError(f"No valid MT4 rows for {symbol}")
    return output


def load_five_minute(symbol: str, start: pd.Timestamp, end_exclusive: pd.Timestamp, cache: Path, manifest: list[dict[str, Any]]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for year, month in iter_months(start, end_exclusive):
        url = month_url(symbol, year, month)
        target = cache / "klines" / symbol / url.rsplit("/", 1)[-1]
        record = download(url, target)
        record.update({"symbol": symbol, "year": year, "month": month})
        manifest.append(record)
        parts.append(parse_mt4_csv_gz(target.read_bytes(), symbol))
    merged = pd.concat(parts).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    merged = merged[(merged.index >= start) & (merged.index < end_exclusive)]
    expected = pd.date_range(start.floor("5min"), end_exclusive - pd.Timedelta(minutes=5), freq="5min")
    observed = merged.reindex(expected)
    observed["valid"] = observed[["open", "high", "low", "close"]].notna().all(axis=1)
    missing = expected[~observed["valid"].to_numpy()]
    manifest.append({
        "symbol": symbol,
        "kind": "assembled_5m_grid",
        "start": start.isoformat(),
        "end_exclusive": end_exclusive.isoformat(),
        "expected_rows": int(len(expected)),
        "observed_rows": int(observed["valid"].sum()),
        "missing_rows": int((~observed["valid"]).sum()),
        "first_missing": None if len(missing) == 0 else missing[0].isoformat(),
        "last_missing": None if len(missing) == 0 else missing[-1].isoformat(),
        "gap_policy": "NO_IMPUTATION_RESET_ROLLING_STATE_AND_ADVERSE_OPEN_POSITION_GAP",
    })
    return observed


def aggregate_hourly(frame: pd.DataFrame) -> pd.DataFrame:
    expected_start = frame.index[0].floor("1h")
    expected_end = (frame.index[-1] + pd.Timedelta(minutes=5)).ceil("1h")
    index = pd.date_range(expected_start, expected_end - pd.Timedelta(hours=1), freq="1h")
    groups = frame.resample("1h", label="left", closed="left")
    output = pd.DataFrame(index=index)
    output["open"] = groups["open"].first().reindex(index)
    output["high"] = groups["high"].max().reindex(index)
    output["low"] = groups["low"].min().reindex(index)
    output["close"] = groups["close"].last().reindex(index)
    output["volume"] = groups["volume"].sum(min_count=12).reindex(index)
    count = groups["valid"].sum().reindex(index).fillna(0)
    output["valid"] = count.eq(12) & output[["open", "high", "low", "close"]].notna().all(axis=1)
    output.loc[~output["valid"], ["open", "high", "low", "close", "volume"]] = np.nan
    return output


def true_range(frame: pd.DataFrame) -> pd.Series:
    previous = frame["close"].shift(1)
    values = pd.concat([(frame["high"] - frame["low"]), (frame["high"] - previous).abs(), (frame["low"] - previous).abs()], axis=1).max(axis=1)
    return values.where(frame["valid"] & frame["valid"].shift(1, fill_value=False))


def continuous_log_return(close: pd.Series, valid: pd.Series, periods: int) -> pd.Series:
    complete = valid.astype("int8").rolling(periods + 1, min_periods=periods + 1).sum().eq(periods + 1)
    return np.log(close).diff(periods).where(complete)


def rolling_z(series: pd.Series, valid: pd.Series, window: int) -> pd.Series:
    complete = valid.astype("int8").rolling(window, min_periods=window).sum().eq(window)
    mean = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std(ddof=0).replace(0, np.nan)
    return ((series - mean) / std).where(complete)


def prior_extreme(series: pd.Series, valid: pd.Series, window: int, mode: str) -> pd.Series:
    shifted = series.shift(1)
    complete = valid.shift(1, fill_value=False).astype("int8").rolling(window, min_periods=window).sum().eq(window)
    rolling = shifted.rolling(window, min_periods=window)
    result = rolling.max() if mode == "max" else rolling.min()
    return result.where(complete)


def count_funding_boundaries(entry: pd.Timestamp, exit_: pd.Timestamp) -> int:
    if exit_ <= entry:
        return 0
    cursor = entry.floor("8h") + pd.Timedelta(hours=8)
    count = 0
    while cursor <= exit_:
        count += 1
        cursor += pd.Timedelta(hours=8)
    return count


def exit_path(frame: pd.DataFrame, entry_idx: int, entry_price: float, side: int, stop: float, exit_low: pd.Series, exit_high: pd.Series, last_idx: int | None = None) -> tuple[int, pd.Timestamp, float, str]:
    last = len(frame) - 1 if last_idx is None else min(last_idx, len(frame) - 1)
    for index in range(entry_idx, last + 1):
        row = frame.iloc[index]
        timestamp = frame.index[index]
        if not bool(row["valid"]):
            return index, timestamp, float(stop), "source_gap_stop"
        open_, high, low, close = map(float, (row["open"], row["high"], row["low"], row["close"]))
        if side > 0:
            if open_ <= stop:
                return index, timestamp, open_, "gap_stop"
            if low <= stop:
                return index, timestamp, float(stop), "stop"
            channel_hit = math.isfinite(float(exit_low.iloc[index])) and close < float(exit_low.iloc[index])
        else:
            if open_ >= stop:
                return index, timestamp, open_, "gap_stop"
            if high >= stop:
                return index, timestamp, float(stop), "stop"
            channel_hit = math.isfinite(float(exit_high.iloc[index])) and close > float(exit_high.iloc[index])
        if channel_hit:
            if index + 1 <= last and bool(frame.iloc[index + 1]["valid"]):
                return index + 1, frame.index[index + 1], float(frame.iloc[index + 1]["open"]), "channel_exit"
            return index, timestamp, float(stop), "source_gap_stop"
    return last, frame.index[last], float(frame.iloc[last]["close"]) if bool(frame.iloc[last]["valid"]) else float(stop), "evaluation_mtm"


def build_market_state(markets: dict[str, pd.DataFrame]) -> dict[str, dict[str, pd.Series]]:
    closes = pd.DataFrame({symbol: markets[symbol]["close"] for symbol in SYMBOLS})
    valid = pd.DataFrame({symbol: markets[symbol]["valid"] for symbol in SYMBOLS})
    ret24 = pd.DataFrame({symbol: continuous_log_return(closes[symbol], valid[symbol], 24) for symbol in SYMBOLS})
    output: dict[str, dict[str, pd.Series]] = {}
    for symbol in SYMBOLS:
        frame = markets[symbol]
        tr = true_range(frame)
        atr20 = tr.rolling(ATR_LB, min_periods=ATR_LB).mean()
        atr96 = tr.rolling(ENTRY_LB, min_periods=ENTRY_LB).mean()
        ret1 = continuous_log_return(frame["close"], frame["valid"], 1)
        ret4 = continuous_log_return(frame["close"], frame["valid"], 4)
        path24 = ret1.abs().rolling(24, min_periods=24).sum().replace(0, np.nan)
        efficiency24 = continuous_log_return(frame["close"], frame["valid"], 24) / path24
        output[symbol] = {
            "atr20": atr20,
            "atr96": atr96,
            "entry_high": prior_extreme(frame["high"], frame["valid"], ENTRY_LB, "max"),
            "entry_low": prior_extreme(frame["low"], frame["valid"], ENTRY_LB, "min"),
            "exit_high": prior_extreme(frame["high"], frame["valid"], EXIT_LB, "max"),
            "exit_low": prior_extreme(frame["low"], frame["valid"], EXIT_LB, "min"),
            "ret1": ret1,
            "ret4": ret4,
            "ret24": ret24[symbol],
            "efficiency24": efficiency24,
            "sma24": frame["close"].rolling(24, min_periods=24).mean(),
            "volume_z20": rolling_z(np.log1p(frame["volume"].clip(lower=0)), frame["valid"], 20),
        }
    output["_cross"] = {"ret24": ret24}  # type: ignore[assignment]
    return output


def generate_events(markets: dict[str, pd.DataFrame], start: pd.Timestamp, end_exclusive: pd.Timestamp) -> list[Event]:
    state = build_market_state(markets)
    cross_ret24 = state["_cross"]["ret24"]  # type: ignore[index]
    provisional: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        frame = markets[symbol]
        s = state[symbol]
        start_idx = max(ENTRY_LB + 1, ATR_LB + 1, 25)
        index = start_idx
        while index < len(frame) - 2:
            timestamp = frame.index[index]
            if timestamp < start:
                index += 1
                continue
            if timestamp >= end_exclusive:
                break
            row = frame.iloc[index]
            if not bool(row["valid"]):
                index += 1
                continue
            close = float(row["close"])
            high_level = float(s["entry_high"].iloc[index])
            low_level = float(s["entry_low"].iloc[index])
            long_signal = math.isfinite(high_level) and close > high_level
            short_signal = math.isfinite(low_level) and close < low_level
            if long_signal == short_signal:
                index += 1
                continue
            side = 1 if long_signal else -1
            entry_idx = index + 1
            if entry_idx >= len(frame) or not bool(frame.iloc[entry_idx]["valid"]):
                index += 1
                continue
            if frame.index[entry_idx] != timestamp + pd.Timedelta(hours=1):
                index += 1
                continue
            atr = float(s["atr20"].iloc[index])
            atr96 = float(s["atr96"].iloc[index])
            if not (math.isfinite(atr) and atr > 0 and math.isfinite(atr96) and atr96 > 0):
                index += 1
                continue
            entry = float(frame.iloc[entry_idx]["open"])
            stop = entry - side * STOP_ATR * atr
            exit_idx, exit_time, exit_price, reason = exit_path(frame, entry_idx, entry, side, stop, s["exit_low"], s["exit_high"])
            gross = side * (exit_price / entry - 1.0)
            funding_boundaries = count_funding_boundaries(frame.index[entry_idx], exit_time)
            stop_fraction = abs(entry - stop) / entry
            after_cost_return = gross - 24.0 / 10000.0 - funding_boundaries * ADVERSE_FUNDING_BPS_PER_8H / 10000.0
            target_r = after_cost_return / stop_fraction if stop_fraction > 0 else math.nan
            channel_level = high_level if side > 0 else low_level
            opposite = low_level if side > 0 else high_level
            breadth_values = cross_ret24.iloc[index]
            same_side_breadth = float(np.mean(np.sign(breadth_values.dropna().to_numpy(float)) == side)) if breadth_values.notna().any() else math.nan
            btc_ret = float(cross_ret24.loc[timestamp, "BTCUSDT"])
            eth_ret = float(cross_ret24.loc[timestamp, "ETHUSDT"])
            hour = timestamp.hour
            features = {
                "symbol_code": float(SYMBOL_CODE[symbol]),
                "side": float(side),
                "breakout_strength_atr": float(side * (close - channel_level) / atr),
                "channel_width_atr": float((high_level - low_level) / atr),
                "opposite_distance_atr": float(side * (close - opposite) / atr),
                "atr_pct": float(atr / close),
                "compression_ratio": float(atr / atr96),
                "signed_ret_1h": float(side * s["ret1"].iloc[index]),
                "signed_ret_4h": float(side * s["ret4"].iloc[index]),
                "signed_ret_24h": float(side * s["ret24"].iloc[index]),
                "signed_efficiency_24h": float(side * s["efficiency24"].iloc[index]),
                "signed_trend_distance_atr": float(side * (close - float(s["sma24"].iloc[index])) / atr),
                "volume_z20": float(s["volume_z20"].iloc[index]),
                "cross_asset_breadth": same_side_breadth,
                "same_side_breakout_count": 0.0,
                "signed_btc_ret24": float(side * btc_ret),
                "signed_eth_ret24": float(side * eth_ret),
                "utc_hour_sin": float(math.sin(2 * math.pi * hour / 24.0)),
                "utc_hour_cos": float(math.cos(2 * math.pi * hour / 24.0)),
            }
            if all(math.isfinite(value) for value in features.values()) and math.isfinite(target_r):
                event_key = f"{timestamp.isoformat()}|{symbol}|{side:+d}"
                provisional.append({
                    "event_key": event_key,
                    "symbol": symbol,
                    "side": side,
                    "signal_idx": index,
                    "entry_idx": entry_idx,
                    "exit_idx": exit_idx,
                    "signal_time": timestamp,
                    "entry_time": frame.index[entry_idx],
                    "exit_time": exit_time,
                    "entry_price": entry,
                    "exit_price": exit_price,
                    "stop_price": stop,
                    "exit_reason": reason,
                    "gross_return": gross,
                    "score": abs(close - channel_level) / atr,
                    "stop_fraction": stop_fraction,
                    "funding_boundaries": funding_boundaries,
                    "target_r_24bp": target_r,
                    "features": features,
                })
            if reason == "evaluation_mtm":
                break
            index = max(index + 1, exit_idx + 1)
    counts: dict[tuple[pd.Timestamp, int], int] = {}
    for item in provisional:
        key = (item["signal_time"], item["side"])
        counts[key] = counts.get(key, 0) + 1
    events: list[Event] = []
    for item in provisional:
        item["features"]["same_side_breakout_count"] = float(counts[(item["signal_time"], item["side"])])
        events.append(Event(**item))
    return sorted(events, key=lambda event: (event.entry_time, -event.score, event.symbol))


def event_frame(events: list[Event]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for event in events:
        row = {
            "event_key": event.event_key,
            "symbol": event.symbol,
            "side": event.side,
            "signal_time": event.signal_time,
            "entry_time": event.entry_time,
            "exit_time": event.exit_time,
            "target_r_24bp": event.target_r_24bp,
            "score": event.score,
        }
        row.update(event.features)
        rows.append(row)
    return pd.DataFrame(rows)


def fit_model(events: list[Event]) -> tuple[HistGradientBoostingRegressor, float, dict[str, Any], pd.DataFrame]:
    frame = event_frame(events)
    train = frame[(frame["entry_time"] < TRAIN_END) & (frame["exit_time"] < TRAIN_END)]
    calibration = frame[(frame["entry_time"] >= TRAIN_END) & (frame["entry_time"] < CAL_END) & (frame["exit_time"] < CAL_END)]
    confirmation = frame[(frame["entry_time"] >= CAL_END) & (frame["entry_time"] < CONF_END) & (frame["exit_time"] < CONF_END)]
    if len(train) < 200 or len(calibration) < 50 or len(confirmation) < 50:
        raise ResearchError(f"Insufficient event rows train={len(train)} calibration={len(calibration)} confirmation={len(confirmation)}")
    model = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.04,
        max_iter=250,
        max_leaf_nodes=15,
        min_samples_leaf=30,
        l2_regularization=2.0,
        random_state=20260726,
    )
    model.fit(train.loc[:, FEATURE_COLUMNS], train["target_r_24bp"])
    raw = model.predict(calibration.loc[:, FEATURE_COLUMNS])
    actual = calibration["target_r_24bp"].to_numpy(float)
    denominator = float(np.dot(raw, raw))
    scale = float(np.dot(raw, actual) / denominator) if denominator > 0 else 0.0
    scale = float(np.clip(scale, 0.0, 1.5))
    frame["raw_prediction_r"] = model.predict(frame.loc[:, FEATURE_COLUMNS])
    frame["prediction_r"] = frame["raw_prediction_r"] * scale
    diagnostics = {
        "train_rows": int(len(train)),
        "calibration_rows": int(len(calibration)),
        "confirmation_rows": int(len(confirmation)),
        "train_target_mean_r": float(train["target_r_24bp"].mean()),
        "calibration_target_mean_r": float(calibration["target_r_24bp"].mean()),
        "raw_calibration_prediction_mean_r": float(np.mean(raw)),
        "calibration_scale": scale,
        "feature_columns": list(FEATURE_COLUMNS),
        "model_parameters": model.get_params(),
    }
    return model, scale, diagnostics, frame


def simulate(
    markets: dict[str, pd.DataFrame],
    events: list[Event],
    predictions: dict[str, float],
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    config: PathConfig,
    selector: str,
    blocked_keys: set[str] | None = None,
    split_time: pd.Timestamp | None = None,
) -> PathResult:
    blocked = blocked_keys or set()
    eligible = [event for event in events if start <= event.entry_time < end_exclusive and event.exit_time < end_exclusive and event.exit_reason != "evaluation_mtm" and event.event_key not in blocked]
    eligible.sort(key=lambda event: (event.entry_time, -event.score, event.symbol))
    nav = 10000.0
    initial_nav = nav
    free_time = start
    trade_records: list[dict[str, Any]] = []
    points: list[tuple[pd.Timestamp, float]] = [(start, nav)]
    index = 0
    while index < len(eligible):
        entry_time = eligible[index].entry_time
        group: list[Event] = []
        while index < len(eligible) and eligible[index].entry_time == entry_time:
            group.append(eligible[index])
            index += 1
        if entry_time < free_time or nav <= 0:
            continue
        if selector == "baseline":
            chosen = max(group, key=lambda event: (event.score, event.symbol))
        elif selector == "ml":
            accepted = [event for event in group if predictions.get(event.event_key, -math.inf) > 0]
            if not accepted:
                continue
            chosen = max(accepted, key=lambda event: (predictions[event.event_key], event.score, event.symbol))
        else:
            raise ValueError(selector)
        half_fee = config.round_trip_cost_bps / 20000.0
        unit_loss = abs(chosen.entry_price - chosen.stop_price) + half_fee * (chosen.entry_price + chosen.stop_price)
        if unit_loss <= 0 or not math.isfinite(unit_loss):
            continue
        quantity = min(nav * config.risk_fraction / unit_loss, nav * config.notional_cap / chosen.entry_price)
        if quantity <= 0:
            continue
        before = nav
        nav_after_entry = nav - quantity * chosen.entry_price * half_fee
        frame = markets[chosen.symbol]
        for bar_index in range(chosen.entry_idx, min(chosen.exit_idx, len(frame) - 1) + 1):
            row = frame.iloc[bar_index]
            if not bool(row["valid"]):
                break
            mark = float(row["close"])
            marked = nav_after_entry + chosen.side * quantity * (mark - chosen.entry_price) - quantity * mark * half_fee
            points.append((frame.index[bar_index], marked))
        funding_cost = quantity * chosen.entry_price * chosen.funding_boundaries * ADVERSE_FUNDING_BPS_PER_8H / 10000.0
        nav = nav_after_entry + chosen.side * quantity * (chosen.exit_price - chosen.entry_price) - quantity * chosen.exit_price * half_fee - funding_cost
        trade_records.append({
            "event_key": chosen.event_key,
            "symbol": chosen.symbol,
            "side": chosen.side,
            "entry_time": chosen.entry_time.isoformat(),
            "exit_time": chosen.exit_time.isoformat(),
            "exit_reason": chosen.exit_reason,
            "predicted_r": predictions.get(chosen.event_key),
            "target_r_24bp": chosen.target_r_24bp,
            "score": chosen.score,
            "quantity": quantity,
            "leverage": quantity * chosen.entry_price / before,
            "funding_boundaries": chosen.funding_boundaries,
            "net_pnl": nav - before,
            "account_return": nav / before - 1.0,
            "nav_before": before,
            "nav_after": nav,
        })
        points.append((chosen.exit_time, nav))
        free_time = chosen.exit_time + pd.Timedelta(hours=1)
    days = max(1, int((end_exclusive - start).total_seconds() // 86400))
    growth = (nav / initial_nav) ** (1.0 / days) - 1.0 if nav > 0 else -1.0
    returns = np.array([record["account_return"] for record in trade_records], dtype=float)
    pnl = np.array([record["net_pnl"] for record in trade_records], dtype=float)
    positive = pnl[pnl > 0]
    negative = pnl[pnl < 0]
    profit_factor = float(positive.sum() / -negative.sum()) if len(positive) and len(negative) else (float("inf") if len(positive) else 0.0)
    points.sort(key=lambda item: item[0])
    point_values = np.array([value for _, value in points], dtype=float)
    maximum_drawdown = float(np.max(1.0 - point_values / np.maximum.accumulate(point_values))) if len(point_values) else 0.0
    top5 = float(np.sort(positive)[-5:].sum() / positive.sum()) if len(positive) else 1.0
    split = split_time if split_time is not None else start + (end_exclusive - start) / 2
    before_split = [value for timestamp, value in points if timestamp <= split]
    midpoint = before_split[-1] if before_split else initial_nav
    daily: dict[str, float] = {}
    for timestamp, value in points:
        daily[timestamp.floor("D").date().isoformat()] = float(value)
    return PathResult(
        config=asdict(config),
        final_nav=float(nav),
        total_return=float(nav / initial_nav - 1.0),
        geometric_daily_growth=float(growth),
        maximum_drawdown=maximum_drawdown,
        trade_count=int(len(trade_records)),
        positive_trade_count=int(np.sum(returns > 0)),
        mean_account_return_bps=float(np.mean(returns) * 10000.0) if len(returns) else None,
        median_account_return_bps=float(np.median(returns) * 10000.0) if len(returns) else None,
        profit_factor=profit_factor,
        win_rate=float(np.mean(returns > 0)) if len(returns) else None,
        top5_positive_share=top5,
        h1_return=float(midpoint / initial_nav - 1.0),
        h2_return=float(nav / midpoint - 1.0) if midpoint > 0 else -1.0,
        ruined=bool(nav <= 0),
        source_gap_stop_count=sum(record["exit_reason"] == "source_gap_stop" for record in trade_records),
        gap_stop_count=sum(record["exit_reason"] == "gap_stop" for record in trade_records),
        stop_count=sum(record["exit_reason"] == "stop" for record in trade_records),
        channel_exit_count=sum(record["exit_reason"] == "channel_exit" for record in trade_records),
        trade_records=trade_records,
        daily_nav=daily,
    )


def winner_removed_path(markets: dict[str, pd.DataFrame], events: list[Event], predictions: dict[str, float], start: pd.Timestamp, end_exclusive: pd.Timestamp, config: PathConfig, selector: str, base: PathResult, split_time: pd.Timestamp | None = None) -> tuple[PathResult, list[str]]:
    positive = [record for record in base.trade_records if record["net_pnl"] > 0]
    count = max(1, math.ceil(len(base.trade_records) * 0.10)) if base.trade_records else 0
    removed = [record["event_key"] for record in sorted(positive, key=lambda record: record["net_pnl"], reverse=True)[:count]]
    return simulate(markets, events, predictions, start, end_exclusive, config, selector, set(removed), split_time), removed


def prediction_metrics(frame: pd.DataFrame, start: pd.Timestamp, end_exclusive: pd.Timestamp) -> dict[str, Any]:
    subset = frame[(frame["entry_time"] >= start) & (frame["entry_time"] < end_exclusive) & (frame["exit_time"] < end_exclusive)]
    spearman = subset["prediction_r"].corr(subset["target_r_24bp"], method="spearman")
    return {
        "rows": int(len(subset)),
        "spearman": None if pd.isna(spearman) else float(spearman),
        "prediction_mean_r": float(subset["prediction_r"].mean()),
        "prediction_std_r": float(subset["prediction_r"].std(ddof=0)),
        "target_mean_r": float(subset["target_r_24bp"].mean()),
        "target_median_r": float(subset["target_r_24bp"].median()),
    }


def gate_checks(metrics: dict[str, Any], ml: PathResult, baseline: PathResult, removed: PathResult) -> dict[str, bool]:
    return {
        "model_spearman_at_least_0_05": metrics["spearman"] is not None and metrics["spearman"] >= 0.05,
        "accepted_trades_at_least_40": ml.trade_count >= 40,
        "positive_total_return": ml.total_return > 0,
        "positive_median_trade": ml.median_account_return_bps is not None and ml.median_account_return_bps > 0,
        "profit_factor_at_least_1_2": ml.profit_factor is not None and ml.profit_factor >= 1.2,
        "both_halves_positive": ml.h1_return > 0 and ml.h2_return > 0,
        "top5_share_at_most_0_45": ml.top5_positive_share <= 0.45,
        "winner_removed_return_positive": removed.total_return > 0,
        "growth_above_same_data_baseline": ml.geometric_daily_growth > baseline.geometric_daily_growth,
        "nav_positive": not ml.ruined and ml.final_nav > 0,
    }


def load_markets(start: pd.Timestamp, end_exclusive: pd.Timestamp, cache: Path, manifest: list[dict[str, Any]]) -> dict[str, pd.DataFrame]:
    return {symbol: aggregate_hourly(load_five_minute(symbol, start, end_exclusive, cache, manifest)) for symbol in SYMBOLS}


def run(output: Path, cache: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    source_records: list[dict[str, Any]] = []
    pre_markets = load_markets(PRE_START, PRE_END, cache, source_records)
    pre_events = generate_events(pre_markets, PRE_START, PRE_END)
    model, scale, fit_diagnostics, frame = fit_model(pre_events)
    predictions = dict(zip(frame["event_key"], frame["prediction_r"], strict=True))
    confirmation_metrics = prediction_metrics(frame, CAL_END, CONF_END)
    base_config = PathConfig(BASE_RISK_FRACTION, BASE_NOTIONAL_CAP, 24.0)
    baseline24 = simulate(pre_markets, pre_events, predictions, CAL_END, CONF_END, base_config, "baseline", split_time=pd.Timestamp("2023-07-01T00:00:00Z"))
    ml_paths: dict[str, dict[str, Any]] = {}
    ml_path_objects: dict[int, PathResult] = {}
    for cost in ROUND_TRIP_COSTS_BPS:
        path = simulate(pre_markets, pre_events, predictions, CAL_END, CONF_END, PathConfig(BASE_RISK_FRACTION, BASE_NOTIONAL_CAP, cost), "ml", split_time=pd.Timestamp("2023-07-01T00:00:00Z"))
        ml_path_objects[int(cost)] = path
        ml_paths[str(int(cost))] = asdict(path)
    removed24, removed_keys = winner_removed_path(pre_markets, pre_events, predictions, CAL_END, CONF_END, base_config, "ml", ml_path_objects[24], pd.Timestamp("2023-07-01T00:00:00Z"))
    checks = gate_checks(confirmation_metrics, ml_path_objects[24], baseline24, removed24)
    alpha_gate = all(checks.values())
    selected_risk: dict[str, Any] | None = None
    selected_confirmation: dict[str, Any] | None = None
    selected_removed: dict[str, Any] | None = None
    rank_gate = False
    validation: dict[str, Any] | None = None
    validation_opened = False
    if alpha_gate:
        calibration_candidates: list[tuple[float, float, float, PathResult]] = []
        for risk in RISK_FRACTIONS:
            for cap in NOTIONAL_CAPS:
                config = PathConfig(risk, cap, 24.0)
                path = simulate(pre_markets, pre_events, predictions, TRAIN_END, CAL_END, config, "ml", split_time=pd.Timestamp("2022-10-01T00:00:00Z"))
                if not path.ruined:
                    calibration_candidates.append((path.geometric_daily_growth, risk, cap, path))
        calibration_candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        if calibration_candidates:
            _growth, risk, cap, calibration_path = calibration_candidates[0]
            selected_config = PathConfig(risk, cap, 24.0)
            selected_path = simulate(pre_markets, pre_events, predictions, CAL_END, CONF_END, selected_config, "ml", split_time=pd.Timestamp("2023-07-01T00:00:00Z"))
            selected_removed_path, selected_removed_keys = winner_removed_path(pre_markets, pre_events, predictions, CAL_END, CONF_END, selected_config, "ml", selected_path, pd.Timestamp("2023-07-01T00:00:00Z"))
            selected_risk = {"risk_fraction": risk, "notional_cap": cap, "calibration_path": asdict(calibration_path)}
            selected_confirmation = asdict(selected_path)
            selected_removed = {"path": asdict(selected_removed_path), "removed_event_keys": selected_removed_keys}
            rank_gate = (
                not selected_path.ruined
                and selected_path.geometric_daily_growth > CURRENT_RANK_ONE_24BP_GROWTH
                and selected_removed_path.total_return > 0
                and selected_path.h1_return > 0
                and selected_path.h2_return > 0
            )
            if rank_gate:
                validation_opened = True
                validation_manifest: list[dict[str, Any]] = []
                validation_markets = load_markets(pd.Timestamp("2023-09-01T00:00:00Z"), VALIDATION_END, cache, validation_manifest)
                validation_events = generate_events(validation_markets, pd.Timestamp("2023-09-01T00:00:00Z"), VALIDATION_END)
                validation_frame = event_frame(validation_events)
                validation_frame["raw_prediction_r"] = model.predict(validation_frame.loc[:, FEATURE_COLUMNS])
                validation_frame["prediction_r"] = validation_frame["raw_prediction_r"] * scale
                validation_predictions = dict(zip(validation_frame["event_key"], validation_frame["prediction_r"], strict=True))
                val_start = pd.Timestamp("2024-01-01T00:00:00Z")
                val_path = simulate(validation_markets, validation_events, validation_predictions, val_start, VALIDATION_END, selected_config, "ml", split_time=pd.Timestamp("2024-04-01T00:00:00Z"))
                val_removed, val_removed_keys = winner_removed_path(validation_markets, validation_events, validation_predictions, val_start, VALIDATION_END, selected_config, "ml", val_path, pd.Timestamp("2024-04-01T00:00:00Z"))
                val_pass = (
                    not val_path.ruined
                    and val_path.geometric_daily_growth > CURRENT_RANK_ONE_24BP_GROWTH
                    and val_removed.total_return > 0
                    and val_path.h1_return > 0
                    and val_path.h2_return > 0
                )
                validation = {
                    "path": asdict(val_path),
                    "winner_removed": asdict(val_removed),
                    "removed_event_keys": val_removed_keys,
                    "gate_passed": val_pass,
                    "source_manifest": validation_manifest,
                    "event_count": len(validation_events),
                }
    status = "VALIDATION_SURVIVOR" if validation and validation["gate_passed"] else ("RANK_CHALLENGE_PRE2024" if rank_gate else ("CONFIRMATION_ALPHA_GATE_PASS" if alpha_gate else "CONFIRMATION_BELOW_GATE"))
    decision = "PROMOTE_TO_EXACT_EXECUTION_AND_RANK_COMPARISON" if status == "VALIDATION_SURVIVOR" else "RETIRE_EXACT_INFORMATION_UNIT"
    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "result_id": RESULT_ID,
        "experiment_id": EXPERIMENT_ID,
        "status": status,
        "decision": decision,
        "hard_validity": "PASS_CAUSAL_FIXED_STRUCTURE_ML_SCREEN",
        "economic_status": "SURVIVOR" if status == "VALIDATION_SURVIVOR" else "BELOW_GATE",
        "ranking_role": "PROVISIONAL_RANK_CHALLENGER" if status == "VALIDATION_SURVIVOR" else "NONE",
        "fixed_structure": {"entry_lookback_hours": ENTRY_LB, "exit_channel_hours": EXIT_LB, "stop_atr": STOP_ATR, "elapsed_time_liquidation": False},
        "model_family_count": 1,
        "hyperparameter_grid": False,
        "feature_grid": False,
        "threshold_grid": False,
        "one_global_slot": True,
        "source_gap_policy": "NO_IMPUTATION_RESET_ROLLING_STATE_AND_ADVERSE_OPEN_POSITION_GAP",
        "fit": fit_diagnostics,
        "pre2024_event_count": len(pre_events),
        "confirmation_prediction_metrics": confirmation_metrics,
        "same_data_all_breakout_24bp": asdict(baseline24),
        "ml_base_paths": ml_paths,
        "winner_removed_24bp": asdict(removed24),
        "winner_removed_event_keys": removed_keys,
        "confirmation_gate_checks": checks,
        "confirmation_gate_passed": alpha_gate,
        "selected_risk": selected_risk,
        "selected_confirmation": selected_confirmation,
        "selected_winner_removed": selected_removed,
        "rank_gate_passed": rank_gate,
        "conditional_2024h1_opened": validation_opened,
        "conditional_2024h1": validation,
        "current_rank_one_24bp_geometric_daily_growth": CURRENT_RANK_ONE_24BP_GROWTH,
        "official_2025_2026_opened": False,
        "credentials_used": False,
        "orders_submitted": False,
    }
    write_json(output / "RESULT.json", result)
    write_json(output / "MODEL_FIT.json", fit_diagnostics)
    write_json(output / "SOURCE_MANIFEST.json", {"schema_version": 1, "files": source_records})
    frame.to_csv(output / "EVENT_MODEL_MATRIX.csv", index=False)
    pd.DataFrame(ml_path_objects[24].trade_records).to_csv(output / "CONFIRMATION_TRADES_24BP.csv", index=False)
    write_json(output / "ENVIRONMENT.json", {"python": platform.python_version(), "platform": platform.platform(), "numpy": np.__version__, "pandas": pd.__version__})
    return result


def self_test() -> None:
    index = pd.date_range("2022-01-01", periods=720, freq="1h", tz="UTC")
    cycle = np.concatenate([
        np.linspace(100.0, 101.0, 120, endpoint=False),
        np.linspace(112.0, 145.0, 96, endpoint=False),
        np.linspace(145.0, 108.0, 96, endpoint=False),
        np.linspace(108.0, 107.0, 48, endpoint=False),
    ])
    base = np.tile(cycle, 2)[: len(index)]
    markets: dict[str, pd.DataFrame] = {}
    for offset, symbol in enumerate(SYMBOLS):
        close = base * (1 + offset * 0.001)
        open_ = np.r_[close[0], close[:-1]]
        frame = pd.DataFrame(index=index)
        frame["open"] = open_
        frame["high"] = np.maximum(open_, close) * 1.0002
        frame["low"] = np.minimum(open_, close) * 0.9998
        frame["close"] = close
        frame["volume"] = 1000.0 + 10.0 * np.sin(np.arange(len(index)) / 12.0) + np.arange(len(index)) * 0.1
        frame["valid"] = True
        markets[symbol] = frame
    events = generate_events(markets, index[0], index[-1] + pd.Timedelta(hours=1))
    assert events, "synthetic breakout cycles should produce structural events"
    for event in events:
        assert event.entry_time > event.signal_time
        assert event.exit_time >= event.entry_time
        assert event.exit_reason in {"stop", "gap_stop", "source_gap_stop", "channel_exit", "evaluation_mtm"}
    sample = events[0]
    predictions = {event.event_key: (1.0 if event.event_key == sample.event_key else -1.0) for event in events}
    path = simulate(markets, events, predictions, index[0], index[-1] + pd.Timedelta(hours=1), PathConfig(0.005, 5.0, 24.0), "ml")
    assert path.trade_count >= 1
    assert month_url("BTCUSDT", 2024, 1).endswith("BTCUSDT_5_2024-01-01_2024-01-31.csv.gz")
    try:
        month_url("BTCUSDT", 2025, 1)
    except ResearchError:
        pass
    else:
        raise AssertionError("2025 source must stay prohibited")
    print(json.dumps({"self_test": "PASS", "events": len(events), "trades": path.trade_count}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None or args.cache is None:
        parser.error("--output and --cache are required unless --self-test is used")
    result = run(args.output, args.cache)
    print(json.dumps({"status": result["status"], "confirmation_gate": result["confirmation_gate_passed"], "rank_gate": result["rank_gate_passed"], "validation_opened": result["conditional_2024h1_opened"], "decision": result["decision"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
