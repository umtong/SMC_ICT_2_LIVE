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
from typing import Iterable

import numpy as np
import pandas as pd
import requests

CLAIM_ID = "CLM-20260726-1634-MMXM-001"
ENGINE_VERSION = "MMXM-LIFECYCLE-V1"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
FIT_YEAR = 2022
DEVELOPMENT_YEAR = 2023
PROHIBITED_YEARS = (2024, 2025, 2026)
COSTS_BPS = (12.0, 18.0, 24.0)
INITIAL_NAV = 10_000.0
RISK_FRACTION = 0.005
NOTIONAL_CAP_MULTIPLE = 3.0
PARTICIPATION_CAP = 0.001
PIVOT_SPAN = 3
MIN_RR = 2.0
BASE_URL = "https://public.bybit.com/kline_for_metatrader4"
SYMBOL_ORDER = {symbol: i for i, symbol in enumerate(SYMBOLS)}


@dataclass(frozen=True)
class Config:
    oc_hours: int
    compression_atr: float
    shelf_count: int
    excursion_units: float
    displacement_atr: float
    entry_mode: str

    @property
    def config_id(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:20]


@dataclass(frozen=True)
class CandidateTrade:
    config_id: str
    event_key: str
    symbol: str
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
    oc_start: str
    oc_end: str
    break_time: str
    sweep_time: str
    smr_time: str
    shelf_count_observed: int
    excursion_units_observed: float
    displacement_atr_observed: float


