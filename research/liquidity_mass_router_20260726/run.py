from __future__ import annotations

import argparse
import calendar
import gzip
import hashlib
import itertools
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
import requests

CLAIM_ID = "CLM-20260726-1704-LIQUIDITY-MASS-001"
ENGINE_VERSION = "LIQUIDITY-MASS-ROUTER-V1"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
FIT_YEAR = 2022
DEVELOPMENT_YEAR = 2023
PROHIBITED_YEARS = (2024, 2025, 2026)
COSTS_BPS = (12.0, 18.0, 24.0)
INITIAL_NAV = 10_000.0
RISK_FRACTION = 0.005
NOTIONAL_CAP_MULTIPLE = 3.0
PARTICIPATION_CAP = 0.001
BASE_URL = "https://public.bybit.com/kline_for_metatrader4"
SYMBOL_ORDER = {symbol: i for i, symbol in enumerate(SYMBOLS)}
POOL_TOLERANCE_ATR = 0.10
SWEEP_BUFFER_ATR = 0.05
POOL_CLUSTER_MAX_AGE_HOURS = 24 * 14
MAX_TARGET_DISTANCE_ATR = 40.0


@dataclass(frozen=True)
class Config:
    pivot_span: int
    minimum_touches: int
    maximum_pool_age_hours: int
    minimum_mass_ratio: float
    minimum_displacement_atr: float
    mode: str
    minimum_reward_risk: float

    @property
    def config_id(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:20]


@dataclass
class LiquidityPool:
    pool_id: str
    side: int
    level: float
    total_weight: float
    touches: float
    htf_hits: int
    volume_score: float
    first_confirm_i: int
    last_confirm_i: int
    active: bool = True


@dataclass(frozen=True)
class PoolSnapshot:
    pool_id: str
    side: int
    level: float
    mass: float
    touches: float
    htf_hits: int
    age_hours: float


@dataclass(frozen=True)
class RawSweepEvent:
    event_key: str
    symbol: str
    pivot_span: int
    event_i: int
    event_time: str
    sweep_side: int
    pool_level: float
    swept_mass: float
    swept_touches: float
    swept_age_hours: float
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    atr: float
    body_atr: float
    close_location: float
    quote_volume_prior: float
    high_targets: tuple[PoolSnapshot, ...]
    low_targets: tuple[PoolSnapshot, ...]


@dataclass(frozen=True)
class CandidateTrade:
    config_id: str
    event_key: str
    symbol: str
    mode: str
    side: int
    entry_i: int
    exit_i: int
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    exit_reason: str
    score: float
    quote_volume_prior: float
    open_at_boundary: bool
    swept_pool_level: float
    swept_pool_mass: float
    target_pool_level: float
    target_pool_mass: float
    mass_ratio: float
    swept_touches: float
    target_touches: float
    body_atr: float


@dataclass
class AccountTrade:
    config_id: str
    event_key: str
    symbol: str
    mode: str
    side: int
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    quantity: float
    notional: float
    gross_pnl: float
    cost: float
    net_pnl: float
    account_return: float
    nav_before: float
    nav_after: float
    exit_reason: str
    open_at_boundary: bool


def configs() -> tuple[Config, ...]:
    cells = tuple(
        Config(*values)
        for values in itertools.product(
            (2, 3),
            (2, 3),
            (24, 72),
            (1.5, 2.5),
            (0.5, 1.0),
            ("rejection", "continuation"),
            (2.0, 3.0),
        )
    )
    assert len(cells) == 128
    assert len({cell.config_id for cell in cells}) == 128
    return cells


