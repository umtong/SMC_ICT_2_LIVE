#!/usr/bin/env python3
"""Build one symbol-month of causal prior-day liquidity-edge microflow events.

The event begins at the first actual public trade through the frozen prior-day
high/low while the side was armed by previously completed state.  The ten
second sensor is never backdated from a completed candle.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests

BASE = "https://public.bybit.com/trading/{symbol}/{symbol}{day}.csv.gz"
UTC = timezone.utc


@dataclass(frozen=True)
class DayFile:
    day: str
    url: str
    sha256: str
    size_bytes: int
    rows: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_bytes(url: str, attempts: int = 6) -> bytes:
    last: Exception | None = None
    for k in range(attempts):
        try:
            r = requests.get(url, timeout=(30, 300), headers={"User-Agent": "SMC-ICT-research/1.0"})
            if r.status_code == 404:
                raise FileNotFoundError(url)
            r.raise_for_status()
            return r.content
        except Exception as exc:  # noqa: BLE001
            last = exc
            if k + 1 < attempts:
                time.sleep(min(45, 2 ** k))
    assert last is not None
    raise last


def parse_timestamp(series: pd.Series) -> pd.Series:
    num = pd.to_numeric(series, errors="coerce")
    finite = num[np.isfinite(num)]
    if len(finite):
        med = float(np.nanmedian(np.abs(finite.to_numpy(dtype=float))))
        if med >= 1e17:
            unit = "ns"
        elif med >= 1e14:
            unit = "us"
        elif med >= 1e11:
            unit = "ms"
        else:
            unit = "s"
        out = pd.to_datetime(num, unit=unit, utc=True, errors="coerce")
    else:
        out = pd.to_datetime(series, utc=True, errors="coerce")
    return out


def choose_column(columns: Iterable[str], choices: Iterable[str]) -> str:
    lookup = {str(c).strip().lower(): str(c) for c in columns}
    for c in choices:
        if c in lookup:
            return lookup[c]
    for low, original in lookup.items():
        for c in choices:
            if c in low:
                return original
    raise KeyError(f"missing one of {list(choices)} in {list(columns)}")


def decode_trades(raw: bytes) -> pd.DataFrame:
    try:
        payload = gzip.decompress(raw)
    except OSError:
        payload = raw
    df = pd.read_csv(io.BytesIO(payload), low_memory=False)
    ts_col = choose_column(df.columns, ["timestamp", "time", "trade_time", "exec_time"])
    px_col = choose_column(df.columns, ["price", "exec_price", "trade_price"])
    qty_col = choose_column(df.columns, ["size", "qty", "quantity", "exec_qty"])
    side_col = choose_column(df.columns, ["side", "taker_side"])
    out = pd.DataFrame(
        {
            "ts": parse_timestamp(df[ts_col]),
            "price": pd.to_numeric(df[px_col], errors="coerce"),
            "qty": pd.to_numeric(df[qty_col], errors="coerce"),
            "side_raw": df[side_col].astype(str),
        }
    )
    out = out.dropna(subset=["ts", "price", "qty"])
    out = out[(out["price"] > 0) & (out["qty"] > 0)].copy()
    side = out["side_raw"].str.strip().str.lower()
    out["aggr"] = np.where(side.str.startswith("b"), 1.0, np.where(side.str.startswith("s"), -1.0, np.nan))
    out = out[np.isfinite(out["aggr"])].copy()
    out["turnover"] = out["price"].astype(float) * out["qty"].astype(float)
    out = out.sort_values("ts", kind="mergesort").reset_index(drop=True)
    return out[["ts", "price", "qty", "aggr", "turnover"]]


def load_day(symbol: str, d: date, cache: dict[str, tuple[pd.DataFrame, DayFile]]) -> tuple[pd.DataFrame, DayFile]:
    key = d.isoformat()
    if key in cache:
        return cache[key]
    url = BASE.format(symbol=symbol, day=key)
    raw = get_bytes(url)
    frame = decode_trades(raw)
    meta = DayFile(key, url, sha256_bytes(raw), len(raw), len(frame))
    cache[key] = (frame, meta)
    return frame, meta


def completed_atr15(trades: pd.DataFrame) -> pd.Series:
    if trades.empty:
        return pd.Series(dtype=float)
    p = trades.set_index("ts")["price"].astype(float)
    ohlc = p.resample("15min", label="right", closed="left").ohlc().dropna()
    prev = ohlc["close"].shift(1)
    tr = pd.concat(
        [
            ohlc["high"] - ohlc["low"],
            (ohlc["high"] - prev).abs(),
            (ohlc["low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(20, min_periods=20).mean()


def atr_at(atr: pd.Series, ts: pd.Timestamp) -> float:
    if atr.empty:
        return math.nan
    idx = atr.index.searchsorted(ts, side="right") - 1
    if idx < 0:
        return math.nan
    return float(atr.iloc[idx])


def sensor_row(
    symbol: str,
    d: date,
    level_side: int,
    event_idx: int,
    stream: pd.DataFrame,
    level: float,
    midpoint: float,
    atr: float,
) -> dict[str, object] | None:
    t0 = stream.at[event_idx, "ts"]
    sensor_end = t0 + pd.Timedelta(seconds=10)
    activation = sensor_end + pd.Timedelta(milliseconds=500)
    ts_ns = stream["ts"].astype("int64").to_numpy()
    lo = event_idx
    hi = int(np.searchsorted(ts_ns, int(sensor_end.value), side="left"))
    entry_i = int(np.searchsorted(ts_ns, int(activation.value), side="right"))
    if hi <= lo or entry_i >= len(stream):
        return None
    s = stream.iloc[lo:hi].copy()
    if s.empty or not np.isfinite(atr) or atr <= 0:
        return None
    first_px = float(s.iloc[0]["price"])
    last_px = float(s.iloc[-1]["price"])
    entry_px = float(stream.iloc[entry_i]["price"])
    total_turn = float(s["turnover"].sum())
    if not np.isfinite(total_turn) or total_turn <= 0:
        return None
    aligned = level_side * s["aggr"].to_numpy(dtype=float)
    turn = s["turnover"].to_numpy(dtype=float)
    px = s["price"].to_numpy(dtype=float)
    sec = (s["ts"] - t0).dt.total_seconds().to_numpy(dtype=float)
    first_mask = sec < 5.0
    second_mask = ~first_mask
    flow_all = float(np.sum(aligned * turn) / total_turn)
    t1 = float(np.sum(turn[first_mask]))
    t2 = float(np.sum(turn[second_mask]))
    flow1 = float(np.sum(aligned[first_mask] * turn[first_mask]) / t1) if t1 > 0 else 0.0
    flow2 = float(np.sum(aligned[second_mask] * turn[second_mask]) / t2) if t2 > 0 else 0.0
    signed_from_level = level_side * (px - level)
    outside = signed_from_level >= 0
    outside_share = float(np.sum(turn[outside]) / total_turn)
    state = outside.astype(np.int8)
    crossings = int(np.sum(state[1:] != state[:-1])) if len(state) > 1 else 0
    favorable = float(max(0.0, np.max(level_side * (px - first_px))) / atr)
    adverse = float(max(0.0, np.max(-level_side * (px - first_px))) / atr)
    penetration = float(level_side * (last_px - level) / atr)
    impact = float(level_side * (last_px - first_px) / first_px * 1e4)
    impact_per_million = float(impact / max(total_turn / 1e6, 1e-12))
    max_turn = float(np.max(turn))
    top_share = max_turn / total_turn
    event_ns = int(t0.value)
    event_id = f"{symbol}|{event_ns}|{'HIGH' if level_side > 0 else 'LOW'}"
    return {
        "event_id": event_id,
        "symbol": symbol,
        "event_day": d.isoformat(),
        "level_side": int(level_side),
        "event_ts": t0.isoformat(),
        "sensor_end_ts": sensor_end.isoformat(),
        "decision_ts": sensor_end.isoformat(),
        "activation_ts": activation.isoformat(),
        "entry_ts": stream.iloc[entry_i]["ts"].isoformat(),
        "event_price": first_px,
        "entry_price": entry_px,
        "level": float(level),
        "prior_day_mid": float(midpoint),
        "atr15m20": float(atr),
        "sensor_high": float(np.max(px)),
        "sensor_low": float(np.min(px)),
        "sensor_last": last_px,
        "penetration_at_end_atr": penetration,
        "outside_turnover_share": outside_share,
        "aligned_flow_imbalance": flow_all,
        "first_half_flow": flow1,
        "second_half_flow": flow2,
        "flow_acceleration": flow2 - flow1,
        "impact_bps": impact,
        "impact_bps_per_million": impact_per_million,
        "favorable_progress_atr": favorable,
        "adverse_progress_atr": adverse,
        "price_hold_atr": float(level_side * (last_px - level) / atr),
        "crossing_count": crossings,
        "trade_count": int(len(s)),
        "total_turnover": total_turn,
        "median_trade_turnover": float(np.median(turn)),
        "largest_trade_share": float(top_share),
        "sensor_duration_observed_s": float((s.iloc[-1]["ts"] - t0).total_seconds()),
    }


def process_day(symbol: str, d: date, cache: dict[str, tuple[pd.DataFrame, DayFile]]) -> tuple[list[dict[str, object]], list[DayFile]]:
    prev, m_prev = load_day(symbol, d - timedelta(days=1), cache)
    cur, m_cur = load_day(symbol, d, cache)
    metas = [m_prev, m_cur]
    if prev.empty or cur.empty:
        return [], metas
    tail = pd.DataFrame(columns=cur.columns)
    if d.year == 2023 and d < date(2023, 12, 31):
        nxt, m_next = load_day(symbol, d + timedelta(days=1), cache)
        metas.append(m_next)
        if not nxt.empty:
            cutoff = pd.Timestamp(datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=UTC)) + pd.Timedelta(minutes=2)
            tail = nxt[nxt["ts"] < cutoff]
    stream = pd.concat([cur, tail], ignore_index=True).sort_values("ts", kind="mergesort").reset_index(drop=True)
    high = float(prev["price"].max())
    low = float(prev["price"].min())
    midpoint = (high + low) / 2.0
    both = pd.concat([prev, stream], ignore_index=True).sort_values("ts", kind="mergesort")
    atr = completed_atr15(both)
    day_start = pd.Timestamp(datetime.combine(d, datetime.min.time(), tzinfo=UTC))
    a0 = atr_at(atr, day_start)
    if not np.isfinite(a0) or a0 <= 0:
        return [], metas
    prev_close = float(prev.iloc[-1]["price"])
    armed = {1: prev_close <= high - 0.5 * a0, -1: prev_close >= low + 0.5 * a0}
    last_event_minute: dict[int, pd.Timestamp | None] = {1: None, -1: None}
    rows: list[dict[str, object]] = []
    cur_only_n = len(cur)
    cur_minutes = cur["ts"].dt.floor("min")
    grouped = cur.groupby(cur_minutes, sort=True)
    prior_minute_close = prev_close
    prior_minute: pd.Timestamp | None = None
    for minute, g in grouped:
        minute = pd.Timestamp(minute)
        a = atr_at(atr, minute)
        if not np.isfinite(a) or a <= 0:
            prior_minute_close = float(g.iloc[-1]["price"])
            prior_minute = minute
            continue
        if prior_minute is not None:
            if last_event_minute[1] is None or prior_minute > last_event_minute[1]:
                if prior_minute_close <= high - 0.5 * a:
                    armed[1] = True
            if last_event_minute[-1] is None or prior_minute > last_event_minute[-1]:
                if prior_minute_close >= low + 0.5 * a:
                    armed[-1] = True
        for idx, tr in g.iterrows():
            px = float(tr["price"])
            side = 0
            level = math.nan
            if armed[1] and px >= high:
                side, level = 1, high
            elif armed[-1] and px <= low:
                side, level = -1, low
            if side:
                row = sensor_row(symbol, d, side, int(idx), stream, level, midpoint, a)
                armed[side] = False
                last_event_minute[side] = minute
                if row is not None:
                    rows.append(row)
        prior_minute_close = float(g.iloc[-1]["price"])
        prior_minute = minute
    return rows, metas


def month_days(year: int, month: int) -> list[date]:
    first = date(year, month, 1)
    nxt = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return [first + timedelta(days=i) for i in range((nxt - first).days)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, choices=["BTCUSDT", "ETHUSDT"])
    ap.add_argument("--year", type=int, default=2023)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cache: dict[str, tuple[pd.DataFrame, DayFile]] = {}
    events: list[dict[str, object]] = []
    manifest: dict[str, DayFile] = {}
    failures: list[dict[str, str]] = []
    for d in month_days(args.year, args.month):
        try:
            rows, metas = process_day(args.symbol, d, cache)
            events.extend(rows)
            for m in metas:
                existing = manifest.get(m.url)
                if existing is not None and existing.sha256 != m.sha256:
                    raise RuntimeError(f"hash changed for {m.url}")
                manifest[m.url] = m
        except FileNotFoundError as exc:
            failures.append({"day": d.isoformat(), "error": f"404 {exc}"})
        except Exception as exc:  # noqa: BLE001
            failures.append({"day": d.isoformat(), "error": repr(exc)})
    frame = pd.DataFrame(events)
    if len(frame):
        frame = frame.sort_values(["event_ts", "symbol", "level_side"], kind="mergesort").drop_duplicates("event_id")
    stem = f"{args.symbol}_{args.year}_{args.month:02d}"
    feature_path = args.out / f"{stem}_features.csv.gz"
    frame.to_csv(feature_path, index=False, compression="gzip")
    source_rows = [m.__dict__ for m in sorted(manifest.values(), key=lambda x: x.url)]
    manifest_obj = {
        "schema": "DENSE-LIQUIDITY-EDGE-MICROFLOW-V3",
        "symbol": args.symbol,
        "year": args.year,
        "month": args.month,
        "event_count": int(len(frame)),
        "source_files": source_rows,
        "failures": failures,
        "feature_sha256": hashlib.sha256(feature_path.read_bytes()).hexdigest(),
    }
    (args.out / f"{stem}_manifest.json").write_text(json.dumps(manifest_obj, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"events": len(frame), "sources": len(source_rows), "failures": len(failures)}))
    if failures:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