@dataclass
class AccountTrade:
    config_id: str
    event_key: str
    symbol: str
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
    cells = []
    for values in itertools.product(
        (4, 8),
        (1.5, 2.5),
        (2, 3),
        (0.5, 1.0),
        (0.8, 1.2),
        ("broken_shelf", "displacement_body_midpoint"),
    ):
        cells.append(Config(*values))
    assert len(cells) == 64
    assert len({cell.config_id for cell in cells}) == 64
    return tuple(cells)


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
        last: Exception | None = None
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
            except Exception as exc:  # pragma: no cover - network retry
                last = exc
                if tmp.exists():
                    tmp.unlink()
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        if last and not path.exists():  # pragma: no cover
            raise last
    with gzip.open(path, "rb") as handle:
        while handle.read(1 << 20):
            pass
    return {
        "url": url,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


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
    raw = pd.read_csv(path, compression="gzip", header=None, low_memory=False)
    return _coerce_kline(raw)


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
        record.update({
            "symbol": symbol,
            "year": year,
            "month": month,
            "row_count": int(len(frame)),
            "first_timestamp": frame.index[0].isoformat(),
            "last_timestamp": frame.index[-1].isoformat(),
        })
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
    invalid = ~valid.astype(bool)
    return invalid.cumsum()


def _segmented_rolling_mean(values: pd.Series, valid: pd.Series, window: int) -> pd.Series:
    segment = _segment_ids(valid)
    out = values.where(valid).groupby(segment).rolling(window, min_periods=window).mean()
    return out.reset_index(level=0, drop=True).reindex(values.index)


def confirmed_pivots(high: np.ndarray, low: np.ndarray, valid: np.ndarray, span: int = PIVOT_SPAN) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
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
    valid = result["valid"].to_numpy(bool)
    prev_close = result["close"].shift(1)
    tr = pd.concat(
        [
            result["high"] - result["low"],
            (result["high"] - prev_close).abs(),
            (result["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    result["atr5"] = _segmented_rolling_mean(tr, result["valid"], 20)
    ph, pl, phi, pli = confirmed_pivots(
        result["high"].to_numpy(float), result["low"].to_numpy(float), valid
    )
    result["pivot_high_confirmed"] = ph
    result["pivot_low_confirmed"] = pl
    result["pivot_high_origin"] = phi
    result["pivot_low_origin"] = pli

    indexed = result.set_index("close_time")
    grouped = indexed[["open", "high", "low", "close", "volume", "valid"]].resample(
        "60min", label="right", closed="right"
    )
    bars60 = pd.DataFrame({
        "open": grouped["open"].first(),
        "high": grouped["high"].max(),
        "low": grouped["low"].min(),
        "close": grouped["close"].last(),
        "volume": grouped["volume"].sum(min_count=1),
        "count": grouped["valid"].sum(),
    })
    bars60["valid"] = bars60["count"].eq(12) & np.isfinite(bars60[["open", "high", "low", "close"]]).all(axis=1)
    prev60 = bars60["close"].shift(1)
    tr60 = pd.concat(
        [bars60["high"] - bars60["low"], (bars60["high"] - prev60).abs(), (bars60["low"] - prev60).abs()],
        axis=1,
    ).max(axis=1)
    bars60["atr60"] = _segmented_rolling_mean(tr60, bars60["valid"], 20)
    result.attrs["bars60"] = bars60
    return result


def original_consolidations(prepared: pd.DataFrame, oc_hours: int, compression_atr: float) -> pd.DataFrame:
    bars = prepared.attrs["bars60"].copy()
    segment = _segment_ids(bars["valid"])
    high = bars["high"].where(bars["valid"])
    low = bars["low"].where(bars["valid"])
    close = bars["close"].where(bars["valid"])
    oc_high = high.groupby(segment).rolling(oc_hours, min_periods=oc_hours).max().reset_index(level=0, drop=True)
    oc_low = low.groupby(segment).rolling(oc_hours, min_periods=oc_hours).min().reset_index(level=0, drop=True)
    abs_move = close.diff().abs().where(bars["valid"])
    path = abs_move.groupby(segment).rolling(max(1, oc_hours - 1), min_periods=max(1, oc_hours - 1)).sum().reset_index(level=0, drop=True)
    net = (close - close.shift(oc_hours - 1)).abs()
    efficiency = net / path.replace(0, np.nan)
    oc_range = oc_high - oc_low
    valid = (
        bars["valid"]
        & oc_high.notna()
        & oc_low.notna()
        & bars["atr60"].notna()
        & (oc_range > 0)
        & (oc_range <= compression_atr * bars["atr60"])
        & (efficiency <= 0.35)
    )
    out = pd.DataFrame({
        "oc_valid": valid,
        "oc_high": oc_high,
        "oc_low": oc_low,
        "oc_mid": (oc_high + oc_low) / 2.0,
        "oc_range": oc_range,
        "oc_start": bars.index.to_series().shift(oc_hours - 1) - pd.Timedelta(hours=1),
        "oc_end": bars.index,
    })
    mapped = out.reindex(prepared["close_time"], method="ffill")
    mapped.index = prepared.index
    return mapped


def _iso(value: pd.Timestamp) -> str:
    return pd.Timestamp(value).isoformat()


def _resolve_trade(
    frame: pd.DataFrame,
    config: Config,
    symbol: str,
    side: int,
    entry_i: int,
    stop: float,
    target: float,
    score: float,
    metadata: dict[str, object],
) -> CandidateTrade:
    o = frame["open"].to_numpy(float)
    h = frame["high"].to_numpy(float)
    l = frame["low"].to_numpy(float)
    c = frame["close"].to_numpy(float)
    v = frame["valid"].to_numpy(bool)
    entry = float(o[entry_i])
    exit_i = len(frame) - 1
    exit_price = float(c[exit_i]) if np.isfinite(c[exit_i]) else entry
    reason = "boundary_mark"
    open_boundary = True
    for i in range(entry_i, len(frame)):
        if not v[i]:
            exit_i = i
            exit_price = stop
            reason = "source_gap_structural_stop"
            open_boundary = False
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
                exit_i, exit_price, reason, open_boundary = i, target, "original_consolidation_target", False
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
                exit_i, exit_price, reason, open_boundary = i, target, "original_consolidation_target", False
                break
    event_key = hashlib.sha256(
        f"{config.config_id}|{symbol}|{side}|{frame.index[entry_i].isoformat()}|{metadata['smr_time']}".encode()
    ).hexdigest()[:24]
    prior = max(0, entry_i - 1)
    quote_volume = float(frame["close"].iloc[prior] * frame["volume"].iloc[prior])
    if not math.isfinite(quote_volume) or quote_volume < 0:
        quote_volume = 0.0
    return CandidateTrade(
        config_id=config.config_id,
        event_key=event_key,
        symbol=symbol,
        side=side,
        entry_i=entry_i,
        exit_i=exit_i,
        entry_time=_iso(frame.index[entry_i]),
        exit_time=_iso(frame.index[exit_i]),
        entry_price=entry,
        exit_price=float(exit_price),
        stop_price=float(stop),
        target_price=float(target),
        exit_reason=reason,
        score=float(score),
        quote_volume_prior=quote_volume,
        open_at_boundary=open_boundary,
        oc_start=str(metadata["oc_start"]),
        oc_end=str(metadata["oc_end"]),
        break_time=str(metadata["break_time"]),
        sweep_time=str(metadata["sweep_time"]),
        smr_time=str(metadata["smr_time"]),
        shelf_count_observed=int(metadata["shelf_count_observed"]),
        excursion_units_observed=float(metadata["excursion_units_observed"]),
        displacement_atr_observed=float(metadata["displacement_atr_observed"]),
    )


def detect_trades(frame: pd.DataFrame, config: Config, symbol: str) -> list[CandidateTrade]:
    mapped = original_consolidations(frame, config.oc_hours, config.compression_atr)
    o = frame["open"].to_numpy(float)
    h = frame["high"].to_numpy(float)
    l = frame["low"].to_numpy(float)
    c = frame["close"].to_numpy(float)
    atr = frame["atr5"].to_numpy(float)
    valid = frame["valid"].to_numpy(bool)
    ph = frame["pivot_high_confirmed"].to_numpy(float)
    pl = frame["pivot_low_confirmed"].to_numpy(float)
    phi = frame["pivot_high_origin"].to_numpy(np.int64)
    pli = frame["pivot_low_origin"].to_numpy(np.int64)

    latest_oc: dict[str, object] | None = None
    state = "seek"
    direction = 0
    break_i = -1
    shelves: list[tuple[int, float]] = []
    pivot_lows: list[tuple[int, float]] = []
    pivot_highs: list[tuple[int, float]] = []
    last_shelf: float | None = None
    sweep_extreme: float | None = None
    reversal_line: float | None = None
    disp_mid: float | None = None
    disp_strength = 0.0
    metadata: dict[str, object] = {}
    trades: list[CandidateTrade] = []

    def reset() -> None:
        nonlocal state, direction, break_i, shelves, pivot_lows, pivot_highs
        nonlocal last_shelf, sweep_extreme, reversal_line, disp_mid, disp_strength, metadata
        state = "seek"
        direction = 0
        break_i = -1
        shelves = []
        pivot_lows = []
        pivot_highs = []
        last_shelf = None
        sweep_extreme = None
        reversal_line = None
        disp_mid = None
        disp_strength = 0.0
        metadata = {}

    for i in range(len(frame) - 1):
        if not valid[i] or not math.isfinite(atr[i]) or atr[i] <= 0:
            latest_oc = None
            reset()
            continue

        if bool(mapped["oc_valid"].iloc[i]):
            latest_oc = {
                "high": float(mapped["oc_high"].iloc[i]),
                "low": float(mapped["oc_low"].iloc[i]),
                "mid": float(mapped["oc_mid"].iloc[i]),
                "range": float(mapped["oc_range"].iloc[i]),
                "start": mapped["oc_start"].iloc[i],
                "end": mapped["oc_end"].iloc[i],
            }

        if state == "seek":
            if latest_oc is None or not all(math.isfinite(float(latest_oc[k])) for k in ("high", "low", "mid", "range")):
                continue
            buffer = 0.05 * atr[i]
            if c[i] < float(latest_oc["low"]) - buffer:
                direction = 1
            elif c[i] > float(latest_oc["high"]) + buffer:
                direction = -1
            else:
                continue
            state = "engineer"
            break_i = i
            metadata = {
                "oc_high": float(latest_oc["high"]),
                "oc_low": float(latest_oc["low"]),
                "oc_mid": float(latest_oc["mid"]),
                "oc_range": float(latest_oc["range"]),
                "oc_start": _iso(pd.Timestamp(latest_oc["start"])),
                "oc_end": _iso(pd.Timestamp(latest_oc["end"])),
                "break_time": _iso(frame.index[i]),
            }
            shelves = []
            pivot_lows = []
            pivot_highs = []
            last_shelf = None
            sweep_extreme = None
            continue

        if state == "engineer":
            oc_high = float(metadata["oc_high"])
            oc_low = float(metadata["oc_low"])
            oc_mid = float(metadata["oc_mid"])
            oc_range = float(metadata["oc_range"])
            if (direction > 0 and c[i] >= oc_mid) or (direction < 0 and c[i] <= oc_mid):
                reset()
                continue
            if math.isfinite(ph[i]) and phi[i] > break_i:
                pivot_highs.append((int(phi[i]), float(ph[i])))
                if direction > 0 and ph[i] < oc_low:
                    if not shelves or ph[i] < shelves[-1][1] - 0.05 * atr[i]:
                        shelves.append((int(phi[i]), float(ph[i])))
            if math.isfinite(pl[i]) and pli[i] > break_i:
                pivot_lows.append((int(pli[i]), float(pl[i])))
                if direction < 0 and pl[i] > oc_high:
                    if not shelves or pl[i] > shelves[-1][1] + 0.05 * atr[i]:
                        shelves.append((int(pli[i]), float(pl[i])))

            if len(shelves) < config.shelf_count:
                continue
            if direction > 0 and pivot_lows:
                reference = pivot_lows[-1][1]
                excursion = (oc_low - min(l[i], reference)) / oc_range
                if excursion >= config.excursion_units and l[i] < reference - 0.05 * atr[i] and c[i] > reference:
                    sweep_extreme = float(l[i])
                    last_shelf = shelves[-1][1]
                    metadata.update({
                        "sweep_time": _iso(frame.index[i]),
                        "shelf_count_observed": len(shelves),
                        "excursion_units_observed": excursion,
                    })
                    state = "await_smr"
            elif direction < 0 and pivot_highs:
                reference = pivot_highs[-1][1]
                excursion = (max(h[i], reference) - oc_high) / oc_range
                if excursion >= config.excursion_units and h[i] > reference + 0.05 * atr[i] and c[i] < reference:
                    sweep_extreme = float(h[i])
                    last_shelf = shelves[-1][1]
                    metadata.update({
                        "sweep_time": _iso(frame.index[i]),
                        "shelf_count_observed": len(shelves),
                        "excursion_units_observed": excursion,
                    })
                    state = "await_smr"
            continue

        if state == "await_smr":
            assert sweep_extreme is not None and last_shelf is not None
            if (direction > 0 and c[i] <= sweep_extreme) or (direction < 0 and c[i] >= sweep_extreme):
                reset()
                continue
            body = abs(c[i] - o[i])
            strength = body / atr[i]
            bar_range = max(h[i] - l[i], np.finfo(float).tiny)
            close_location = (c[i] - l[i]) / bar_range
            if direction > 0:
                confirmed = c[i] > last_shelf and strength >= config.displacement_atr and close_location >= 0.70
            else:
                confirmed = c[i] < last_shelf and strength >= config.displacement_atr and close_location <= 0.30
            if not confirmed:
                continue
            reversal_line = float(last_shelf)
            disp_mid = float((o[i] + c[i]) / 2.0)
            disp_strength = float(strength)
            metadata.update({
                "smr_time": _iso(frame.index[i]),
                "displacement_atr_observed": disp_strength,
            })
            state = "await_hold"
            continue

        if state == "await_hold":
            assert sweep_extreme is not None and reversal_line is not None and disp_mid is not None
            target = float(metadata["oc_high"] if direction > 0 else metadata["oc_low"])
            stop = float(sweep_extreme - 0.05 * atr[i] if direction > 0 else sweep_extreme + 0.05 * atr[i])
            if (direction > 0 and (l[i] <= stop or h[i] >= target)) or (direction < 0 and (h[i] >= stop or l[i] <= target)):
                reset()
                continue
            level = reversal_line if config.entry_mode == "broken_shelf" else disp_mid
            if direction > 0:
                hold = l[i] <= level and c[i] > level and c[i] > o[i]
            else:
                hold = h[i] >= level and c[i] < level and c[i] < o[i]
            if not hold or not valid[i + 1]:
                continue
            entry = float(o[i + 1])
            if direction > 0:
                risk = entry - stop
                reward = target - entry
            else:
                risk = stop - entry
                reward = entry - target
            if risk <= 0 or reward <= 0 or reward / risk < MIN_RR:
                reset()
                continue
            score = (reward / risk) * disp_strength * (1.0 + 0.15 * len(shelves))
            trades.append(_resolve_trade(frame, config, symbol, direction, i + 1, stop, target, score, metadata))
            reset()
    return trades


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
        entry = item.entry_price
        stop_distance = abs(entry - item.stop_price) / entry
        reserve = stop_distance + cost_bps / 10_000.0
        if reserve <= 0:
            continue
        risk_notional = nav * RISK_FRACTION / reserve
        cap_notional = nav * NOTIONAL_CAP_MULTIPLE
        liquidity_notional = item.quote_volume_prior * PARTICIPATION_CAP
        notional = min(risk_notional, cap_notional, liquidity_notional)
        if not math.isfinite(notional) or notional < 5.0:
            continue
        quantity = notional / entry
        gross = item.side * quantity * (item.exit_price - entry)
        cost = notional * cost_bps / 10_000.0
        before = nav
        nav = max(0.0, nav + gross - cost)
        pnl = nav - before
        peak = max(peak, nav)
        max_drawdown = max(max_drawdown, 1.0 - nav / max(peak, 1e-12))
        stop_nav = max(0.0, before + item.side * quantity * (item.stop_price - entry) - cost)
        max_drawdown = max(max_drawdown, 1.0 - stop_nav / max(peak, 1e-12))
        output.append(AccountTrade(
            config_id=item.config_id,
            event_key=item.event_key,
            symbol=item.symbol,
            side=item.side,
            entry_time=item.entry_time,
            exit_time=item.exit_time,
            entry_price=entry,
            exit_price=item.exit_price,
            stop_price=item.stop_price,
            target_price=item.target_price,
            quantity=quantity,
            notional=notional,
            gross_pnl=gross,
            cost=cost,
            net_pnl=pnl,
            account_return=pnl / before if before > 0 else -1.0,
            nav_before=before,
            nav_after=nav,
            exit_reason=item.exit_reason,
            open_at_boundary=item.open_at_boundary,
        ))
        if nav <= 0:
            terminal = True
            max_drawdown = 1.0
            break
    return output, {"nav": nav, "maximum_drawdown": max_drawdown, "terminal_account_loss": terminal}


def _compound(returns: Iterable[float]) -> float:
    values = np.asarray(list(returns), dtype=float)
    if not len(values):
        return 0.0
    if np.any(values <= -1.0):
        return -1.0
    return float(np.prod(1.0 + values) - 1.0)


def metrics(trades: list[AccountTrade], state: dict[str, float | bool], year: int) -> dict[str, object]:
    days = 366 if calendar.isleap(year) else 365
    ending_nav = float(state["nav"])
    total = ending_nav / INITIAL_NAV - 1.0
    geom = -1.0 if ending_nav <= 0 else float(np.expm1(np.log(ending_nav / INITIAL_NAV) / days))
    if not trades:
        return {
            "completed_trades": 0,
            "total_return": total,
            "geometric_calendar_day_growth": geom,
            "profit_factor": None,
            "median_trade_bps": None,
            "maximum_drawdown": float(state["maximum_drawdown"]),
            "top_five_positive_pnl_share": 1.0,
            "open_position_count": 0,
            "first_half_return": 0.0,
            "second_half_return": 0.0,
            "terminal_account_loss": bool(state["terminal_account_loss"]),
            "ending_nav": ending_nav,
        }
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


def evaluate_stage(frames: dict[str, pd.DataFrame], year: int, selected_configs: Iterable[Config] | None = None) -> tuple[pd.DataFrame, dict[str, list[CandidateTrade]], list[dict[str, object]]]:
    cfgs = tuple(selected_configs or configs())
    candidate_cache: dict[str, list[CandidateTrade]] = {}
    rows: list[dict[str, object]] = []
    ledgers: list[dict[str, object]] = []
    for number, config in enumerate(cfgs, 1):
        candidates: list[CandidateTrade] = []
        for symbol in SYMBOLS:
            candidates.extend(detect_trades(frames[symbol], config, symbol))
        candidate_cache[config.config_id] = candidates
        selected = select_global(candidates)
        by_cost: dict[float, dict[str, object]] = {}
        account_by_cost: dict[float, list[AccountTrade]] = {}
        for cost in COSTS_BPS:
            account, state = replay_account(selected, cost)
            account_by_cost[cost] = account
            by_cost[cost] = metrics(account, state, year)
        prelim = preliminary_pass(by_cost)
        top10_return = None
        removed_count = 0
        gate = False
        if prelim:
            top10_return, removed_count = exact_top10_removed(candidates, account_by_cost[18.0], 18.0)
            gate = top10_return > 0
        for cost in COSTS_BPS:
            metric = by_cost[cost]
            rows.append({
                "stage_year": year,
                "config_id": config.config_id,
                **asdict(config),
                "candidate_event_count": len(candidates),
                "global_selected_count": len(selected),
                "cost_bps": cost,
                **metric,
                "preliminary_gate_pass": prelim,
                "exact_top10_removed_return_18bps": top10_return,
                "exact_top10_removed_count": removed_count,
                "stage_gate_pass": gate,
            })
        for item in account_by_cost[12.0]:
            ledger = asdict(item)
            ledger["stage_year"] = year
            ledger["cost_bps"] = 12.0
            ledgers.append(ledger)
        print(json.dumps({
            "progress": f"{number}/{len(cfgs)}",
            "config_id": config.config_id,
            "candidate_events": len(candidates),
            "selected": len(selected),
            "preliminary": prelim,
            "gate": gate,
        }), flush=True)
    return pd.DataFrame(rows), candidate_cache, ledgers


def choose_fit_survivors(grid: pd.DataFrame) -> list[str]:
    base = grid.loc[(grid.cost_bps == 18.0) & grid.stage_gate_pass].copy()
    if base.empty:
        return []
    base = base.sort_values(
        ["geometric_calendar_day_growth", "exact_top10_removed_return_18bps", "maximum_drawdown", "config_id"],
        ascending=[False, False, True, True],
    )
    return base.config_id.astype(str).head(4).tolist()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def stage_data(year: int, cache: Path, output: Path) -> dict[str, pd.DataFrame]:
    if year in PROHIBITED_YEARS:
        raise ValueError(f"sealed year requested: {year}")
    frames: dict[str, pd.DataFrame] = {}
    source_records: list[dict[str, object]] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-MMXM-lifecycle/1.0"
        for symbol in SYMBOLS:
            raw, records = load_year(symbol, year, cache, session)
            source_records.extend(records)
            frames[symbol] = prepare(raw)
    write_json(output / f"SOURCE_MANIFEST_{year}.json", {
        "claim_id": CLAIM_ID,
        "engine_version": ENGINE_VERSION,
        "year": year,
        "records": source_records,
        "2024_2026_opened": False,
    })
    return frames


def run(output: Path, cache: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    fit_frames = stage_data(FIT_YEAR, cache, output)
    fit_grid, _, fit_ledgers = evaluate_stage(fit_frames, FIT_YEAR)
    fit_grid.to_csv(output / "FIT_GRID.csv", index=False)
    pd.DataFrame(fit_ledgers).to_csv(output / "FIT_12BPS_LEDGER.csv", index=False)
    survivors = choose_fit_survivors(fit_grid)
    write_json(output / "FROZEN_FIT_SURVIVORS.json", {
        "claim_id": CLAIM_ID,
        "engine_version": ENGINE_VERSION,
        "fit_year": FIT_YEAR,
        "survivor_config_ids": survivors,
        "fit_grid_sha256": hashlib.sha256((output / "FIT_GRID.csv").read_bytes()).hexdigest(),
        "development_opened": bool(survivors),
        "2024_2026_opened": False,
    })

    development_survivors: list[str] = []
    if survivors:
        cfg_lookup = {cell.config_id: cell for cell in configs()}
        frozen = [cfg_lookup[item] for item in survivors]
        development_frames = stage_data(DEVELOPMENT_YEAR, cache, output)
        development_grid, _, development_ledgers = evaluate_stage(development_frames, DEVELOPMENT_YEAR, frozen)
        development_grid.to_csv(output / "DEVELOPMENT_GRID.csv", index=False)
        pd.DataFrame(development_ledgers).to_csv(output / "DEVELOPMENT_12BPS_LEDGER.csv", index=False)
        development_survivors = choose_fit_survivors(development_grid)

    fit_base = fit_grid.loc[fit_grid.cost_bps == 12.0].copy()
    best_fit = None
    if not fit_base.empty:
        best = fit_base.sort_values(["geometric_calendar_day_growth", "config_id"], ascending=[False, True]).iloc[0]
        best_fit = best.to_dict()
    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "engine_version": ENGINE_VERSION,
        "status": "DEVELOPMENT_SURVIVOR" if development_survivors else "TESTED_BELOW_GATE",
        "fit_year": FIT_YEAR,
        "fit_candidate_count": 64,
        "fit_gate_pass_count": len(survivors),
        "frozen_fit_survivors": survivors,
        "development_year": DEVELOPMENT_YEAR if survivors else None,
        "development_opened": bool(survivors),
        "development_gate_pass_count": len(development_survivors),
        "development_survivors": development_survivors,
        "best_fit_12bps": best_fit,
        "ranking_eligible": False,
        "2024_opened": False,
        "2025_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "interpretation": (
            "A development survivor requires a new sequential exact-BBO and actual-funding claim."
            if development_survivors
            else "The exact full MMXM lifecycle translation failed its pre-2024 after-cost gate and should not receive adjacent threshold tuning."
        ),
    }
    write_json(output / "RESULT.json", result)
    return result


def self_test() -> None:
    assert len(configs()) == 64
    try:
        month_url("BTCUSDT", 2024, 1)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("sealed year was not rejected")
    high = np.array([1, 2, 3, 5, 3, 2, 1], dtype=float)
    low = np.array([0, 0, 0, 0, 0, 0, 0], dtype=float)
    valid = np.ones(7, dtype=bool)
    ph, _, origin, _ = confirmed_pivots(high, low, valid, span=3)
    assert np.isnan(ph[:6]).all() and ph[6] == 5 and origin[6] == 3
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