def month_url(symbol: str, year: int, month: int) -> str:
    if year in PROHIBITED_YEARS:
        raise ValueError(f"sealed year requested: {year}")
    end = calendar.monthrange(year, month)[1]
    name = f"{symbol}_5_{year:04d}-{month:02d}-01_{year:04d}-{month:02d}-{end:02d}.csv.gz"
    return f"{BASE_URL}/{symbol}/{year}/{name}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, path: Path, session: requests.Session) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        tmp = path.with_suffix(path.suffix + ".part")
        for attempt in range(5):
            try:
                with session.get(url, stream=True, timeout=(30, 180)) as response:
                    response.raise_for_status()
                    with tmp.open("wb") as handle:
                        for chunk in response.iter_content(1 << 20):
                            if chunk:
                                handle.write(chunk)
                tmp.replace(path)
                break
            except Exception:
                if tmp.exists():
                    tmp.unlink()
                if attempt == 4:
                    raise
                time.sleep(2**attempt)
    with gzip.open(path, "rb") as handle:
        while handle.read(1 << 20):
            pass
    return {"url": url, "path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _coerce_kline(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.shape[1] < 6:
        raise ValueError(f"Bybit kline has {raw.shape[1]} columns, expected at least 6")
    raw = raw.iloc[:, :6].copy()
    raw.columns = ["datetime", "open", "high", "low", "close", "volume"]
    numeric = raw[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce").astype(float)
    dt = pd.to_datetime(raw["datetime"], utc=True, errors="coerce", format="mixed")
    keep = dt.notna() & numeric.notna().all(axis=1)
    frame = numeric.loc[keep].copy()
    frame.index = pd.DatetimeIndex(dt.loc[keep])
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    if frame.empty:
        raise ValueError("Bybit kline file parsed to zero rows")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any() or (frame["volume"] < 0).any():
        raise ValueError("Bybit kline contains non-positive price or negative volume")
    if not (frame["high"] >= frame[["open", "close", "low"]].max(axis=1)).all():
        raise ValueError("Bybit high invariant failed")
    if not (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)).all():
        raise ValueError("Bybit low invariant failed")
    return frame


def read_month(path: Path) -> pd.DataFrame:
    return _coerce_kline(pd.read_csv(path, compression="gzip", header=None, low_memory=False))


def load_year(symbol: str, year: int, cache: Path, session: requests.Session) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    if year in PROHIBITED_YEARS:
        raise ValueError(f"sealed year requested: {year}")
    frames: list[pd.DataFrame] = []
    records: list[dict[str, object]] = []
    for month in range(1, 13):
        url = month_url(symbol, year, month)
        path = cache / symbol / str(year) / url.rsplit("/", 1)[-1]
        record = download(url, path, session)
        frame = read_month(path)
        record.update(
            {
                "symbol": symbol,
                "year": year,
                "month": month,
                "row_count": int(len(frame)),
                "first_timestamp": frame.index[0].isoformat(),
                "last_timestamp": frame.index[-1].isoformat(),
            }
        )
        records.append(record)
        frames.append(frame)
    data = pd.concat(frames).sort_index()
    data = data[~data.index.duplicated(keep="last")]
    start = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
    end = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC") - pd.Timedelta(minutes=5)
    grid = pd.date_range(start, end, freq="5min", tz="UTC")
    data = data.reindex(grid)
    data.index.name = "open_time"
    data["valid"] = np.isfinite(data[["open", "high", "low", "close", "volume"]]).all(axis=1)
    data["close_time"] = data.index + pd.Timedelta(minutes=5)
    return data, records


def _segment_ids(valid: pd.Series) -> pd.Series:
    return (~valid.astype(bool)).cumsum()


def _segmented_rolling_mean(values: pd.Series, valid: pd.Series, window: int) -> pd.Series:
    segment = _segment_ids(valid)
    out = values.where(valid).groupby(segment).rolling(window, min_periods=window).mean()
    return out.reset_index(level=0, drop=True).reindex(values.index)


def _segmented_rolling_median(values: pd.Series, valid: pd.Series, window: int) -> pd.Series:
    segment = _segment_ids(valid)
    out = values.where(valid).groupby(segment).rolling(window, min_periods=window).median()
    return out.reset_index(level=0, drop=True).reindex(values.index)


def confirmed_pivots(high: np.ndarray, low: np.ndarray, valid: np.ndarray, span: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(high)
    ph = np.full(n, np.nan)
    pl = np.full(n, np.nan)
    ph_origin = np.full(n, -1, dtype=np.int64)
    pl_origin = np.full(n, -1, dtype=np.int64)
    for confirm_i in range(span * 2, n):
        pivot_i = confirm_i - span
        left = pivot_i - span
        right = pivot_i + span + 1
        if left < 0 or not valid[left:right].all():
            continue
        hwin = high[left:right]
        lwin = low[left:right]
        if np.isfinite(high[pivot_i]) and high[pivot_i] == np.max(hwin) and np.count_nonzero(hwin == high[pivot_i]) == 1:
            ph[confirm_i] = high[pivot_i]
            ph_origin[confirm_i] = pivot_i
        if np.isfinite(low[pivot_i]) and low[pivot_i] == np.min(lwin) and np.count_nonzero(lwin == low[pivot_i]) == 1:
            pl[confirm_i] = low[pivot_i]
            pl_origin[confirm_i] = pivot_i
    return ph, pl, ph_origin, pl_origin


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    prev_close = result["close"].shift(1)
    tr = pd.concat(
        [result["high"] - result["low"], (result["high"] - prev_close).abs(), (result["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    result["atr5"] = _segmented_rolling_mean(tr, result["valid"], 20)
    quote_volume = result["close"] * result["volume"]
    result["quote_volume"] = quote_volume
    median = _segmented_rolling_median(quote_volume, result["valid"], 288)
    result["volume_ratio"] = (quote_volume / median.replace(0, np.nan)).clip(lower=0.05, upper=25.0)
    return result


def pivot_events(frame: pd.DataFrame, span: int) -> dict[int, list[tuple[int, float, float, float, bool]]]:
    valid = frame["valid"].to_numpy(bool)
    high = frame["high"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    ph, pl, phi, pli = confirmed_pivots(high, low, valid, span)
    volume_ratio = frame["volume_ratio"].to_numpy(float)
    events: dict[int, list[tuple[int, float, float, float, bool]]] = {}
    for i in range(len(frame)):
        if math.isfinite(ph[i]):
            origin = int(phi[i])
            ratio = float(volume_ratio[origin]) if math.isfinite(volume_ratio[origin]) else 1.0
            events.setdefault(i, []).append((1, float(ph[i]), ratio, 1.0, False))
        if math.isfinite(pl[i]):
            origin = int(pli[i])
            ratio = float(volume_ratio[origin]) if math.isfinite(volume_ratio[origin]) else 1.0
            events.setdefault(i, []).append((-1, float(pl[i]), ratio, 1.0, False))
    indexed = frame.set_index("close_time")
    grouped = indexed[["open", "high", "low", "close", "volume", "valid"]].resample("60min", label="right", closed="right")
    hourly = pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(min_count=1),
            "count": grouped["valid"].sum(),
        }
    )
    hourly["valid"] = hourly["count"].eq(12) & np.isfinite(hourly[["open", "high", "low", "close", "volume"]]).all(axis=1)
    hqv = hourly["close"] * hourly["volume"]
    hmed = _segmented_rolling_median(hqv, hourly["valid"], 24)
    hratio = (hqv / hmed.replace(0, np.nan)).clip(lower=0.05, upper=25.0)
    hph, hpl, hphi, hpli = confirmed_pivots(hourly["high"].to_numpy(float), hourly["low"].to_numpy(float), hourly["valid"].to_numpy(bool), 2)
    close_to_i = {pd.Timestamp(value): i for i, value in enumerate(frame["close_time"])}
    for j, ts in enumerate(hourly.index):
        i = close_to_i.get(pd.Timestamp(ts))
        if i is None:
            continue
        if math.isfinite(hph[j]):
            origin = int(hphi[j])
            ratio = float(hratio.iloc[origin]) if math.isfinite(float(hratio.iloc[origin])) else 1.0
            events.setdefault(i, []).append((1, float(hph[j]), ratio, 2.0, True))
        if math.isfinite(hpl[j]):
            origin = int(hpli[j])
            ratio = float(hratio.iloc[origin]) if math.isfinite(float(hratio.iloc[origin])) else 1.0
            events.setdefault(i, []).append((-1, float(hpl[j]), ratio, 2.0, True))
    return events


def pool_mass(pool: LiquidityPool, current_i: int) -> float:
    age_hours = max(0.0, (current_i - pool.first_confirm_i) * 5.0 / 60.0)
    age_factor = 1.0 + min(age_hours, 72.0) / 72.0
    average_volume = pool.volume_score / max(pool.total_weight, np.finfo(float).tiny)
    return float((pool.touches**1.25) * (1.0 + 0.35 * pool.htf_hits) * age_factor * max(0.25, average_volume))


def snapshot(pool: LiquidityPool, current_i: int) -> PoolSnapshot:
    return PoolSnapshot(pool.pool_id, pool.side, pool.level, pool_mass(pool, current_i), pool.touches, pool.htf_hits, max(0.0, (current_i - pool.first_confirm_i) * 5.0 / 60.0))


def add_pool_observation(pools: list[LiquidityPool], side: int, level: float, i: int, atr: float, volume_ratio: float, weight: float, is_htf: bool) -> None:
    tolerance = POOL_TOLERANCE_ATR * atr
    eligible = [
        pool
        for pool in pools
        if pool.active and pool.side == side and abs(level - pool.level) <= tolerance and (i - pool.last_confirm_i) * 5.0 / 60.0 <= POOL_CLUSTER_MAX_AGE_HOURS
    ]
    if eligible:
        pool = min(eligible, key=lambda item: abs(level - item.level))
        total = pool.total_weight + weight
        pool.level = (pool.level * pool.total_weight + level * weight) / total
        pool.total_weight = total
        pool.touches += weight
        pool.htf_hits += int(is_htf)
        pool.volume_score += weight * math.sqrt(max(0.05, min(volume_ratio, 25.0)))
        pool.last_confirm_i = i
        return
    token = hashlib.sha256(f"{side}|{level:.12g}|{i}|{len(pools)}".encode()).hexdigest()[:18]
    pools.append(LiquidityPool(token, side, level, weight, weight, int(is_htf), weight * math.sqrt(max(0.05, min(volume_ratio, 25.0))), i, i))


def build_sweep_events(frame: pd.DataFrame, symbol: str, span: int) -> list[RawSweepEvent]:
    events_by_i = pivot_events(frame, span)
    pools: list[LiquidityPool] = []
    output: list[RawSweepEvent] = []
    o = frame["open"].to_numpy(float)
    h = frame["high"].to_numpy(float)
    l = frame["low"].to_numpy(float)
    c = frame["close"].to_numpy(float)
    atr = frame["atr5"].to_numpy(float)
    valid = frame["valid"].to_numpy(bool)
    qv = frame["quote_volume"].to_numpy(float)
    for i in range(len(frame) - 1):
        if not valid[i] or not math.isfinite(atr[i]) or atr[i] <= 0:
            for pool in pools:
                pool.active = False
            pools.clear()
            continue
        buffer = SWEEP_BUFFER_ATR * atr[i]
        active = [pool for pool in pools if pool.active]
        crossed_high = [pool for pool in active if pool.side > 0 and h[i] >= pool.level + buffer]
        crossed_low = [pool for pool in active if pool.side < 0 and l[i] <= pool.level - buffer]
        if crossed_high and crossed_low:
            for pool in crossed_high + crossed_low:
                pool.active = False
        elif crossed_high or crossed_low:
            crossed = crossed_high if crossed_high else crossed_low
            sweep_side = 1 if crossed_high else -1
            swept_mass = sum(pool_mass(pool, i) for pool in crossed)
            swept_touches = sum(pool.touches for pool in crossed)
            outer = max(crossed, key=lambda item: item.level) if sweep_side > 0 else min(crossed, key=lambda item: item.level)
            known_targets = [pool for pool in active if pool not in crossed and pool.active]
            high_targets = tuple(sorted((snapshot(pool, i) for pool in known_targets if pool.side > 0), key=lambda item: item.level))
            low_targets = tuple(sorted((snapshot(pool, i) for pool in known_targets if pool.side < 0), key=lambda item: item.level, reverse=True))
            bar_range = max(h[i] - l[i], np.finfo(float).tiny)
            first_confirm = min(pool.first_confirm_i for pool in crossed)
            event_key = hashlib.sha256(f"{symbol}|{span}|{i}|{sweep_side}|{outer.level:.12g}".encode()).hexdigest()[:24]
            output.append(
                RawSweepEvent(
                    event_key,
                    symbol,
                    span,
                    i,
                    frame.index[i].isoformat(),
                    sweep_side,
                    float(outer.level),
                    float(swept_mass),
                    float(swept_touches),
                    max(0.0, (i - first_confirm) * 5.0 / 60.0),
                    float(o[i]),
                    float(h[i]),
                    float(l[i]),
                    float(c[i]),
                    float(atr[i]),
                    float(abs(c[i] - o[i]) / atr[i]),
                    float((c[i] - l[i]) / bar_range),
                    float(qv[max(0, i - 1)]) if math.isfinite(qv[max(0, i - 1)]) else 0.0,
                    high_targets,
                    low_targets,
                )
            )
            for pool in crossed:
                pool.active = False
        for side, level, volume_ratio, weight, is_htf in events_by_i.get(i, []):
            add_pool_observation(pools, side, level, i, atr[i], volume_ratio, weight, is_htf)
        if len(pools) > 2000:
            pools[:] = [pool for pool in pools if pool.active and (i - pool.last_confirm_i) * 5.0 / 60.0 <= POOL_CLUSTER_MAX_AGE_HOURS]
    return output


def _eligible_targets(candidates: Sequence[PoolSnapshot], entry: float, side: int, config: Config, swept_mass: float, atr: float) -> list[PoolSnapshot]:
    result: list[PoolSnapshot] = []
    for pool in candidates:
        if pool.touches < config.minimum_touches or pool.age_hours > config.maximum_pool_age_hours:
            continue
        if pool.mass < swept_mass * config.minimum_mass_ratio:
            continue
        distance = (pool.level - entry) * side
        if distance <= 0 or distance > MAX_TARGET_DISTANCE_ATR * atr:
            continue
        result.append(pool)
    return sorted(result, key=lambda pool: (abs(pool.level - entry), -pool.mass, pool.pool_id))


def _resolve_trade(frame: pd.DataFrame, config: Config, event: RawSweepEvent, side: int, target_pool: PoolSnapshot, stop: float) -> CandidateTrade:
    entry_i = event.event_i + 1
    entry = float(frame["open"].iloc[entry_i])
    target = target_pool.level
    o = frame["open"].to_numpy(float)
    h = frame["high"].to_numpy(float)
    l = frame["low"].to_numpy(float)
    c = frame["close"].to_numpy(float)
    valid = frame["valid"].to_numpy(bool)
    exit_i = len(frame) - 1
    exit_price = float(c[exit_i]) if math.isfinite(c[exit_i]) else entry
    reason = "boundary_mark"
    open_boundary = True
    for i in range(entry_i, len(frame)):
        if not valid[i]:
            exit_i, exit_price, reason, open_boundary = i, stop, "source_gap_structural_stop", False
            break
        if side > 0:
            if o[i] <= stop:
                exit_i, exit_price, reason, open_boundary = i, float(o[i]), "stop_gap", False
                break
            if l[i] <= stop and h[i] >= target:
                exit_i, exit_price, reason, open_boundary = i, stop, "stop_first", False
                break
            if l[i] <= stop:
                exit_i, exit_price, reason, open_boundary = i, stop, "protective_stop", False
                break
            if o[i] >= target or h[i] >= target:
                exit_i, exit_price, reason, open_boundary = i, target, "liquidity_pool_target", False
                break
        else:
            if o[i] >= stop:
                exit_i, exit_price, reason, open_boundary = i, float(o[i]), "stop_gap", False
                break
            if h[i] >= stop and l[i] <= target:
                exit_i, exit_price, reason, open_boundary = i, stop, "stop_first", False
                break
            if h[i] >= stop:
                exit_i, exit_price, reason, open_boundary = i, stop, "protective_stop", False
                break
            if o[i] <= target or l[i] <= target:
                exit_i, exit_price, reason, open_boundary = i, target, "liquidity_pool_target", False
                break
    mass_ratio = target_pool.mass / max(event.swept_mass, np.finfo(float).tiny)
    score = mass_ratio * ((target - entry) * side / max(abs(entry - stop), np.finfo(float).tiny)) * event.body_atr
    return CandidateTrade(
        config.config_id,
        event.event_key,
        event.symbol,
        config.mode,
        side,
        entry_i,
        exit_i,
        frame.index[entry_i].isoformat(),
        frame.index[exit_i].isoformat(),
        entry,
        float(exit_price),
        float(stop),
        float(target),
        reason,
        float(score),
        event.quote_volume_prior,
        open_boundary,
        event.pool_level,
        event.swept_mass,
        target_pool.level,
        target_pool.mass,
        float(mass_ratio),
        event.swept_touches,
        target_pool.touches,
        event.body_atr,
    )


def candidates_from_events(frame: pd.DataFrame, events: Iterable[RawSweepEvent], config: Config) -> list[CandidateTrade]:
    output: list[CandidateTrade] = []
    for event in events:
        if event.pivot_span != config.pivot_span or event.swept_touches < config.minimum_touches or event.swept_age_hours > config.maximum_pool_age_hours:
            continue
        if event.body_atr < config.minimum_displacement_atr:
            continue
        if event.event_i + 1 >= len(frame) or not bool(frame["valid"].iloc[event.event_i + 1]):
            continue
        entry = float(frame["open"].iloc[event.event_i + 1])
        buffer = SWEEP_BUFFER_ATR * event.atr
        if config.mode == "rejection":
            if event.sweep_side > 0:
                if not (event.close_price < event.pool_level and event.close_price < event.open_price and event.close_location <= 0.40):
                    continue
                side, targets, stop = -1, event.low_targets, event.high_price + buffer
            else:
                if not (event.close_price > event.pool_level and event.close_price > event.open_price and event.close_location >= 0.60):
                    continue
                side, targets, stop = 1, event.high_targets, event.low_price - buffer
        else:
            if event.sweep_side > 0:
                if not (event.close_price > event.pool_level + buffer and event.close_price > event.open_price and event.close_location >= 0.70):
                    continue
                side, targets, stop = 1, event.high_targets, min(event.low_price - buffer, event.pool_level - buffer)
            else:
                if not (event.close_price < event.pool_level - buffer and event.close_price < event.open_price and event.close_location <= 0.30):
                    continue
                side, targets, stop = -1, event.low_targets, max(event.high_price + buffer, event.pool_level + buffer)
        eligible = _eligible_targets(targets, entry, side, config, event.swept_mass, event.atr)
        if not eligible:
            continue
        target_pool = eligible[0]
        risk = (entry - stop) * side
        reward = (target_pool.level - entry) * side
        if risk <= 0 or reward <= 0 or reward / risk < config.minimum_reward_risk:
            continue
        output.append(_resolve_trade(frame, config, event, side, target_pool, stop))
    return output


def select_global(candidates: Iterable[CandidateTrade], removed: set[str] | None = None) -> list[CandidateTrade]:
    removed = removed or set()
    ordered = sorted(
        (item for item in candidates if item.event_key not in removed),
        key=lambda item: (pd.Timestamp(item.entry_time), -item.score, SYMBOL_ORDER[item.symbol], item.event_key),
    )
    selected: list[CandidateTrade] = []
    slot_free = pd.Timestamp.min.tz_localize("UTC")
    for item in ordered:
        entry = pd.Timestamp(item.entry_time)
        if entry < slot_free:
            continue
        selected.append(item)
        slot_free = pd.Timestamp(item.exit_time)
        if item.open_at_boundary:
            break
    return selected


def replay_account(selected: Iterable[CandidateTrade], cost_bps: float) -> tuple[list[AccountTrade], dict[str, float | bool]]:
    nav = INITIAL_NAV
    peak = INITIAL_NAV
    max_drawdown = 0.0
    output: list[AccountTrade] = []
    terminal = False
    for item in selected:
        if nav <= 0:
            terminal = True
            break
        stop_fraction = abs(item.entry_price - item.stop_price) / item.entry_price
        reserve = stop_fraction + cost_bps / 10_000.0
        if reserve <= 0:
            continue
        risk_notional = nav * RISK_FRACTION / reserve
        notional = min(nav * NOTIONAL_CAP_MULTIPLE, item.quote_volume_prior * PARTICIPATION_CAP, risk_notional)
        if not math.isfinite(notional) or notional < 5.0:
            continue
        quantity = notional / item.entry_price
        gross = item.side * quantity * (item.exit_price - item.entry_price)
        cost = notional * cost_bps / 10_000.0
        before = nav
        nav = max(0.0, nav + gross - cost)
        pnl = nav - before
        peak = max(peak, nav)
        max_drawdown = max(max_drawdown, 1.0 - nav / max(peak, 1e-12))
        stop_nav = max(0.0, before + item.side * quantity * (item.stop_price - item.entry_price) - cost)
        max_drawdown = max(max_drawdown, 1.0 - stop_nav / max(peak, 1e-12))
        output.append(AccountTrade(item.config_id, item.event_key, item.symbol, item.mode, item.side, item.entry_time, item.exit_time, item.entry_price, item.exit_price, item.stop_price, item.target_price, quantity, notional, gross, cost, pnl, pnl / before if before > 0 else -1.0, before, nav, item.exit_reason, item.open_at_boundary))
        if nav <= 0:
            terminal = True
            max_drawdown = 1.0
            break
    return output, {"nav": nav, "maximum_drawdown": max_drawdown, "terminal_account_loss": terminal}


def _compound(values: Iterable[float]) -> float:
    array = np.asarray(list(values), dtype=float)
    if not len(array):
        return 0.0
    if np.any(array <= -1.0):
        return -1.0
    return float(np.prod(1.0 + array) - 1.0)


def metrics(trades: list[AccountTrade], state: dict[str, float | bool], year: int) -> dict[str, object]:
    days = 366 if calendar.isleap(year) else 365
    ending_nav = float(state["nav"])
    total = ending_nav / INITIAL_NAV - 1.0
    geom = -1.0 if ending_nav <= 0 else float(np.expm1(np.log(ending_nav / INITIAL_NAV) / days))
    if not trades:
        return {"completed_trades": 0, "total_return": total, "geometric_calendar_day_growth": geom, "profit_factor": None, "median_trade_bps": None, "maximum_drawdown": float(state["maximum_drawdown"]), "top_five_positive_pnl_share": 1.0, "open_position_count": 0, "first_half_return": 0.0, "second_half_return": 0.0, "terminal_account_loss": bool(state["terminal_account_loss"]), "ending_nav": ending_nav}
    frame = pd.DataFrame([asdict(item) for item in trades])
    completed = frame.loc[~frame.open_at_boundary].copy()
    positive = completed.loc[completed.net_pnl > 0, "net_pnl"].to_numpy(float)
    negative = completed.loc[completed.net_pnl < 0, "net_pnl"].to_numpy(float)
    positive_sum = float(positive.sum())
    midpoint = pd.Timestamp(f"{year}-07-01", tz="UTC")
    frame["exit_dt"] = pd.to_datetime(frame.exit_time, utc=True)
    first = frame.loc[frame.exit_dt < midpoint, "account_return"].to_numpy(float)
    second = frame.loc[frame.exit_dt >= midpoint, "account_return"].to_numpy(float)
    return {
        "completed_trades": int(len(completed)),
        "total_return": total,
        "geometric_calendar_day_growth": geom,
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) else None,
        "median_trade_bps": float(np.median(completed.account_return.to_numpy(float)) * 10_000) if len(completed) else None,
        "maximum_drawdown": float(state["maximum_drawdown"]),
        "top_five_positive_pnl_share": float(np.sort(positive)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0,
        "open_position_count": int(frame.open_at_boundary.sum()),
        "first_half_return": _compound(first),
        "second_half_return": _compound(second),
        "terminal_account_loss": bool(state["terminal_account_loss"]),
        "ending_nav": ending_nav,
        "symbol_trade_count": completed.groupby("symbol").size().to_dict() if len(completed) else {},
        "mode_trade_count": completed.groupby("mode").size().to_dict() if len(completed) else {},
        "exit_reason_count": frame.groupby("exit_reason").size().to_dict(),
    }


def preliminary_pass(by_cost: dict[float, dict[str, object]]) -> bool:
    base = by_cost[12.0]
    return (
        not bool(base["terminal_account_loss"])
        and int(base["completed_trades"]) >= 40
        and all(float(by_cost[cost]["total_return"]) > 0 for cost in COSTS_BPS)
        and base["median_trade_bps"] is not None
        and float(base["median_trade_bps"]) > 0
        and base["profit_factor"] is not None
        and float(base["profit_factor"]) >= 1.15
        and float(base["maximum_drawdown"]) <= 0.25
        and float(base["first_half_return"]) > 0
        and float(base["second_half_return"]) > 0
        and float(base["top_five_positive_pnl_share"]) <= 0.35
        and int(base["open_position_count"]) == 0
    )


def exact_top10_removed(candidates: list[CandidateTrade], baseline: list[AccountTrade], cost_bps: float) -> tuple[float, int]:
    completed = [item for item in baseline if not item.open_at_boundary]
    if not completed:
        return 0.0, 0
    count = max(1, int(math.ceil(len(completed) * 0.10)))
    winners = sorted(completed, key=lambda item: item.net_pnl, reverse=True)[:count]
    removed = {item.event_key for item in winners}
    selected = select_global(candidates, removed)
    _, state = replay_account(selected, cost_bps)
    return float(state["nav"]) / INITIAL_NAV - 1.0, len(removed)


def stage_data(year: int, cache: Path, output: Path) -> dict[str, pd.DataFrame]:
    if year in PROHIBITED_YEARS:
        raise ValueError(f"sealed year requested: {year}")
    frames: dict[str, pd.DataFrame] = {}
    source_records: list[dict[str, object]] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-liquidity-mass/1.0"
        for symbol in SYMBOLS:
            raw, records = load_year(symbol, year, cache, session)
            source_records.extend(records)
            frames[symbol] = prepare(raw)
    write_json(output / f"SOURCE_MANIFEST_{year}.json", {"claim_id": CLAIM_ID, "engine_version": ENGINE_VERSION, "year": year, "records": source_records, "2024_2026_opened": False})
    return frames


def build_event_cache(frames: dict[str, pd.DataFrame], output: Path, year: int) -> dict[tuple[str, int], list[RawSweepEvent]]:
    cache: dict[tuple[str, int], list[RawSweepEvent]] = {}
    diagnostics: list[dict[str, object]] = []
    for symbol in SYMBOLS:
        for span in (2, 3):
            events = build_sweep_events(frames[symbol], symbol, span)
            cache[(symbol, span)] = events
            diagnostics.append({"year": year, "symbol": symbol, "pivot_span": span, "raw_sweep_event_count": len(events), "high_sweeps": sum(event.sweep_side > 0 for event in events), "low_sweeps": sum(event.sweep_side < 0 for event in events)})
    pd.DataFrame(diagnostics).to_csv(output / f"SWEEP_EVENT_DIAGNOSTICS_{year}.csv", index=False)
    return cache


def evaluate_stage(frames: dict[str, pd.DataFrame], event_cache: dict[tuple[str, int], list[RawSweepEvent]], year: int, selected_configs: Iterable[Config] | None = None) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    cfgs = tuple(selected_configs or configs())
    rows: list[dict[str, object]] = []
    ledger_rows: list[dict[str, object]] = []
    for number, config in enumerate(cfgs, 1):
        candidates: list[CandidateTrade] = []
        for symbol in SYMBOLS:
            candidates.extend(candidates_from_events(frames[symbol], event_cache[(symbol, config.pivot_span)], config))
        selected = select_global(candidates)
        by_cost: dict[float, dict[str, object]] = {}
        accounts: dict[float, list[AccountTrade]] = {}
        for cost in COSTS_BPS:
            account, state = replay_account(selected, cost)
            accounts[cost] = account
            by_cost[cost] = metrics(account, state, year)
        prelim = preliminary_pass(by_cost)
        removed_return = None
        removed_count = 0
        gate = False
        if prelim:
            removed_return, removed_count = exact_top10_removed(candidates, accounts[18.0], 18.0)
            gate = removed_return > 0
        for cost in COSTS_BPS:
            rows.append({"stage_year": year, "config_id": config.config_id, **asdict(config), "candidate_trade_count": len(candidates), "global_selected_count": len(selected), "cost_bps": cost, **by_cost[cost], "preliminary_gate_pass": prelim, "exact_top10_removed_return_18bps": removed_return, "exact_top10_removed_count": removed_count, "stage_gate_pass": gate})
        for item in accounts[12.0]:
            row = asdict(item)
            row["stage_year"] = year
            row["cost_bps"] = 12.0
            ledger_rows.append(row)
        print(json.dumps({"progress": f"{number}/{len(cfgs)}", "config_id": config.config_id, "mode": config.mode, "candidates": len(candidates), "selected": len(selected), "preliminary": prelim, "gate": gate}), flush=True)
    return pd.DataFrame(rows), ledger_rows


def choose_survivors(grid: pd.DataFrame) -> list[str]:
    base = grid.loc[(grid.cost_bps == 18.0) & grid.stage_gate_pass].copy()
    if base.empty:
        return []
    base = base.sort_values(["geometric_calendar_day_growth", "exact_top10_removed_return_18bps", "maximum_drawdown", "config_id"], ascending=[False, False, True, True])
    return base.config_id.astype(str).head(6).tolist()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def run(output: Path, cache: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    fit_frames = stage_data(FIT_YEAR, cache, output)
    fit_events = build_event_cache(fit_frames, output, FIT_YEAR)
    fit_grid, fit_ledger = evaluate_stage(fit_frames, fit_events, FIT_YEAR)
    fit_grid.to_csv(output / "FIT_GRID.csv", index=False)
    pd.DataFrame(fit_ledger).to_csv(output / "FIT_12BPS_LEDGER.csv", index=False)
    survivors = choose_survivors(fit_grid)
    write_json(output / "FROZEN_FIT_SURVIVORS.json", {"claim_id": CLAIM_ID, "engine_version": ENGINE_VERSION, "fit_year": FIT_YEAR, "survivor_config_ids": survivors, "fit_grid_sha256": hashlib.sha256((output / "FIT_GRID.csv").read_bytes()).hexdigest(), "development_opened": bool(survivors), "2024_2026_opened": False})
    development_survivors: list[str] = []
    if survivors:
        lookup = {cell.config_id: cell for cell in configs()}
        frozen = [lookup[item] for item in survivors]
        development_frames = stage_data(DEVELOPMENT_YEAR, cache, output)
        development_events = build_event_cache(development_frames, output, DEVELOPMENT_YEAR)
        development_grid, development_ledger = evaluate_stage(development_frames, development_events, DEVELOPMENT_YEAR, frozen)
        development_grid.to_csv(output / "DEVELOPMENT_GRID.csv", index=False)
        pd.DataFrame(development_ledger).to_csv(output / "DEVELOPMENT_12BPS_LEDGER.csv", index=False)
        development_survivors = choose_survivors(development_grid)
    fit_base = fit_grid.loc[fit_grid.cost_bps == 12.0].copy()
    best = None
    if not fit_base.empty:
        best = fit_base.sort_values(["geometric_calendar_day_growth", "config_id"], ascending=[False, True]).iloc[0].to_dict()
    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "engine_version": ENGINE_VERSION,
        "status": "DEVELOPMENT_SURVIVOR" if development_survivors else "TESTED_BELOW_GATE",
        "fit_year": FIT_YEAR,
        "fit_candidate_count": 128,
        "fit_gate_pass_count": len(survivors),
        "frozen_fit_survivors": survivors,
        "development_year": DEVELOPMENT_YEAR if survivors else None,
        "development_opened": bool(survivors),
        "development_gate_pass_count": len(development_survivors),
        "development_survivors": development_survivors,
        "best_fit_12bps": best,
        "ranking_eligible": False,
        "2024_opened": False,
        "2025_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "interpretation": "A development survivor requires a new exact-BBO, actual-funding sequential claim." if development_survivors else "The explicit unresolved-liquidity mass router failed its pre-2024 gate and should not receive adjacent tuning."
    }
    write_json(output / "RESULT.json", result)
    return result


def self_test() -> None:
    assert len(configs()) == 128
    try:
        month_url("BTCUSDT", 2024, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("sealed year was not rejected")
    pools: list[LiquidityPool] = []
    add_pool_observation(pools, 1, 100.0, 10, 1.0, 1.0, 1.0, False)
    add_pool_observation(pools, 1, 100.05, 20, 1.0, 4.0, 1.0, False)
    assert len(pools) == 1 and pools[0].touches == 2.0 and pool_mass(pools[0], 30) > 0
    print(json.dumps({"self_test": "PASS", "configs": len(configs())}))


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
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
