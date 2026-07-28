#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import math
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.isotonic import IsotonicRegression

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
CLOCKS = ("UTC_ASIA", "NY_TDO", "LONDON_0200_NY")
MAKER = 0.00020
TAKER = 0.00055
BASE_SLIP_BPS = 1.5
MAINTENANCE = 0.005
LIQ_BUFFER = 0.0025
THROUGH_PRICE = 0.00010
STEPS = {"BTCUSDT": 0.001, "ETHUSDT": 0.01, "SOLUSDT": 0.1, "XRPUSDT": 1.0}
START = pd.Timestamp("2024-01-01T00:00:00Z")
END = pd.Timestamp("2024-07-01T00:00:00Z")


def floor_step(value: float, step: float) -> float:
    return max(0.0, math.floor((value + 1e-12) / step) * step)


def read_member(path: Path, suffix: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(suffix)]
        if len(names) != 1:
            raise RuntimeError(f"{path}: expected one {suffix}, found {names}")
        return pq.read_table(io.BytesIO(archive.read(names[0]))).to_pandas()


def numeric(frame: pd.DataFrame, names: Iterable[str]) -> pd.DataFrame:
    result = frame.copy()
    for name in names:
        if name in result:
            result[name] = pd.to_numeric(result[name], errors="coerce")
    return result


