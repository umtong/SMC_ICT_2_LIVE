from __future__ import annotations

import hashlib
import math
import shutil
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

CLAIM_ID = "CLM-20260726-ML-QUEUE-FVG-MAKER-001"
RESULT_ID = "RES-20260726-ML-QUEUE-FVG-MAKER-001"
FIT_DATE = "2022-07-01"
DEV_DATE = "2023-07-01"
SYMBOL = "BTCUSDT"
DAY_US = 86_400_000_000
ACK_US = 100_000
EXIT_LATENCY_US = 100_000
ORDER_NOTIONAL_USDT = 10_000.0
QUEUE_MULTIPLIER = 1.5
COSTS_BPS = (12.0, 18.0, 24.0)
DECISION_COST_BPS = 18.0
FEATURES = (
    "sweep_depth_bps", "reclaim_fraction", "displacement_body_bps",
    "fvg_width_bps", "target_bps", "stop_bps", "r_multiple",
    "spread_bps", "side_depth_imbalance", "side_microprice_skew_bps",
    "side_flow_3s", "queue_ratio",
)
SOURCES = {
    FIT_DATE: {
        "book": ("https://datasets.tardis.dev/v1/bybit/book_snapshot_5/2022/07/01/BTCUSDT.csv.gz", 50_953_798, "7787c36c35a591c8fcf1bf629d8b82624ac61a6b970f09cdbcff01c9afb624b6"),
        "trades": ("https://datasets.tardis.dev/v1/bybit/trades/2022/07/01/BTCUSDT.csv.gz", 36_158_133, "fd1b225da124666f1411b53c4537aba721ce443f715737135b89316f81d0146f"),
    },
    DEV_DATE: {
        "book": ("https://datasets.tardis.dev/v1/bybit/book_snapshot_5/2023/07/01/BTCUSDT.csv.gz", 15_194_559, "4ed34a4de337e276e8e58df96780bbb8868d1ead3b9c49839d295fe532aa2753"),
        "trades": ("https://datasets.tardis.dev/v1/bybit/trades/2023/07/01/BTCUSDT.csv.gz", 7_480_525, "0707925b9320626560a5aa2ce89c78666b27266c92626fc6a6ff5236a0d5b301"),
    },
}


class ResearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceRecord:
    date: str
    kind: str
    url: str
    path: str
    bytes: int
    sha256: str


@dataclass
class Event:
    event_id: str
    date: str
    direction: int
    sweep_second: int
    mss_second: int
    decision_us: int
    ack_us: int
    prior_high: float
    prior_low: float
    raid_extreme: float
    fvg_low: float
    fvg_high: float
    limit_price: float
    stop_price: float
    target_price: float
    tick_size: float
    sweep_depth_bps: float
    reclaim_fraction: float
    displacement_body_bps: float
    fvg_width_bps: float
    target_bps: float
    stop_bps: float
    r_multiple: float
    side_flow_3s: float
    ack_valid: bool = False
    reject_reason: str = ""
    spread_bps: float = math.nan
    side_depth_imbalance: float = math.nan
    side_microprice_skew_bps: float = math.nan
    queue_ahead: float = math.nan
    order_qty: float = math.nan
    queue_ratio: float = math.nan
    outcome: str = "UNSIMULATED"
    fill_us: int | None = None
    exit_trigger_us: int | None = None
    release_us: int | None = None
    exit_reason: str = ""
    entry_price: float = math.nan
    exit_price: float = math.nan
    gross_bps: float = math.nan
    boundary_stop: bool = False

    def row(self) -> dict[str, object]:
        out = asdict(self)
        out["class_label"] = {"NO_FILL": 0, "TARGET": 1, "STOP": 2}.get(self.outcome, -1)
        return out


def utc_start_us(date: str) -> int:
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1_000_000)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, path: Path, size: int, digest: str) -> None:
    if any(f"/{year}/" in url for year in (2024, 2025, 2026)):
        raise ResearchError(f"sealed year requested: {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size == size and sha256_file(path) == digest:
        return
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.unlink(missing_ok=True)
    last: Exception | None = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "SMC_ICT_2_LIVE-ML-QUEUE-FVG/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response, tmp.open("wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            if tmp.stat().st_size != size or sha256_file(tmp) != digest:
                raise ResearchError(f"source identity mismatch: {url}")
            tmp.replace(path)
            return
        except Exception as exc:
            last = exc
            tmp.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(2**attempt)
    raise ResearchError(f"download failed: {url}: {last}")


def acquire(cache: Path) -> tuple[dict[str, dict[str, Path]], list[SourceRecord]]:
    paths: dict[str, dict[str, Path]] = {}
    records: list[SourceRecord] = []
    for date, items in SOURCES.items():
        paths[date] = {}
        for kind, (url, size, digest) in items.items():
            path = cache / date / f"{kind}_{SYMBOL}_{date}.csv.gz"
            download(url, path, size, digest)
            paths[date][kind] = path
            records.append(SourceRecord(date, kind, url, str(path), path.stat().st_size, sha256_file(path)))
            print(f"SOURCE_OK {date} {kind} {path.stat().st_size} {digest}", flush=True)
    return paths, records


def load_trades(path: Path, date: str) -> pd.DataFrame:
    wanted = ["local_timestamp", "timestamp", "side", "price", "amount"]
    frames: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, compression="gzip", usecols=wanted, chunksize=500_000):
        for column in ("local_timestamp", "timestamp", "price", "amount"):
            chunk[column] = pd.to_numeric(chunk[column], errors="coerce")
        chunk["side"] = chunk["side"].astype("string").str.lower()
        chunk = chunk.dropna(subset=["local_timestamp", "price", "amount", "side"])
        chunk = chunk.loc[(chunk.price > 0) & (chunk.amount > 0) & chunk.side.isin(["buy", "sell"])]
        frames.append(chunk)
    if not frames:
        raise ResearchError("empty trade source")
    out = pd.concat(frames, ignore_index=True)
    out["local_timestamp"] = out.local_timestamp.astype(np.int64)
    out = out.sort_values(["local_timestamp", "timestamp"], kind="stable")
    start = utc_start_us(date)
    out = out.loc[(out.local_timestamp >= start) & (out.local_timestamp < start + DAY_US)].reset_index(drop=True)
    if out.empty:
        raise ResearchError(f"no UTC local-arrival rows: {date}")
    return out


def infer_tick(prices: np.ndarray) -> float:
    unique = np.unique(np.round(prices[: min(len(prices), 500_000)], 8))
    diffs = np.diff(unique)
    diffs = diffs[diffs > 1e-8]
    if not len(diffs):
        raise ResearchError("tick inference failed")
    raw = float(np.quantile(diffs, 0.01))
    choices = np.array([0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0])
    return float(choices[np.argmin(np.abs(choices - raw))])