def load_symbol(paths: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    t1s: list[pd.DataFrame] = []
    t5s: list[pd.DataFrame] = []
    marks: list[pd.DataFrame] = []
    ois: list[pd.DataFrame] = []
    ratios: list[pd.DataFrame] = []
    premiums: list[pd.DataFrame] = []
    fundings: list[pd.DataFrame] = []
    for path in paths:
        t1s.append(read_member(path, "trade_bars/1m.parquet"))
        t5s.append(read_member(path, "trade_bars/5m.parquet"))
        marks.append(read_member(path, "streams/mark_price_1m.parquet"))
        ois.append(read_member(path, "streams/open_interest_5m.parquet"))
        ratios.append(read_member(path, "streams/account_ratio_5m.parquet"))
        premiums.append(read_member(path, "streams/premium_index_1m.parquet"))
        fundings.append(read_member(path, "streams/funding_events.parquet"))

    t1 = numeric(pd.concat(t1s, ignore_index=True), ("start_time_ms", "open", "high", "low", "close", "volume"))
    t1 = t1.sort_values("start_time_ms", kind="stable").drop_duplicates("start_time_ms", keep="last")
    mark = numeric(pd.concat(marks, ignore_index=True), ("start_time_ms", "open", "high", "low", "close"))
    mark = mark.sort_values("start_time_ms", kind="stable").drop_duplicates("start_time_ms", keep="last")
    mark = mark.rename(columns={"open": "mark_open", "high": "mark_high", "low": "mark_low", "close": "mark_close"})
    t1 = t1.merge(mark[["start_time_ms", "mark_open", "mark_high", "mark_low", "mark_close"]], on="start_time_ms", how="left")
    t1["ts"] = pd.to_datetime(t1.start_time_ms, unit="ms", utc=True)

    t5 = numeric(pd.concat(t5s, ignore_index=True), ("start_time_ms", "open", "high", "low", "close", "volume"))
    t5 = t5.sort_values("start_time_ms", kind="stable").drop_duplicates("start_time_ms", keep="last")
    oi = numeric(pd.concat(ois, ignore_index=True), ("start_time_ms", "open_interest"))
    oi = oi.sort_values("start_time_ms", kind="stable").drop_duplicates("start_time_ms", keep="last")
    ratio = numeric(pd.concat(ratios, ignore_index=True), ("start_time_ms", "buy_ratio", "sell_ratio", "long_short_ratio"))
    ratio = ratio.sort_values("start_time_ms", kind="stable").drop_duplicates("start_time_ms", keep="last")
    premium = numeric(pd.concat(premiums, ignore_index=True), ("start_time_ms", "close"))
    premium["bucket"] = (premium.start_time_ms // 300_000) * 300_000
    premium = premium.sort_values("start_time_ms", kind="stable").groupby("bucket", as_index=False).last()
    premium = premium.rename(columns={"bucket": "start_time_ms", "close": "premium_close"})
    t5 = t5.merge(oi[["start_time_ms", "open_interest"]], on="start_time_ms", how="left")
    keep_ratio = [name for name in ("start_time_ms", "buy_ratio", "sell_ratio", "long_short_ratio") if name in ratio]
    t5 = t5.merge(ratio[keep_ratio], on="start_time_ms", how="left")
    t5 = t5.merge(premium[["start_time_ms", "premium_close"]], on="start_time_ms", how="left")
    t5["ts"] = pd.to_datetime(t5.start_time_ms, unit="ms", utc=True)
    t5["decision_time"] = t5.ts + pd.Timedelta(minutes=5)

    funding = numeric(pd.concat(fundings, ignore_index=True), ("timestamp_ms", "funding_rate"))
    funding = funding.sort_values("timestamp_ms", kind="stable").drop_duplicates("timestamp_ms", keep="last")
    funding["ts"] = pd.to_datetime(funding.timestamp_ms, unit="ms", utc=True)
    return t1.reset_index(drop=True), t5.reset_index(drop=True), funding.reset_index(drop=True)


def add_features(frame: pd.DataFrame) -> pd.DataFrame:
    f = frame.copy().sort_values("ts", kind="stable").reset_index(drop=True)
    previous = f.close.shift(1)
    tr = pd.concat((f.high - f.low, (f.high - previous).abs(), (f.low - previous).abs()), axis=1).max(axis=1)
    f["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    f["body_atr"] = (f.close - f.open) / f.atr
    f["body_abs_atr"] = f.body_atr.abs()
    f["close_pos"] = (f.close - f.low) / (f.high - f.low).replace(0, np.nan)
    vm = f.volume.rolling(48, min_periods=24).mean()
    vs = f.volume.rolling(48, min_periods=24).std(ddof=0)
    f["volume_z"] = (f.volume - vm) / vs.replace(0, np.nan)
    f["ema48"] = f.close.ewm(span=48, adjust=False, min_periods=48).mean()
    f["ema192"] = f.close.ewm(span=192, adjust=False, min_periods=192).mean()
    f["trend_fast"] = (f.ema48 - f.ema48.shift(12)) / f.atr
    f["trend_slow"] = (f.ema192 - f.ema192.shift(48)) / f.atr
    for bars, name in ((3, "ret15"), (12, "ret60"), (48, "ret240"), (288, "ret1d")):
        f[name] = np.log(f.close / f.close.shift(bars))
    if "open_interest" in f:
        loi = np.log(f.open_interest.replace(0, np.nan))
        f["oi15"] = loi.diff(3)
        f["oi60"] = loi.diff(12)
        f["oi240"] = loi.diff(48)
    else:
        f[["oi15", "oi60", "oi240"]] = np.nan
    if "buy_ratio" in f and "sell_ratio" in f:
        raw = np.log((f.buy_ratio + 1e-9) / (f.sell_ratio + 1e-9))
    elif "long_short_ratio" in f:
        raw = np.log(f.long_short_ratio.replace(0, np.nan))
    else:
        raw = pd.Series(np.nan, index=f.index)
    f["ratio_z"] = (raw - raw.rolling(96, min_periods=32).mean()) / raw.rolling(96, min_periods=32).std(ddof=0)
    p = f.premium_close if "premium_close" in f else pd.Series(np.nan, index=f.index)
    f["premium_z"] = (p - p.rolling(96, min_periods=32).mean()) / p.rolling(96, min_periods=32).std(ddof=0)
    f["bull_fvg_low"] = f.high.shift(2).where(f.low > f.high.shift(2))
    f["bull_fvg_high"] = f.low.where(f.low > f.high.shift(2))
    f["bear_fvg_low"] = f.high.where(f.high < f.low.shift(2))
    f["bear_fvg_high"] = f.low.shift(2).where(f.high < f.low.shift(2))
    ny = f.ts.dt.tz_convert("America/New_York")
    f["ny_date"] = ny.dt.date
    day = f.groupby("ny_date").agg(day_high=("high", "max"), day_low=("low", "min"))
    previous_day = day.shift(1)
    f["pdh"] = f.ny_date.map(previous_day.day_high)
    f["pdl"] = f.ny_date.map(previous_day.day_low)
    return f


def group_codes(index: pd.DatetimeIndex, clock: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if clock == "UTC_ASIA":
        local = index.tz_convert("UTC").tz_localize(None)
        offset = 0
    else:
        local = index.tz_convert("America/New_York").tz_localize(None)
        offset = 0 if clock == "NY_TDO" else 120
    day = local.normalize()
    minute = (local.hour * 60 + local.minute).to_numpy(np.int64)
    before = minute < offset
    anchor_day = day - pd.to_timedelta(before.astype(np.int64), unit="D")
    elapsed = ((local - anchor_day).total_seconds() / 60).astype(np.int64) - offset
    daynum = (anchor_day.view("i8") // 86_400_000_000_000).astype(np.int64)
    return daynum * 4 + elapsed // 480, daynum * 16 + elapsed // 120, elapsed


def previous_block_levels(f: pd.DataFrame, code: np.ndarray, prefix: str) -> None:
    temp = f.assign(_code=code).groupby("_code").agg(_high=("high", "max"), _low=("low", "min")).shift(1)
    f[prefix + "_high"] = pd.Series(code, index=f.index).map(temp._high)
    f[prefix + "_low"] = pd.Series(code, index=f.index).map(temp._low)


def directional_fvg(f: pd.DataFrame, start: int, end: int, side: int) -> tuple[float, float] | None:
    if side > 0:
        rows = np.flatnonzero(np.isfinite(f.bull_fvg_low.to_numpy(float)[start:end]))
        if not len(rows):
            return None
        j = start + int(rows[-1])
        return float(f.bull_fvg_low.iloc[j]), float(f.bull_fvg_high.iloc[j])
    rows = np.flatnonzero(np.isfinite(f.bear_fvg_low.to_numpy(float)[start:end]))
    if not len(rows):
        return None
    j = start + int(rows[-1])
    return float(f.bear_fvg_low.iloc[j]), float(f.bear_fvg_high.iloc[j])


def generate_candidates(symbol: str, features: pd.DataFrame, clock: str) -> pd.DataFrame:
    f = features.copy().reset_index(drop=True)
    b8, b2, elapsed = group_codes(pd.DatetimeIndex(f.ts), clock)
    f["b8"] = b8
    f["b2"] = b2
    f["clock_minute"] = elapsed % 1440
    previous_block_levels(f, b8, "prev8")
    previous_block_levels(f, b2, "prev2")
    starts = np.r_[0, np.flatnonzero(b8[1:] != b8[:-1]) + 1]
    ends = np.r_[starts[1:], len(f)]
    op = f.open.to_numpy(float)
    hi = f.high.to_numpy(float)
    lo = f.low.to_numpy(float)
    cl = f.close.to_numpy(float)
    atr = f.atr.to_numpy(float)
    body = f.body_atr.to_numpy(float)
    cp = f.close_pos.to_numpy(float)
    vz = f.volume_z.to_numpy(float)
    rows: list[dict[str, object]] = []
    feature_names = ("body_atr", "body_abs_atr", "close_pos", "volume_z", "trend_fast", "trend_slow", "ret15", "ret60", "ret240", "ret1d", "oi15", "oi60", "oi240", "ratio_z", "premium_z")

    for bs, be in zip(starts, ends):
        if be - bs < 36:
            continue
        opening_end = min(bs + 12, be)
        opening_high = float(np.nanmax(hi[bs:opening_end]))
        opening_low = float(np.nanmin(lo[bs:opening_end]))
        lock = None
        for side in (1, -1):
            for sweep in range(opening_end, min(be - 8, bs + 60)):
                if not np.isfinite(atr[sweep]) or atr[sweep] <= 0:
                    continue
                buffer = max(0.03 * atr[sweep], cl[sweep] * 0.00003)
                swept = (lo[sweep] < opening_low - buffer and cl[sweep] > opening_low) if side > 0 else (hi[sweep] > opening_high + buffer and cl[sweep] < opening_high)
                if not swept:
                    continue
                source_positions = [k for k in range(max(bs, sweep - 12), sweep + 1) if (cl[k] < op[k] if side > 0 else cl[k] > op[k])]
                if not source_positions:
                    continue
                cisd = float(op[source_positions[-1]])
                confirm = -1
                for j in range(sweep, min(be, sweep + 7)):
                    crossed = cl[j] > cisd if side > 0 else cl[j] < cisd
                    direction = body[j] >= 0.22 and cp[j] >= 0.58 if side > 0 else body[j] <= -0.22 and cp[j] <= 0.42
                    imbalance = directional_fvg(f, sweep, j + 1, side)
                    displaced = abs(body[j]) >= 0.42 and (imbalance is not None or vz[j] >= 1.25)
                    if crossed and direction and displaced:
                        confirm = j
                        break
                if confirm < 0:
                    continue
                macro_zone = directional_fvg(f, sweep, confirm + 1, side)
                if macro_zone is None:
                    continue
                extreme = float(np.nanmin(lo[sweep:confirm + 1])) if side > 0 else float(np.nanmax(hi[sweep:confirm + 1]))
                hard_stop = extreme - max(0.03 * atr[confirm], cl[confirm] * 0.00003) if side > 0 else extreme + max(0.03 * atr[confirm], cl[confirm] * 0.00003)
                possible = [float(f.prev8_high.iloc[confirm]), float(f.pdh.iloc[confirm]), opening_high] if side > 0 else [float(f.prev8_low.iloc[confirm]), float(f.pdl.iloc[confirm]), opening_low]
                possible = [value for value in possible if np.isfinite(value) and side * (value - cl[confirm]) > 0]
                if not possible:
                    continue
                dol = min(possible) if side > 0 else max(possible)
                candidate_lock = {"side": side, "sweep": sweep, "confirm": confirm, "cisd": cisd, "zone_low": macro_zone[0], "zone_high": macro_zone[1], "hard_stop": hard_stop, "dol": dol, "opening_high": opening_high, "opening_low": opening_low}
                if lock is None or confirm < int(lock["confirm"]):
                    lock = candidate_lock
                break
        if lock is None:
            continue
        side = int(lock["side"])
        ci = int(lock["confirm"])
        hard_stop = float(lock["hard_stop"])
        dol = float(lock["dol"])
        sub_starts = np.r_[ci + 1, ci + 2 + np.flatnonzero(b2[ci + 2:be] != b2[ci + 1:be - 1])]
        for sequence, sub_start in enumerate(sub_starts, 1):
            if sub_start >= be:
                continue
            code = b2[sub_start]
            rel = np.flatnonzero(b2[sub_start + 1:be] != code)
            sub_end = sub_start + 1 + int(rel[0]) if len(rel) else be
            if sub_end - sub_start < 3:
                continue
            if side > 0 and np.nanmin(lo[ci + 1:sub_end]) <= hard_stop:
                break
            if side < 0 and np.nanmax(hi[ci + 1:sub_end]) >= hard_stop:
                break
            if side > 0 and np.nanmax(hi[ci + 1:sub_end]) >= dol:
                break
            if side < 0 and np.nanmin(lo[ci + 1:sub_end]) <= dol:
                break

            peak = float(cl[ci])
            trough = float(cl[ci])
            pullback = -1
            pullback_extreme = np.nan
            micro_cisd = np.nan
            confirm = -1
            source_index = -1
            for j in range(max(ci + 1, sub_start), sub_end):
                if not np.isfinite(atr[j]) or atr[j] <= 0:
                    continue
                if side > 0:
                    peak = max(peak, hi[j])
                    trough = min(trough, lo[j])
                    depth = (peak - lo[j]) / atr[j]
                    in_zone = lo[j] <= float(lock["zone_high"]) and hi[j] >= float(lock["zone_low"])
                    if pullback < 0 and depth >= 0.25 and in_zone:
                        pullback = j
                        pullback_extreme = float(lo[j])
                    if pullback >= 0:
                        pullback_extreme = min(float(pullback_extreme), float(lo[j]))
                        if cl[j] < op[j]:
                            source_index = j
                            micro_cisd = float(op[j])
                        recent_fvg = directional_fvg(f, max(pullback, j - 2), j + 1, side)
                        if source_index >= pullback and cl[j] > micro_cisd and body[j] >= 0.15 and cp[j] >= 0.55 and hi[j] > hi[j - 1] and (recent_fvg is not None or body[j] >= 0.35):
                            confirm = j
                            break
                else:
                    trough = min(trough, lo[j])
                    peak = max(peak, hi[j])
                    depth = (hi[j] - trough) / atr[j]
                    in_zone = lo[j] <= float(lock["zone_high"]) and hi[j] >= float(lock["zone_low"])
                    if pullback < 0 and depth >= 0.25 and in_zone:
                        pullback = j
                        pullback_extreme = float(hi[j])
                    if pullback >= 0:
                        pullback_extreme = max(float(pullback_extreme), float(hi[j]))
                        if cl[j] > op[j]:
                            source_index = j
                            micro_cisd = float(op[j])
                        recent_fvg = directional_fvg(f, max(pullback, j - 2), j + 1, side)
                        if source_index >= pullback and cl[j] < micro_cisd and body[j] <= -0.15 and cp[j] <= 0.45 and lo[j] < lo[j - 1] and (recent_fvg is not None or body[j] <= -0.35):
                            confirm = j
                            break
            if confirm < 0 or not np.isfinite(micro_cisd) or not np.isfinite(pullback_extreme):
                continue
            soft_stop = float(pullback_extreme) - max(0.03 * atr[confirm], cl[confirm] * 0.00003) if side > 0 else float(pullback_extreme) + max(0.03 * atr[confirm], cl[confirm] * 0.00003)
            if side > 0:
                hard_stop = min(hard_stop, soft_stop)
            else:
                hard_stop = max(hard_stop, soft_stop)
            hard_risk = side * (micro_cisd - hard_stop)
            if hard_risk <= 0 or hard_risk > 4.0 * atr[confirm]:
                continue
            known_levels = []
            prior_high = float(f.prev2_high.iloc[confirm])
            prior_low = float(f.prev2_low.iloc[confirm])
            if side > 0:
                for value, source in ((peak, "expansion_extreme"), (prior_high, "previous_2h"), (dol, "external_dol")):
                    if np.isfinite(value) and micro_cisd < value <= dol:
                        known_levels.append((value, source))
                known_levels.sort(key=lambda item: item[0])
            else:
                for value, source in ((trough, "expansion_extreme"), (prior_low, "previous_2h"), (dol, "external_dol")):
                    if np.isfinite(value) and dol <= value < micro_cisd:
                        known_levels.append((value, source))
                known_levels.sort(key=lambda item: item[0], reverse=True)
            if not known_levels:
                continue
            target, target_source = known_levels[0]
            target_r = side * (target - micro_cisd) / hard_risk
            stop_fill = hard_stop * (1 - side * BASE_SLIP_BPS / 10_000)
            per_unit = side * (micro_cisd - stop_fill) + micro_cisd * MAKER + stop_fill * TAKER
            cost_fraction = (per_unit - hard_risk) / max(hard_risk, 1e-12)
            if target_r < 0.50 or cost_fraction > 0.40:
                continue
            record = {
                "symbol": symbol,
                "clock": clock,
                "decision_time": pd.Timestamp(f.decision_time.iloc[confirm]),
                "bar_start": pd.Timestamp(f.ts.iloc[confirm]),
                "block2_end": pd.Timestamp(f.ts.iloc[sub_end - 1]) + pd.Timedelta(minutes=5),
                "side": side,
                "micro_cisd_level": micro_cisd,
                "soft_stop": soft_stop,
                "hard_stop": hard_stop,
                "target": float(target),
                "target_source": target_source,
                "dol": dol,
                "target_r": target_r,
                "cost_fraction": cost_fraction,
                "sequence": sequence,
                "pullback_depth_atr": side * (peak - pullback_extreme) / atr[confirm] if side > 0 else side * (pullback_extreme - trough) / atr[confirm],
                "macro_depth_atr": side * (float(lock["opening_low"]) - hard_stop) / atr[confirm] if side > 0 else side * (hard_stop - float(lock["opening_high"])) / atr[confirm],
                "distance_dol_atr": side * (dol - micro_cisd) / atr[confirm],
            }
            for name in feature_names:
                record[name] = float(f[name].iloc[confirm]) if name in f and np.isfinite(f[name].iloc[confirm]) else np.nan
            rows.append(record)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates(["decision_time", "symbol", "clock", "side", "micro_cisd_level", "soft_stop"]).sort_values("decision_time", kind="stable").reset_index(drop=True)


@dataclass
class Tape:
    time: pd.DatetimeIndex
    ns: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    mark_open: np.ndarray
    mark_high: np.ndarray
    mark_low: np.ndarray
    mark_close: np.ndarray
    median_volume: np.ndarray
    funding: dict[int, float]
    five_time: pd.DatetimeIndex
    five_complete_ns: np.ndarray
    five_open: np.ndarray
    five_close: np.ndarray
    five_high: np.ndarray
    five_low: np.ndarray
    five_atr: np.ndarray


def build_tape(t1: pd.DataFrame, f5: pd.DataFrame, funding: pd.DataFrame) -> Tape:
    t = t1.sort_values("ts", kind="stable").reset_index(drop=True)
    time = pd.DatetimeIndex(t.ts)
    median = t.volume.rolling(60, min_periods=20).median().shift(1).to_numpy(float)
    funds = {pd.Timestamp(row.ts).value: float(row.funding_rate) for row in funding.itertuples(index=False) if np.isfinite(float(row.funding_rate))}
    f = f5.sort_values("ts", kind="stable").reset_index(drop=True)
    return Tape(time, time.as_unit("ns").asi8, t.open.to_numpy(float), t.high.to_numpy(float), t.low.to_numpy(float), t.close.to_numpy(float), t.volume.to_numpy(float), t.mark_open.to_numpy(float), t.mark_high.to_numpy(float), t.mark_low.to_numpy(float), t.mark_close.to_numpy(float), median, funds, pd.DatetimeIndex(f.ts), (pd.DatetimeIndex(f.ts).as_unit("ns").asi8 + 300_000_000_000), f.open.to_numpy(float), f.close.to_numpy(float), f.high.to_numpy(float), f.low.to_numpy(float), f.atr.to_numpy(float))


def market_price(base: float, order_side: int, quantity: float, volume: float, impact_bps: float = 10.0) -> tuple[float, float]:
    participation = quantity / max(volume, quantity, 1e-12)
    bps = BASE_SLIP_BPS + impact_bps * math.sqrt(max(participation, 0.0))
    return base * (1 + order_side * bps / 10_000), participation


def classify_five(tape: Tape, index: int, side: int, level: float) -> str:
    if index < 0 or index >= len(tape.five_close) or not np.isfinite(tape.five_atr[index]):
        return "NEUTRAL"
    atr = max(float(tape.five_atr[index]), 1e-12)
    body = side * (float(tape.five_close[index]) - float(tape.five_open[index])) / atr
    position = (float(tape.five_close[index]) - float(tape.five_low[index])) / max(float(tape.five_high[index]) - float(tape.five_low[index]), 1e-12)
    if side < 0:
        position = 1 - position
    distance = side * (float(tape.five_close[index]) - level) / atr
    if distance >= 0.03 and body >= 0.15 and position >= 0.55:
        return "ACCEPT"
    if distance <= -0.03 and body <= -0.15 and position <= 0.45:
        return "REJECT"
    return "NEUTRAL"


def simulate(candidate: pd.Series, tape: Tape, nav: float, risk_fraction: float = 0.01, leverage: float = 5.0) -> dict[str, object]:
    decision = pd.Timestamp(candidate.decision_time)
    activation = decision + pd.Timedelta(milliseconds=500)
    start = int(np.searchsorted(tape.ns, activation.value, side="left"))
    if start >= len(tape.time):
        return {"status": "NO_TAPE", "event_end": decision, "pnl": 0.0, "filled": 0.0, "planned_risk": 0.0}
    side = int(candidate.side)
    entry = float(candidate.micro_cisd_level)
    soft_stop = float(candidate.soft_stop)
    hard_stop = float(candidate.hard_stop)
    target = float(candidate.target)
    dol = float(candidate.dol)
    step = STEPS[str(candidate.symbol)]
    stop_fill = hard_stop * (1 - side * BASE_SLIP_BPS / 10_000)
    per_unit = side * (entry - stop_fill) + entry * MAKER + stop_fill * TAKER
    safe_unit = side * (entry - stop_fill) + entry * MAKER + stop_fill * (MAINTENANCE + LIQ_BUFFER)
    planned = floor_step(min(nav * risk_fraction / max(per_unit, 1e-12), nav * leverage / entry, nav / max(safe_unit, 1e-12)), step)
    if planned < step:
        return {"status": "SIZE_ZERO", "event_end": decision, "pnl": 0.0, "filled": 0.0, "planned_risk": 0.0}
    expiry = pd.Timestamp(candidate.block2_end)
    expiry_index = int(np.searchsorted(tape.ns, expiry.value, side="left"))
    prior = tape.median_volume[max(start - 1, 0)]
    if not np.isfinite(prior):
        prior = float(np.nanmedian(tape.volume[max(0, start - 60):start]))
    entry_queue = max(0.0, 0.005 * max(prior, 0.0))
    exit_queue = entry_queue
    cash = float(nav)
    filled = 0.0
    open_quantity = 0.0
    entry_fees = 0.0
    partial_quantity = 0.0
    accepted = False
    target_touched = False
    assessment_bar = -1
    assessment_activation = None
    dynamic_stop = hard_stop
    event_end = decision
    status = "NO_FILL"
    last = len(tape.time) - 1

    for i in range(start, last + 1):
        timestamp = tape.time[i]
        event_end = timestamp
        if open_quantity > 0:
            rate = tape.funding.get(timestamp.value)
            if rate is not None:
                cash += -side * open_quantity * tape.mark_open[i] * rate

        completed = int(np.searchsorted(tape.five_complete_ns, timestamp.value - 500_000_000, side="right") - 1)
        soft_invalid = False
        if completed >= 0 and open_quantity > 0 and not accepted:
            soft_invalid = tape.five_close[completed] < soft_stop if side > 0 else tape.five_close[completed] > soft_stop
        hard_hit = tape.mark_low[i] <= dynamic_stop if side > 0 else tape.mark_high[i] >= dynamic_stop

        if pending := (filled < planned and timestamp < expiry and open_quantity >= 0):
            threshold = entry * (1 - side * THROUGH_PRICE)
            crossed = tape.low[i] <= threshold if side > 0 else tape.high[i] >= threshold
            if crossed and not hard_hit:
                eligible = 0.02 * 0.50 * max(tape.volume[i], 0.0)
                consumed = max(0.0, eligible - entry_queue)
                entry_queue = max(0.0, entry_queue - eligible)
                quantity = floor_step(min(planned - filled, consumed), step)
                if quantity >= step:
                    cash -= quantity * entry * MAKER
                    entry_fees += quantity * entry * MAKER
                    filled += quantity
                    open_quantity += quantity
        if timestamp >= expiry:
            planned = filled

        if open_quantity > 0 and (hard_hit or soft_invalid):
            cap = max(step, 0.10 * tape.volume[i])
            quantity = floor_step(min(open_quantity, cap), step)
            if quantity >= step:
                base = min(dynamic_stop, tape.open[i]) if side > 0 and hard_hit else max(dynamic_stop, tape.open[i]) if side < 0 and hard_hit else float(tape.open[i])
                price, _ = market_price(base, -side, quantity, tape.volume[i])
                cash += side * quantity * (price - entry) - quantity * price * TAKER
                open_quantity -= quantity
            if open_quantity < step:
                open_quantity = 0.0
                status = "HARD_STOP" if hard_hit else "CLOSE_INVALIDATION"
                break

        target_hit = tape.high[i] >= target if side > 0 else tape.low[i] <= target
        if open_quantity > 0 and target_hit and not target_touched:
            target_touched = True
            assessment_bar = int(np.searchsorted(tape.five_time.as_unit("ns").asi8, timestamp.floor("5min").value, side="left"))
            if 0 <= assessment_bar < len(tape.five_complete_ns):
                assessment_activation = pd.Timestamp(int(tape.five_complete_ns[assessment_bar]) + 500_000_000, unit="ns", tz="UTC")

        if open_quantity > 0 and target_hit:
            goal = floor_step(filled * 0.67, step)
            remaining = max(0.0, goal - partial_quantity)
            eligible = 0.02 * 0.50 * max(tape.volume[i], 0.0)
            consumed = max(0.0, eligible - exit_queue)
            exit_queue = max(0.0, exit_queue - eligible)
            quantity = floor_step(min(open_quantity, remaining, consumed), step)
            if quantity >= step:
                cash += side * quantity * (target - entry) - quantity * target * MAKER
                open_quantity -= quantity
                partial_quantity += quantity

        if open_quantity > 0 and assessment_activation is not None and timestamp >= assessment_activation:
            state = classify_five(tape, assessment_bar, side, target)
            if state == "ACCEPT":
                accepted = True
                dynamic_stop = max(dynamic_stop, target - side * 0.20 * tape.five_atr[assessment_bar]) if side > 0 else min(dynamic_stop, target - side * 0.20 * tape.five_atr[assessment_bar])
                assessment_activation = None
            elif state == "REJECT":
                cap = max(step, 0.10 * tape.volume[i])
                quantity = floor_step(min(open_quantity, cap), step)
                if quantity >= step:
                    price, _ = market_price(float(tape.open[i]), -side, quantity, tape.volume[i])
                    cash += side * quantity * (price - entry) - quantity * price * TAKER
                    open_quantity -= quantity
                if open_quantity < step:
                    open_quantity = 0.0
                    status = "TARGET_REJECTION"
                    break
            else:
                assessment_bar += 1
                if assessment_bar < len(tape.five_complete_ns):
                    assessment_activation = pd.Timestamp(int(tape.five_complete_ns[assessment_bar]) + 500_000_000, unit="ns", tz="UTC")
                else:
                    assessment_activation = None

        dol_hit = tape.high[i] >= dol if side > 0 else tape.low[i] <= dol
        if open_quantity > 0 and accepted and dol_hit:
            eligible = 0.02 * 0.50 * max(tape.volume[i], 0.0)
            quantity = floor_step(min(open_quantity, eligible), step)
            if quantity >= step:
                cash += side * quantity * (dol - entry) - quantity * dol * MAKER
                open_quantity -= quantity
            if open_quantity < step:
                open_quantity = 0.0
                status = "DOL"
                break

        if open_quantity <= 0 and filled > 0 and partial_quantity >= filled - step:
            status = "TARGET"
            break
        if open_quantity <= 0 and timestamp >= expiry and filled <= 0:
            status = "NO_FILL"
            break
        if timestamp >= END and open_quantity > 0:
            price, _ = market_price(tape.mark_close[i], -side, open_quantity, tape.volume[i])
            cash += side * open_quantity * (price - entry) - open_quantity * price * TAKER
            open_quantity = 0.0
            status = "END_MARK"
            break

    planned_risk = planned * per_unit
    return {"status": status, "event_end": event_end, "pnl": cash - nav, "filled": filled, "planned_risk": planned_risk, "return": (cash / nav - 1) if nav > 0 else -1.0}


def model_frame(candidates: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    d = candidates.copy().reset_index(drop=True)
    d = d.join(labels[["event_end", "reward", "filled_label"]])
    minute = pd.to_numeric(d.clock_minute, errors="coerce").fillna(0).to_numpy(float) % 1440
    d["clock_sin"] = np.sin(2 * np.pi * minute / 1440)
    d["clock_cos"] = np.cos(2 * np.pi * minute / 1440)
    features = ["target_r", "cost_fraction", "sequence", "pullback_depth_atr", "macro_depth_atr", "distance_dol_atr", "body_atr", "body_abs_atr", "close_pos", "volume_z", "trend_fast", "trend_slow", "ret15", "ret60", "ret240", "ret1d", "oi15", "oi60", "oi240", "ratio_z", "premium_z", "clock_sin", "clock_cos"]
    for symbol in SYMBOLS:
        name = "symbol_" + symbol
        d[name] = d.symbol.eq(symbol).astype(float)
        features.append(name)
    for clock in CLOCKS:
        name = "clock_" + clock
        d[name] = d.clock.eq(clock).astype(float)
        features.append(name)
    d["side_long"] = d.side.gt(0).astype(float)
    features.append("side_long")
    return d, features


def fit_model(training: pd.DataFrame, features: list[str]):
    ordered = training.sort_values("event_end", kind="stable").copy()
    if len(ordered) < 500:
        return None
    split = int(len(ordered) * 0.80)
    calibration = ordered.iloc[split:].copy()
    calibration_start = pd.Timestamp(calibration.decision_time.min())
    base = ordered.iloc[:split]
    base = base[pd.to_datetime(base.event_end, utc=True) < calibration_start]
    if len(base) < 300 or base.filled_label.sum() < 100:
        return None
    xb = base[features].replace([np.inf, -np.inf], np.nan)
    fill = LGBMClassifier(n_estimators=180, learning_rate=0.035, num_leaves=15, min_child_samples=45, reg_lambda=2.0, reg_alpha=0.2, verbosity=-1, random_state=20260729)
    fill.fit(xb, base.filled_label.astype(int))
    resolved = base[base.filled_label.eq(1)]
    xr = resolved[features].replace([np.inf, -np.inf], np.nan)
    reg = LGBMRegressor(n_estimators=240, learning_rate=0.03, num_leaves=15, min_child_samples=35, reg_lambda=3.0, reg_alpha=0.2, verbosity=-1, random_state=20260729)
    reg.fit(xr, resolved.reward.astype(float))
    xc = calibration[features].replace([np.inf, -np.inf], np.nan)
    raw = fill.predict_proba(xc)[:, 1] * reg.predict(xc)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=-2, y_max=4)
    iso.fit(raw, calibration.reward.to_numpy(float))
    lo = xb.quantile(0.005)
    hi = xb.quantile(0.995)
    return fill, reg, iso, lo, hi


def score(model, rows: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    fill, reg, iso, lo, hi = model
    x = rows[features].replace([np.inf, -np.inf], np.nan)
    pf = fill.predict_proba(x)[:, 1]
    raw = pf * reg.predict(x)
    expected = iso.predict(raw)
    support = ((x.ge(lo) & x.le(hi)) | x.isna()).mean(axis=1).to_numpy(float)
    result = rows[["candidate_id", "decision_time"]].copy()
    result["expected"] = expected
    result["support"] = support
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    candidates: list[pd.DataFrame] = []
    tapes: dict[str, Tape] = {}
    for symbol in SYMBOLS:
        paths = sorted(args.data_root.glob(f"{symbol}_*.zip"))
        if not paths:
            raise RuntimeError(f"no canonical archives for {symbol}")
        t1, t5, funding = load_symbol(paths)
        f5 = add_features(t5)
        tapes[symbol] = build_tape(t1, f5, funding)
        for clock in CLOCKS:
            generated = generate_candidates(symbol, f5, clock)
            if not generated.empty:
                candidates.append(generated)
    all_candidates = pd.concat(candidates, ignore_index=True).sort_values("decision_time", kind="stable").reset_index(drop=True)
    all_candidates["candidate_id"] = np.arange(len(all_candidates), dtype=np.int64)

    label_rows = []
    for row in all_candidates.itertuples(index=False):
        outcome = simulate(pd.Series(row._asdict()), tapes[str(row.symbol)], 10_000.0)
        planned = float(outcome["planned_risk"])
        label_rows.append({"event_end": outcome["event_end"], "reward": float(outcome["pnl"]) / planned if planned > 0 else 0.0, "filled_label": int(float(outcome["filled"]) > 0), "status": outcome["status"]})
    labels = pd.DataFrame(label_rows)
    labels["event_end"] = pd.to_datetime(labels.event_end, utc=True)
    model_data, features = model_frame(all_candidates, labels)
    training = model_data[pd.to_datetime(model_data.event_end, utc=True) < START]
    model = fit_model(training, features)
    if model is None:
        raise RuntimeError("insufficient causal training rows")
    evaluation = model_data[(model_data.decision_time >= START) & (model_data.decision_time < END)].copy()
    predictions = score(model, evaluation, features)
    evaluation = evaluation.merge(predictions[["candidate_id", "expected", "support"]], on="candidate_id", how="left")
    evaluation = evaluation[np.isfinite(evaluation.expected) & evaluation.expected.gt(0) & evaluation.support.ge(0.85)].copy()

    nav = 10_000.0
    slot = START
    trades = []
    attempts = []
    for decision_time, group in evaluation.groupby("decision_time", sort=True):
        decision_time = pd.Timestamp(decision_time)
        if decision_time < slot:
            continue
        selected = group.sort_values(["expected", "target_r", "distance_dol_atr"], ascending=[False, False, False], kind="stable").iloc[0]
        outcome = simulate(selected, tapes[str(selected.symbol)], nav)
        slot = max(decision_time, pd.Timestamp(outcome["event_end"]))
        record = {"decision_time": decision_time, "symbol": selected.symbol, "clock": selected.clock, "side": int(selected.side), "expected": float(selected.expected), "support": float(selected.support), **outcome, "before_nav": nav}
        attempts.append(record)
        if float(outcome["filled"]) > 0:
            nav += float(outcome["pnl"])
            record["end_nav"] = nav
            trades.append(record)
        if nav <= 0:
            break

    trade_frame = pd.DataFrame(trades)
    days = int((END - START) / pd.Timedelta(days=1))
    growth = (nav / 10_000.0) ** (1 / days) - 1 if nav > 0 else -1.0
    wins = trade_frame.loc[trade_frame.pnl.gt(0), "pnl"].to_numpy(float) if len(trade_frame) else np.array([])
    summary = {
        "schema_version": 1,
        "stage": "2024H1_CAUSAL_ITERABLE_SCREEN",
        "candidate_count": len(all_candidates),
        "training_candidate_count": len(training),
        "evaluation_candidate_count": len(evaluation),
        "attempts": len(attempts),
        "trades": len(trade_frame),
        "start_nav": 10_000.0,
        "end_nav": nav,
        "account_multiple": nav / 10_000.0,
        "geometric_daily_growth": growth,
        "top_five_positive_pnl_share": float(np.sort(wins)[-5:].sum() / wins.sum()) if wins.sum() > 0 else None,
        "status_counts": pd.DataFrame(attempts).status.value_counts().to_dict() if attempts else {},
        "causal_contract": {
            "macro": "institutional 8h opening range sweep/reclaim plus local CISD, displacement and FVG",
            "micro": "2h pullback into macro FVG plus locally sourced micro CISD",
            "entry": "500ms delayed queue-aware passive retest",
            "stop": "macro sweep emergency mark stop plus completed-5m local structural invalidation",
            "exit": "67% low-resistance liquidity, 33% runner only after completed-5m acceptance",
            "time_exit": False,
        },
    }
    all_candidates.to_parquet(args.output / "candidates.parquet", index=False)
    labels.to_parquet(args.output / "labels.parquet", index=False)
    trade_frame.to_parquet(args.output / "trades.parquet", index=False)
    pd.DataFrame(attempts).to_parquet(args.output / "attempts.parquet", index=False)
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