def second_bars(trades: pd.DataFrame, date: str) -> pd.DataFrame:
    start = utc_start_us(date)
    sec = ((trades.local_timestamp.to_numpy(np.int64) - start) // 1_000_000).astype(np.int32)
    price = trades.price.to_numpy(float)
    amount = trades.amount.to_numpy(float)
    side = trades.side.to_numpy()
    notional = price * amount
    work = pd.DataFrame({
        "sec": sec, "price": price, "notional": notional,
        "signed": np.where(side == "buy", notional, -notional),
    })
    bars = work.groupby("sec", sort=True).agg(
        open=("price", "first"), high=("price", "max"), low=("price", "min"),
        close=("price", "last"), signed_notional=("signed", "sum"),
        notional=("notional", "sum"), trade_count=("price", "size"),
    ).reindex(pd.RangeIndex(86_400, name="sec"))
    bars["close"] = bars.close.ffill().bfill()
    for column in ("open", "high", "low"):
        bars[column] = bars[column].fillna(bars.close)
    for column in ("signed_notional", "notional", "trade_count"):
        bars[column] = bars[column].fillna(0.0)
    return bars.reset_index()


def round_tick(value: float, tick: float) -> float:
    return round(round(value / tick) * tick, 8)


def _flow3(bars: pd.DataFrame, sec: int, direction: int) -> float:
    left = max(0, sec - 2)
    signed = float(bars.loc[left:sec, "signed_notional"].sum())
    total = float(bars.loc[left:sec, "notional"].sum())
    return direction * signed / total if total > 0 else 0.0


def detect_events(bars: pd.DataFrame, date: str, tick: float) -> list[Event]:
    high, low = bars.high.to_numpy(float), bars.low.to_numpy(float)
    open_, close = bars.open.to_numpy(float), bars.close.to_numpy(float)
    signed, notional = bars.signed_notional.to_numpy(float), bars.notional.to_numpy(float)
    ph = pd.Series(high).rolling(60, min_periods=60).max().shift(1).to_numpy()
    pl = pd.Series(low).rolling(60, min_periods=60).min().shift(1).to_numpy()
    ih = pd.Series(high).rolling(10, min_periods=10).max().shift(1).to_numpy()
    il = pd.Series(low).rolling(10, min_periods=10).min().shift(1).to_numpy()
    rbps = (high - low) / np.maximum(close, 1e-12) * 10_000
    median_range = pd.Series(rbps).rolling(30, min_periods=20).median().shift(1).to_numpy()
    day = utc_start_us(date)
    events: list[Event] = []
    next_allowed = 60
    for t in range(60, 86_380):
        if t < next_allowed or not np.isfinite(ph[t]) or not np.isfinite(median_range[t]):
            continue
        sweep_high = high[t] > ph[t] * 1.0001 and close[t] < ph[t]
        sweep_low = low[t] < pl[t] * 0.9999 and close[t] > pl[t]
        if sweep_high == sweep_low:
            continue
        direction = -1 if sweep_high else 1
        external = ph[t] if sweep_high else pl[t]
        raid = high[t] if sweep_high else low[t]
        internal = il[t] if sweep_high else ih[t]
        found: tuple[int, float, float] | None = None
        for j in range(t + 2, min(t + 13, 86_399)):
            body = abs(close[j] / open_[j] - 1) * 10_000
            flow_ok = direction * signed[j] > 0 and notional[j] > 0
            structure_ok = close[j] < internal if direction < 0 else close[j] > internal
            candle_ok = close[j] < open_[j] if direction < 0 else close[j] > open_[j]
            if not (flow_ok and structure_ok and candle_ok and body >= max(0.5, median_range[t])):
                continue
            if direction < 0:
                gap_low, gap_high = high[j], low[j - 2]
            else:
                gap_low, gap_high = high[j - 2], low[j]
            width = gap_high - gap_low
            if width <= 0 or width / ((gap_high + gap_low) / 2) * 10_000 < 0.5:
                continue
            found = j, gap_low, gap_high
            break
        if found is None:
            continue
        j, gap_low, gap_high = found
        limit = round_tick((gap_low + gap_high) / 2, tick)
        if direction > 0:
            stop = round_tick(min(low[t:j + 1]) - tick, tick)
            target = round_tick(ph[t], tick)
            target_bps, stop_bps = (target / limit - 1) * 10_000, (1 - stop / limit) * 10_000
        else:
            stop = round_tick(max(high[t:j + 1]) + tick, tick)
            target = round_tick(pl[t], tick)
            target_bps, stop_bps = (1 - target / limit) * 10_000, (stop / limit - 1) * 10_000
        if not (target_bps >= 8 and 2 <= stop_bps <= 100 and target_bps / stop_bps >= 1.2):
            continue
        decision = day + (j + 1) * 1_000_000
        key = f"{date}|{t}|{j}|{direction}"
        excursion = max(abs(raid - external), tick)
        events.append(Event(
            hashlib.sha1(key.encode()).hexdigest()[:20], date, direction, t, j,
            decision, decision + ACK_US, float(ph[t]), float(pl[t]), float(raid),
            float(gap_low), float(gap_high), float(limit), float(stop), float(target),
            float(tick), float(abs(raid / external - 1) * 10_000),
            float(abs(close[t] - raid) / excursion), float(abs(close[j] / open_[j] - 1) * 10_000),
            float((gap_high - gap_low) / limit * 10_000), float(target_bps), float(stop_bps),
            float(target_bps / stop_bps), float(_flow3(bars, j, direction)),
        ))
        next_allowed = t + 30
    return events
