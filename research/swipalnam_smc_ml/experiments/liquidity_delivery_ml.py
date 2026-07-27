#!/usr/bin/env python3
"""Causal ML system for a transcript-grounded SMC/ICT liquidity-delivery model.

Core auction sequence:
  external liquidity raid -> displacement/MSS -> FVG/order-block revisit
  -> opposing liquidity delivery or structural invalidation.

The executable never sends orders.  It replays canonical Bybit data, applies a
fixed 500 ms activation delay, enforces one global pending/position slot, and
selects every model/configuration/risk rule on information available before the
corresponding evaluation time.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

LATENCY_MS = 500
MINUTE_MS = 60_000
DAY_MS = 86_400_000
EPS = 1e-12


@dataclass(frozen=True)
class SetupConfig:
    timeframe_min: int
    min_sweep_atr: float
    min_body_atr: float
    min_fvg_atr: float
    retrace: float
    require_pd: bool
    require_overlap: bool
    stop_buffer_atr: float = 0.10
    min_rr: float = 1.25

    @property
    def key(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class AccountConfig:
    risk_fraction: float
    leverage: float
    taker_fee_bps: float = 5.5
    slippage_bps: float = 1.0
    impact_bps: float = 4.0
    maintenance_margin_rate: float = 0.005

    @property
    def key(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class ResearchError(RuntimeError):
    pass


def utc_ms(value: str | pd.Timestamp) -> int:
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.value // 1_000_000)


def iso_ms(value: int | None) -> str | None:
    return None if value is None else pd.Timestamp(value, unit="ms", tz="UTC").isoformat()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if dataclasses.is_dataclass(value):
        return asdict(value)
    raise TypeError(type(value).__name__)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def first(columns: Sequence[str], candidates: Sequence[str]) -> str | None:
    available = set(columns)
    return next((name for name in candidates if name in available), None)


def epoch_ms(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    if finite.empty:
        parsed = pd.to_datetime(series, utc=True, errors="coerce")
        return (parsed.astype("int64") // 1_000_000).astype("Int64")
    median = float(np.nanmedian(np.abs(finite.to_numpy(float))))
    if median < 1e11:
        numeric *= 1_000
    elif median > 1e15:
        numeric /= 1_000_000
    elif median > 1e13:
        numeric /= 1_000
    return numeric.round().astype("Int64")


def normalize_bars(frame: pd.DataFrame, timeframe_min: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["start_time_ms", "available_at_ms", "open", "high", "low", "close", "volume", "turnover"])
    src = frame.copy()
    src.columns = [str(col).strip().lower() for col in src.columns]
    time_col = first(src.columns.tolist(), ["start_time_ms", "timestamp_ms", "open_time_ms", "time_ms", "timestamp", "open_time", "start_time", "datetime"])
    if time_col is None:
        raise ResearchError(f"no time column: {list(src.columns)}")
    aliases = {
        "open": ["open", "open_price", "o"],
        "high": ["high", "high_price", "h"],
        "low": ["low", "low_price", "l"],
        "close": ["close", "close_price", "c", "last_price"],
        "volume": ["volume", "qty", "base_volume", "v"],
        "turnover": ["turnover", "quote_volume", "notional", "quote_qty"],
    }
    chosen = {target: first(src.columns.tolist(), names) for target, names in aliases.items()}
    if any(chosen[name] is None for name in ("open", "high", "low", "close")):
        raise ResearchError(f"unrecognized OHLC schema: {list(src.columns)}")
    out = pd.DataFrame({"start_time_ms": epoch_ms(src[time_col])})
    for name in ("open", "high", "low", "close"):
        out[name] = pd.to_numeric(src[chosen[name]], errors="coerce")
    out["volume"] = pd.to_numeric(src[chosen["volume"]], errors="coerce") if chosen["volume"] else 0.0
    out["turnover"] = pd.to_numeric(src[chosen["turnover"]], errors="coerce") if chosen["turnover"] else out["volume"] * out["close"]
    available = first(src.columns.tolist(), ["available_at_ms", "availability_time_ms", "close_time_ms", "end_time_ms"])
    out["available_at_ms"] = epoch_ms(src[available]) if available else out["start_time_ms"] + timeframe_min * MINUTE_MS
    valid_col = first(src.columns.tolist(), ["source_available", "available", "observed", "is_valid"])
    if valid_col:
        out = out[src[valid_col].astype(bool).to_numpy()]
    out = out.dropna().sort_values("start_time_ms", kind="stable").drop_duplicates("start_time_ms", keep="last")
    out["start_time_ms"] = out["start_time_ms"].astype("int64")
    out["available_at_ms"] = out["available_at_ms"].astype("int64")
    valid = (out[["open", "high", "low", "close"]] > 0).all(axis=1) & (out["high"] >= out[["open", "close"]].max(axis=1)) & (out["low"] <= out[["open", "close"]].min(axis=1))
    return out[valid].reset_index(drop=True)


def normalize_stream(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["available_at_ms", name])
    src = frame.copy()
    src.columns = [str(col).strip().lower() for col in src.columns]
    time_col = first(src.columns.tolist(), ["start_time_ms", "timestamp_ms", "time_ms", "timestamp", "start_time"])
    if time_col is None:
        return pd.DataFrame(columns=["available_at_ms", name])
    preferred = {
        "open_interest": ["open_interest", "oi", "value"],
        "account_ratio": ["long_short_ratio", "buy_ratio", "ratio", "value"],
        "funding": ["funding_rate", "rate", "value"],
        "mark": ["close", "mark_price", "value"],
        "index": ["close", "index_price", "value"],
        "premium": ["close", "premium", "value"],
    }[name]
    value_col = first(src.columns.tolist(), preferred)
    if value_col is None:
        excluded = {time_col, "available_at_ms", "source_available", "symbol", "interval"}
        numeric = [col for col in src.columns if col not in excluded and pd.to_numeric(src[col], errors="coerce").notna().any()]
        if not numeric:
            return pd.DataFrame(columns=["available_at_ms", name])
        value_col = numeric[0]
    available = first(src.columns.tolist(), ["available_at_ms", "availability_time_ms", "end_time_ms"])
    out = pd.DataFrame({
        "available_at_ms": epoch_ms(src[available]) if available else epoch_ms(src[time_col]),
        name: pd.to_numeric(src[value_col], errors="coerce"),
    }).dropna().sort_values("available_at_ms", kind="stable")
    out["available_at_ms"] = out["available_at_ms"].astype("int64")
    return out.drop_duplicates("available_at_ms", keep="last").reset_index(drop=True)


def load_segment(root: Path, segment: str, symbol: str) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    from scripts.market_data.load_canonical_bybit import load_stream, load_trade_bar  # type: ignore
    bars = normalize_bars(load_trade_bar(root, segment, symbol, "1m"), 1)
    definitions = {
        "open_interest": ["open_interest_5m", "open_interest"],
        "account_ratio": ["account_ratio_5m", "long_short_ratio_5m", "account_ratio"],
        "funding": ["funding_events", "funding_rate"],
        "mark": ["mark_price_1m", "mark_1m"],
        "index": ["index_price_1m", "index_1m"],
        "premium": ["premium_index_1m", "premium_1m"],
    }
    streams: dict[str, pd.DataFrame] = {}
    for name, alternatives in definitions.items():
        streams[name] = pd.DataFrame(columns=["available_at_ms", name])
        for stream_name in alternatives:
            try:
                normalized = normalize_stream(load_stream(root, segment, symbol, stream_name), name)
            except Exception:
                continue
            if not normalized.empty:
                streams[name] = normalized
                break
    return bars, streams


def concatenate(frames: Sequence[pd.DataFrame], time_col: str) -> pd.DataFrame:
    valid = [frame for frame in frames if not frame.empty]
    if not valid:
        return pd.DataFrame()
    return pd.concat(valid, ignore_index=True).sort_values(time_col, kind="stable").drop_duplicates(time_col, keep="last").reset_index(drop=True)


def resample(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes == 1:
        return frame.copy()
    work = frame.copy()
    size = minutes * MINUTE_MS
    work["bucket"] = work["start_time_ms"] // size * size
    out = work.groupby("bucket", sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), turnover=("turnover", "sum"), available_at_ms=("available_at_ms", "max"), rows=("close", "count"),
    ).reset_index().rename(columns={"bucket": "start_time_ms"})
    return out[out["rows"] == minutes].drop(columns="rows").reset_index(drop=True)


def zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=max(10, window // 4)).mean()
    std = series.rolling(window, min_periods=max(10, window // 4)).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def confirmed_pivots(frame: pd.DataFrame, left: int, right: int) -> pd.DataFrame:
    high = frame["high"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    n = len(frame)
    detected_high = np.full(n, np.nan)
    detected_low = np.full(n, np.nan)
    for origin in range(left, n - right):
        detect = origin + right
        if high[origin] >= np.nanmax(high[origin-left:origin+right+1]):
            detected_high[detect] = high[origin]
        if low[origin] <= np.nanmin(low[origin-left:origin+right+1]):
            detected_low[detect] = low[origin]
    return pd.DataFrame({
        "last_swing_high": pd.Series(detected_high).ffill(),
        "last_swing_low": pd.Series(detected_low).ffill(),
        "new_swing_high": np.isfinite(detected_high),
        "new_swing_low": np.isfinite(detected_low),
    })


def enrich(frame: pd.DataFrame, minutes: int, streams: Mapping[str, pd.DataFrame], one_minute: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy().reset_index(drop=True)
    previous_close = out["close"].shift(1)
    tr = pd.concat([(out["high"]-out["low"]), (out["high"]-previous_close).abs(), (out["low"]-previous_close).abs()], axis=1).max(axis=1)
    out["atr"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    out["atr_pct"] = out["atr"] / out["close"]
    out["range"] = out["high"] - out["low"]
    out["body_signed"] = out["close"] - out["open"]
    out["body_atr"] = out["body_signed"].abs() / out["atr"]
    out["range_atr"] = out["range"] / out["atr"]
    out["lower_wick"] = out[["open", "close"]].min(axis=1) - out["low"]
    out["upper_wick"] = out["high"] - out[["open", "close"]].max(axis=1)
    out["close_location"] = (out["close"] - out["low"]) / out["range"].replace(0, np.nan)
    out["volume_z"] = zscore(np.log1p(out["volume"].clip(lower=0)), 288)
    out["turnover_z"] = zscore(np.log1p(out["turnover"].clip(lower=0)), 288)
    out = pd.concat([out, confirmed_pivots(out, 3 if minutes == 5 else 2, 3 if minutes == 5 else 2)], axis=1)
    out["internal_high"] = out["high"].shift(1).rolling(12, min_periods=6).max()
    out["internal_low"] = out["low"].shift(1).rolling(12, min_periods=6).min()
    dt = pd.to_datetime(out["start_time_ms"], unit="ms", utc=True)
    day = dt.floor("D")
    daily = out.assign(day=day).groupby("day").agg(day_high=("high", "max"), day_low=("low", "min")).shift(1)
    out["prev_day_high"] = daily["day_high"].reindex(day).to_numpy()
    out["prev_day_low"] = daily["day_low"].reindex(day).to_numpy()
    hour = dt.hour.to_numpy()
    bucket = np.select([hour < 7, hour < 13, hour < 21], [0, 1, 2], default=3)
    day_no = (dt.floor("D").astype("int64") // (DAY_MS * 1_000_000)).to_numpy()
    sid = day_no * 4 + bucket
    sessions = out.assign(sid=sid).groupby("sid").agg(high=("high", "max"), low=("low", "min")).shift(1)
    out["prev_session_high"] = sessions["high"].reindex(sid).to_numpy()
    out["prev_session_low"] = sessions["low"].reindex(sid).to_numpy()
    out["session_bucket"] = bucket
    minute_of_day = dt.hour * 60 + dt.minute
    out["hour_sin"] = np.sin(2*np.pi*minute_of_day/1440)
    out["hour_cos"] = np.cos(2*np.pi*minute_of_day/1440)
    out["dow_sin"] = np.sin(2*np.pi*dt.dayofweek/7)
    out["dow_cos"] = np.cos(2*np.pi*dt.dayofweek/7)
    h1 = resample(one_minute, 60)
    h4 = resample(one_minute, 240)
    for htf, suffix in ((h1, "1h"), (h4, "4h")):
        htf["fast"] = htf["close"].ewm(span=20, adjust=False, min_periods=20).mean()
        htf["slow"] = htf["close"].ewm(span=50, adjust=False, min_periods=50).mean()
        htf[f"trend_{suffix}"] = np.tanh((htf["fast"]-htf["slow"])/htf["close"]*500)
        htf["range_high"] = htf["high"].shift(1).rolling(30, min_periods=10).max()
        htf["range_low"] = htf["low"].shift(1).rolling(30, min_periods=10).min()
        htf[f"pd_{suffix}"] = (htf["close"]-htf["range_low"])/(htf["range_high"]-htf["range_low"])
        out = pd.merge_asof(out.sort_values("available_at_ms"), htf[["available_at_ms", f"trend_{suffix}", f"pd_{suffix}"]].sort_values("available_at_ms"), on="available_at_ms", direction="backward").sort_values("start_time_ms").reset_index(drop=True)
    for name, stream in streams.items():
        if stream.empty:
            out[name] = np.nan
        else:
            out = pd.merge_asof(out.sort_values("available_at_ms"), stream.sort_values("available_at_ms"), on="available_at_ms", direction="backward").sort_values("start_time_ms").reset_index(drop=True)
    out["oi_change_z"] = zscore(np.log(out["open_interest"].replace(0, np.nan)).diff(), 288) if "open_interest" in out else np.nan
    out["account_ratio_z"] = zscore(out["account_ratio"], 288) if "account_ratio" in out else np.nan
    if "mark" in out and "index" in out:
        out["basis_bps"] = (out["mark"]/out["index"]-1)*10_000
    elif "premium" in out:
        out["basis_bps"] = out["premium"]*10_000
    else:
        out["basis_bps"] = np.nan
    out["timeframe_min"] = minutes
    return out


def add_smt(frames: dict[str, pd.DataFrame]) -> None:
    for frame in frames.values():
        frame["smt_bull"] = 0.0
        frame["smt_bear"] = 0.0
    if "BTCUSDT" not in frames or "ETHUSDT" not in frames:
        return
    btc, eth = frames["BTCUSDT"], frames["ETHUSDT"]
    joined = btc[["start_time_ms", "low", "high", "last_swing_low", "last_swing_high"]].merge(eth[["start_time_ms", "low", "high", "last_swing_low", "last_swing_high"]], on="start_time_ms", suffixes=("_btc", "_eth"))
    b_low = joined["low_btc"] < joined["last_swing_low_btc"]
    e_low = joined["low_eth"] < joined["last_swing_low_eth"]
    b_high = joined["high_btc"] > joined["last_swing_high_btc"]
    e_high = joined["high_eth"] > joined["last_swing_high_eth"]
    joined["smt_bull_btc"], joined["smt_bull_eth"] = (b_low & ~e_low).astype(float), (e_low & ~b_low).astype(float)
    joined["smt_bear_btc"], joined["smt_bear_eth"] = (b_high & ~e_high).astype(float), (e_high & ~b_high).astype(float)
    for symbol, suffix in (("BTCUSDT", "btc"), ("ETHUSDT", "eth")):
        extra = joined[["start_time_ms", f"smt_bull_{suffix}", f"smt_bear_{suffix}"]].rename(columns={f"smt_bull_{suffix}": "smt_bull", f"smt_bear_{suffix}": "smt_bear"})
        frames[symbol] = frames[symbol].drop(columns=["smt_bull", "smt_bear"]).merge(extra, on="start_time_ms", how="left").fillna({"smt_bull": 0.0, "smt_bear": 0.0})


def swept_level(row: pd.Series, direction: int) -> tuple[str, float, float, int] | None:
    atr = float(row["atr"])
    if not np.isfinite(atr) or atr <= 0:
        return None
    names = ["last_swing_low", "prev_day_low", "prev_session_low"] if direction > 0 else ["last_swing_high", "prev_day_high", "prev_session_high"]
    hit: list[tuple[str, float, float]] = []
    for name in names:
        level = float(row.get(name, np.nan))
        if not np.isfinite(level):
            continue
        if direction > 0 and row["low"] < level < row["close"]:
            hit.append((name, level, (level-row["low"])/atr))
        if direction < 0 and row["high"] > level > row["close"]:
            hit.append((name, level, (row["high"]-level)/atr))
    if not hit:
        return None
    levels = np.array([item[1] for item in hit])
    tolerance = max(atr*0.12, float(row["close"])*0.0003)
    confluence = max(int(np.sum(np.abs(levels-level) <= tolerance)) for level in levels)
    chosen = max(hit, key=lambda item: item[2])
    return chosen[0], chosen[1], chosen[2], confluence


def raw_candidates(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    n = len(frame)
    for sweep_i in range(60, n-5):
        sweep = frame.iloc[sweep_i]
        atr = float(sweep["atr"])
        if not np.isfinite(atr):
            continue
        for direction in (1, -1):
            event = swept_level(sweep, direction)
            if event is None:
                continue
            level_name, level, sweep_atr, confluence = event
            displacement_i = None
            fvg_low = fvg_high = fvg_atr = np.nan
            for i in range(sweep_i, min(n, sweep_i+5)):
                row = frame.iloc[i]
                if float(row["body_signed"])*direction <= 0:
                    continue
                break_level = float(row["internal_high"] if direction > 0 else row["internal_low"])
                broke = float(row["close"]) > break_level if direction > 0 else float(row["close"]) < break_level
                location_ok = row["close_location"] >= 0.55 if direction > 0 else row["close_location"] <= 0.45
                if not (broke and location_ok and row["body_atr"] >= 0.25 and row["range_atr"] >= 0.55):
                    continue
                if direction > 0:
                    gap_low, gap_high = float(frame.at[i-2, "high"]), float(row["low"])
                else:
                    gap_low, gap_high = float(row["high"]), float(frame.at[i-2, "low"])
                gap = gap_high-gap_low
                if gap <= 0:
                    gap_low, gap_high, gap = sorted((float(row["open"]), float(row["close"])))[0], sorted((float(row["open"]), float(row["close"])))[1], 0.0
                displacement_i, fvg_atr = i, gap/max(float(row["atr"]), EPS)
                fvg_low, fvg_high = sorted((gap_low, gap_high))
                break
            if displacement_i is None:
                continue
            disp = frame.iloc[displacement_i]
            ob_i = max(sweep_i-2, displacement_i-1)
            for i in range(displacement_i-1, max(-1, sweep_i-3), -1):
                opposite = frame.at[i, "close"] < frame.at[i, "open"] if direction > 0 else frame.at[i, "close"] > frame.at[i, "open"]
                if opposite:
                    ob_i = i
                    break
            ob = frame.iloc[ob_i]
            if direction > 0:
                ob_low, ob_high = float(ob["low"]), float(max(ob["open"], ob["close"]))
            else:
                ob_low, ob_high = float(min(ob["open"], ob["close"])), float(ob["high"])
            overlap_low, overlap_high = max(ob_low, fvg_low), min(ob_high, fvg_high)
            overlap = overlap_high > overlap_low
            zone_low, zone_high = (overlap_low, overlap_high) if overlap else (min(ob_low, fvg_low), max(ob_high, fvg_high))
            if not (np.isfinite(zone_low) and np.isfinite(zone_high) and zone_high > zone_low > 0):
                continue
            reference = (zone_low+zone_high)/2
            stop_anchor = float(frame.loc[sweep_i:displacement_i, "low"].min() if direction > 0 else frame.loc[sweep_i:displacement_i, "high"].max())
            targets = [float(disp.get(name, np.nan)) for name in (["last_swing_high", "prev_day_high", "prev_session_high"] if direction > 0 else ["last_swing_low", "prev_day_low", "prev_session_low"])]
            targets = [value for value in targets if np.isfinite(value) and (value-reference)*direction > 0]
            target = (min(targets) if direction > 0 else max(targets)) if targets else reference + direction*3*float(disp["atr"])
            risk = abs(reference-stop_anchor)
            rr = (target-reference)*direction/risk if risk > 0 else np.nan
            pd4 = float(disp.get("pd_4h", np.nan))
            pd_ok = bool((direction > 0 and pd4 <= 0.55) or (direction < 0 and pd4 >= 0.45)) if np.isfinite(pd4) else False
            rows.append({
                "candidate_id": f"{symbol}-{int(disp['timeframe_min'])}-{int(disp['start_time_ms'])}-{direction:+d}-{sweep_i}",
                "symbol": symbol, "direction": direction, "timeframe_min": int(disp["timeframe_min"]),
                "decision_time_ms": int(disp["available_at_ms"]), "swept_level_name": level_name, "swept_level": level,
                "sweep_depth_atr": sweep_atr, "sweep_wick_atr": float((sweep["lower_wick"] if direction > 0 else sweep["upper_wick"])/atr),
                "liquidity_confluence": confluence, "displacement_body_atr": float(disp["body_atr"]),
                "displacement_range_atr": float(disp["range_atr"]), "close_location": float(disp["close_location"]),
                "fvg_low": fvg_low, "fvg_high": fvg_high, "fvg_atr": fvg_atr, "ob_low": ob_low, "ob_high": ob_high,
                "zone_low": zone_low, "zone_high": zone_high, "fvg_ob_overlap": float(overlap), "stop_anchor": stop_anchor,
                "target_price": target, "structural_rr": rr, "atr": float(disp["atr"]), "atr_pct": float(disp["atr_pct"]),
                "volume_z": float(disp.get("volume_z", np.nan)), "turnover_z": float(disp.get("turnover_z", np.nan)),
                "trend_1h": float(disp.get("trend_1h", np.nan)), "trend_4h": float(disp.get("trend_4h", np.nan)),
                "pd_1h": float(disp.get("pd_1h", np.nan)), "pd_4h": pd4, "pd_aligned": float(pd_ok),
                "oi_change_z": float(disp.get("oi_change_z", np.nan)), "account_ratio_z": float(disp.get("account_ratio_z", np.nan)),
                "basis_bps": float(disp.get("basis_bps", np.nan)), "funding": float(disp.get("funding", np.nan)),
                "smt_bull": float(disp.get("smt_bull", 0)), "smt_bear": float(disp.get("smt_bear", 0)),
                "session_bucket": float(disp.get("session_bucket", np.nan)), "hour_sin": float(disp.get("hour_sin", np.nan)),
                "hour_cos": float(disp.get("hour_cos", np.nan)), "dow_sin": float(disp.get("dow_sin", np.nan)), "dow_cos": float(disp.get("dow_cos", np.nan)),
            })
    return pd.DataFrame(rows).sort_values("decision_time_ms", kind="stable").reset_index(drop=True) if rows else pd.DataFrame()


def entry_price(candidate: Mapping[str, Any], retrace: float) -> float:
    low, high = float(candidate["zone_low"]), float(candidate["zone_high"])
    return high-retrace*(high-low) if int(candidate["direction"]) > 0 else low+retrace*(high-low)


def simulate(candidate: Mapping[str, Any], minute: pd.DataFrame, setup: pd.DataFrame, config: SetupConfig, end_ms: int) -> dict[str, Any]:
    direction = int(candidate["direction"])
    decision = int(candidate["decision_time_ms"])
    active = decision + LATENCY_MS
    limit = entry_price(candidate, config.retrace)
    stop = float(candidate["stop_anchor"]) - direction*config.stop_buffer_atr*float(candidate["atr"])
    target = float(candidate["target_price"])
    starts = minute["start_time_ms"].to_numpy(np.int64)
    begin, end = int(np.searchsorted(starts, active, side="left")), int(np.searchsorted(starts, end_ms, side="left"))
    base = {"candidate_id": candidate["candidate_id"], "symbol": candidate["symbol"], "direction": direction, "decision_time_ms": decision, "order_active_time_ms": active}
    if begin >= end or (limit-stop)*direction <= 0 or (target-limit)*direction <= 0:
        return {**base, "order_end_time_ms": end_ms, "filled": False, "resolved": False, "entry_time_ms": np.nan, "entry_price": np.nan, "stop_price": stop, "exit_time_ms": np.nan, "exit_price": np.nan, "exit_reason": "invalid_or_no_data", "gross_pnl_per_unit": 0.0, "net_r": np.nan, "mfe_r": np.nan, "mae_r": np.nan}
    fill_i = None
    for i in range(begin, end):
        row = minute.iloc[i]
        invalid = row["low"] <= stop if direction > 0 else row["high"] >= stop
        delivered = row["high"] >= target if direction > 0 else row["low"] <= target
        if invalid or delivered:
            return {**base, "order_end_time_ms": int(row["available_at_ms"]), "filled": False, "resolved": True, "entry_time_ms": np.nan, "entry_price": np.nan, "stop_price": stop, "exit_time_ms": np.nan, "exit_price": np.nan, "exit_reason": "invalidated_before_fill" if invalid else "target_before_fill", "gross_pnl_per_unit": 0.0, "net_r": np.nan, "mfe_r": np.nan, "mae_r": np.nan}
        if row["low"] <= limit <= row["high"] and i+1 < end:
            fill_i = i+1
            break
    if fill_i is None:
        return {**base, "order_end_time_ms": end_ms, "filled": False, "resolved": False, "entry_time_ms": np.nan, "entry_price": np.nan, "stop_price": stop, "exit_time_ms": np.nan, "exit_price": np.nan, "exit_reason": "pending_at_end", "gross_pnl_per_unit": 0.0, "net_r": np.nan, "mfe_r": np.nan, "mae_r": np.nan}
    entry = float(minute.iloc[fill_i]["open"])*(1+direction/10_000)
    risk = (entry-stop)*direction
    rr = (target-entry)*direction/risk if risk > 0 else -1
    if risk <= 0 or rr < config.min_rr:
        row = minute.iloc[fill_i]
        return {**base, "order_end_time_ms": int(row["available_at_ms"]), "filled": False, "resolved": True, "entry_time_ms": np.nan, "entry_price": np.nan, "stop_price": stop, "exit_time_ms": np.nan, "exit_price": np.nan, "exit_reason": "gap_or_rr_invalid", "gross_pnl_per_unit": 0.0, "net_r": np.nan, "mfe_r": np.nan, "mae_r": np.nan}
    tp1 = entry + direction*min(risk, 0.45*abs(target-entry))
    remaining, gross, tp1_hit, mfe, mae = 1.0, 0.0, False, 0.0, 0.0
    current_stop = stop
    setup_times = setup["available_at_ms"].to_numpy(np.int64)
    last_setup = int(np.searchsorted(setup_times, int(minute.iloc[fill_i]["available_at_ms"]), side="right")-1)
    exit_time = exit_price = None
    reason = "open_at_end"
    for i in range(fill_i, end):
        row = minute.iloc[i]
        high, low = float(row["high"]), float(row["low"])
        mfe = max(mfe, (high-entry)/risk if direction > 0 else (entry-low)/risk)
        mae = max(mae, (entry-low)/risk if direction > 0 else (high-entry)/risk)
        stop_hit = low <= current_stop if direction > 0 else high >= current_stop
        target_hit = high >= target if direction > 0 else low <= target
        tp1_now = (high >= tp1 if direction > 0 else low <= tp1) and not tp1_hit
        if stop_hit:
            exit_price, exit_time, reason = current_stop*(1-direction/10_000), int(row["available_at_ms"]), "stop"
            gross += remaining*(exit_price-entry)*direction
            remaining = 0
            break
        if target_hit:
            if tp1_now:
                gross += 0.4*(tp1-entry)*direction
                remaining, tp1_hit = 0.6, True
            exit_price, exit_time, reason = target*(1-direction/10_000), int(row["available_at_ms"]), "opposing_liquidity"
            gross += remaining*(exit_price-entry)*direction
            remaining = 0
            break
        if tp1_now:
            gross += 0.4*(tp1-entry)*direction
            remaining, tp1_hit = 0.6, True
        available = int(row["available_at_ms"])
        new_setup = int(np.searchsorted(setup_times, available, side="right")-1)
        if new_setup > last_setup:
            for pos in range(last_setup+1, new_setup+1):
                s = setup.iloc[pos]
                if tp1_hit and direction > 0 and bool(s["new_swing_low"]) and entry < s["last_swing_low"] < s["close"]:
                    current_stop = max(current_stop, float(s["last_swing_low"]))
                if tp1_hit and direction < 0 and bool(s["new_swing_high"]) and s["close"] < s["last_swing_high"] < entry:
                    current_stop = min(current_stop, float(s["last_swing_high"]))
                reversal = (s["close"] < s["internal_low"] and s["body_atr"] >= 0.8) if direction > 0 else (s["close"] > s["internal_high"] and s["body_atr"] >= 0.8)
                if reversal:
                    executable = int(np.searchsorted(starts, int(s["available_at_ms"])+LATENCY_MS, side="left"))
                    if executable <= i:
                        exit_price, exit_time, reason = float(row["close"])*(1-direction/10_000), int(row["available_at_ms"]), "opposite_mss"
                        gross += remaining*(exit_price-entry)*direction
                        remaining = 0
                        break
            last_setup = new_setup
            if remaining <= 0:
                break
    resolved = exit_time is not None
    if not resolved:
        final = minute.iloc[end-1]
        exit_time, exit_price = int(final["available_at_ms"]), float(final["close"])
        gross += remaining*(exit_price-entry)*direction
    fee = 5.5/10_000
    cost = entry*(fee+1/10_000)+float(exit_price)*(fee+1/10_000)
    return {**base, "order_end_time_ms": int(minute.iloc[fill_i]["start_time_ms"]), "filled": True, "resolved": resolved, "entry_time_ms": int(minute.iloc[fill_i]["start_time_ms"]), "entry_price": entry, "stop_price": stop, "exit_time_ms": exit_time, "exit_price": float(exit_price), "exit_reason": reason, "gross_pnl_per_unit": gross, "net_r": (gross-cost)/risk, "mfe_r": mfe, "mae_r": mae}


FEATURES = ["direction", "timeframe_min", "sweep_depth_atr", "sweep_wick_atr", "liquidity_confluence", "displacement_body_atr", "displacement_range_atr", "close_location", "fvg_atr", "fvg_ob_overlap", "structural_rr", "atr_pct", "volume_z", "turnover_z", "trend_1h", "trend_4h", "pd_1h", "pd_4h", "pd_aligned", "oi_change_z", "account_ratio_z", "basis_bps", "funding", "smt_bull", "smt_bear", "session_bucket", "hour_sin", "hour_cos", "dow_sin", "dow_cos", "symbol_code"]


def feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["symbol_code"] = work["symbol"].map({symbol: i for i, symbol in enumerate(sorted(work["symbol"].unique()))})
    for name in FEATURES:
        if name not in work:
            work[name] = np.nan
    x = work[FEATURES].replace([np.inf, -np.inf], np.nan)
    return x.fillna(x.median().fillna(0)).astype(float)


def setup_mask(frame: pd.DataFrame, config: SetupConfig) -> pd.Series:
    mask = (frame["timeframe_min"] == config.timeframe_min) & (frame["sweep_depth_atr"] >= config.min_sweep_atr) & (frame["displacement_body_atr"] >= config.min_body_atr) & (frame["fvg_atr"] >= config.min_fvg_atr) & (frame["structural_rr"] >= config.min_rr*0.7)
    if config.require_pd:
        mask &= frame["pd_aligned"] > 0.5
    if config.require_overlap:
        mask &= frame["fvg_ob_overlap"] > 0.5
    return mask.fillna(False)


def model_pair(seed: int) -> tuple[HistGradientBoostingClassifier, HistGradientBoostingRegressor]:
    return (
        HistGradientBoostingClassifier(learning_rate=0.05, max_iter=140, max_leaf_nodes=15, min_samples_leaf=20, l2_regularization=0.8, random_state=seed),
        HistGradientBoostingRegressor(loss="huber", learning_rate=0.045, max_iter=140, max_leaf_nodes=15, min_samples_leaf=20, l2_regularization=1.0, random_state=seed+1),
    )


def prequential_scores(frame: pd.DataFrame, eligible: pd.Series, start_ms: int, end_ms: int, policy: str, min_train: int = 50) -> pd.Series:
    scores = pd.Series(np.nan, index=frame.index, dtype=float)
    x = feature_matrix(frame)
    if policy == "frozen":
        cutoffs, windows = [start_ms], [(start_ms, end_ms)]
    else:
        freq = "MS" if policy == "monthly" else "QS"
        dates = list(pd.date_range(pd.Timestamp(start_ms, unit="ms", tz="UTC"), pd.Timestamp(end_ms, unit="ms", tz="UTC"), freq=freq, inclusive="left"))
        cutoffs = [start_ms] + [int(ts.value//1_000_000) for ts in dates if int(ts.value//1_000_000) > start_ms]
        windows = [(cutoff, cutoffs[i+1] if i+1 < len(cutoffs) else end_ms) for i, cutoff in enumerate(cutoffs)]
    for cutoff, (window_start, window_end) in zip(cutoffs, windows):
        train = eligible & frame["filled"].fillna(False) & frame["resolved"].fillna(False) & (frame["label_end_time_ms"] < cutoff) & frame["net_r"].notna()
        predict = eligible & (frame["decision_time_ms"] >= window_start) & (frame["decision_time_ms"] < window_end)
        if train.sum() < min_train or not predict.any():
            continue
        y = frame.loc[train, "net_r"].astype(float).clip(-8, 12)
        binary = (y > 0).astype(int)
        if binary.nunique() < 2:
            continue
        classifier, regressor = model_pair(7 + int(cutoff//DAY_MS)%997)
        classifier.fit(x.loc[train], binary)
        regressor.fit(x.loc[train], y)
        probability = classifier.predict_proba(x.loc[predict])[:, 1]
        expected = regressor.predict(x.loc[predict])
        scores.loc[predict] = expected*(0.55+probability)+0.2*(probability-0.5)
    return scores


def drawdown(nav: pd.Series) -> float:
    return float((nav/nav.cummax()-1).min()) if len(nav) else 0.0


def geometric_growth(nav: pd.Series) -> float:
    ratios = nav.iloc[1:].to_numpy(float)/nav.iloc[:-1].to_numpy(float)
    return float(np.exp(np.mean(np.log(ratios)))-1) if len(ratios) and np.all(ratios > 0) else -1.0


def account_sim(frame: pd.DataFrame, minute_by_symbol: Mapping[str, pd.DataFrame], account: AccountConfig, start_ms: int, end_ms: int, threshold: float, initial_nav: float = 10_000.0) -> dict[str, Any]:
    selected = frame[frame["ml_score"].notna() & (frame["ml_score"] >= threshold)].sort_values(["decision_time_ms", "ml_score"], ascending=[True, False]).drop_duplicates("decision_time_ms")
    nav, slot_free, trades, skips, liquidations = initial_nav, start_ms, [], 0, 0
    for row in selected.itertuples(index=False):
        decision = int(row.decision_time_ms)
        if not (start_ms <= decision < end_ms):
            continue
        if decision < slot_free:
            skips += 1
            continue
        if not bool(row.filled):
            slot_free = min(int(row.order_end_time_ms), end_ms)
            continue
        entry, stop, direction = float(row.entry_price), float(row.stop_price), int(row.direction)
        stop_distance = abs(entry-stop)
        fee, slip = account.taker_fee_bps/10_000, account.slippage_bps/10_000
        loss_per_unit = stop_distance + (entry+stop)*(fee+slip)
        planned = nav*account.risk_fraction
        quantity = min(planned/max(loss_per_unit, EPS), nav*account.leverage/entry)
        stop_pct = stop_distance/entry
        liq_distance = max(0, 1/account.leverage-account.maintenance_margin_rate-2*fee)
        if quantity <= 0 or stop_pct >= 0.9*liq_distance:
            liquidations += 1
            continue
        minute = minute_by_symbol[str(row.symbol)]
        pos = int(np.searchsorted(minute["start_time_ms"].to_numpy(np.int64), int(row.entry_time_ms), side="left"))
        liquidity = float(minute["turnover"].iloc[max(0, pos-60):pos+1].sum())
        notional = quantity*entry
        participation = notional/max(liquidity, notional)
        impact = account.impact_bps*math.sqrt(max(participation, 0))/10_000
        gross = quantity*float(row.gross_pnl_per_unit)
        costs = quantity*(entry+float(row.exit_price))*(fee+slip+impact)
        funding = float(row.funding) if np.isfinite(float(row.funding)) else 0.0
        funding_cost = direction*notional*funding*max(0, (int(row.exit_time_ms)-int(row.entry_time_ms))/DAY_MS*3)
        pnl = gross-costs-funding_cost
        before = nav
        nav += pnl
        trades.append({"candidate_id": row.candidate_id, "symbol": row.symbol, "direction": direction, "entry_time": iso_ms(int(row.entry_time_ms)), "exit_time": iso_ms(int(row.exit_time_ms)), "exit_reason": row.exit_reason, "quantity": quantity, "notional": notional, "planned_loss": planned, "net_pnl": pnl, "realized_r": pnl/max(planned, EPS), "nav_before": before, "nav_after": nav, "ml_score": float(row.ml_score)})
        slot_free = min(int(row.exit_time_ms), end_ms)
        if nav <= 0:
            liquidations += 1
            nav = 0
            break
    days = np.arange(start_ms, end_ms, DAY_MS, dtype=np.int64)
    daily_values = []
    for day in days:
        boundary = day+DAY_MS
        value = initial_nav
        for trade in trades:
            exit_time = utc_ms(trade["exit_time"])
            if exit_time < boundary:
                value = trade["nav_after"]
            else:
                break
        daily_values.append(max(float(value), 0))
    daily = pd.Series(daily_values, index=pd.to_datetime(days, unit="ms", utc=True), dtype=float)
    path = pd.concat([pd.Series([initial_nav], index=[daily.index[0]-pd.Timedelta(days=1)]), daily]) if len(daily) else pd.Series([initial_nav])
    pnl = np.array([trade["net_pnl"] for trade in trades], float)
    positive, negative = pnl[pnl>0].sum() if len(pnl) else 0, -pnl[pnl<0].sum() if len(pnl) else 0
    top_share = float(np.sort(np.maximum(pnl, 0))[-5:].sum()/np.maximum(pnl, 0).sum()) if len(pnl) and np.maximum(pnl, 0).sum() > 0 else None
    return {"initial_nav": initial_nav, "final_nav": float(daily.iloc[-1]) if len(daily) else nav, "account_multiple": (float(daily.iloc[-1]) if len(daily) else nav)/initial_nav, "geometric_daily_growth": geometric_growth(path), "max_drawdown": drawdown(path), "completed_trades": len(trades), "win_rate": float(np.mean(pnl>0)) if len(pnl) else None, "profit_factor": float(positive/negative) if negative > 0 else None, "top_5_pnl_share": top_share, "liquidation_events": liquidations, "slot_skips": skips, "daily_nav": [{"time": ts.isoformat(), "nav": float(value)} for ts, value in daily.items()], "trades": trades}


def setup_grid() -> list[SetupConfig]:
    return [SetupConfig(tf, sweep, body, fvg, retrace, pd, fvg > 0) for tf in (5, 15) for sweep in (0.02, 0.08, 0.16) for body in (0.45, 0.75, 1.05) for fvg in (0.0, 0.05) for retrace in (0.50, 0.62, 0.705) for pd in (False, True)]


def account_grid() -> list[AccountConfig]:
    return [AccountConfig(risk, leverage) for risk in (0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12) for leverage in (3, 5, 10, 20, 30, 50)]


def compact(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metrics.items() if key not in {"daily_nav", "trades"}}


def self_test() -> None:
    start = utc_ms("2023-01-01")
    times = start + np.arange(300)*MINUTE_MS
    price = 20_000 + np.sin(np.arange(300)/12)*100 + np.arange(300)*0.2
    minute = pd.DataFrame({"start_time_ms": times, "available_at_ms": times+MINUTE_MS, "open": price, "high": price+8, "low": price-8, "close": price+np.sin(np.arange(300))*2, "volume": 10, "turnover": price*10})
    assert len(resample(minute, 5)) == 60
    assert abs(geometric_growth(pd.Series([100, 101, 102.01]))-0.01) < 1e-9
    print("SELF_TEST_PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifact/swipalnam_smc_ml"))
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--train-segments", nargs="+", default=["PRE_2024_2023"])
    parser.add_argument("--evaluation-segments", nargs="+", default=["2024_H1"])
    parser.add_argument("--train-start", default="2023-01-01T00:00:00Z")
    parser.add_argument("--train-end-exclusive", default="2024-01-01T00:00:00Z")
    parser.add_argument("--evaluation-start", default="2024-01-01T00:00:00Z")
    parser.add_argument("--evaluation-end-exclusive", default="2024-07-01T00:00:00Z")
    parser.add_argument("--minimum-candidates", type=int, default=45)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test(); return 0
    if args.data_root is None:
        raise SystemExit("--data-root is required")
    train_start, train_end = utc_ms(args.train_start), utc_ms(args.train_end_exclusive)
    eval_start, eval_end = utc_ms(args.evaluation_start), utc_ms(args.evaluation_end_exclusive)
    minute_by_symbol: dict[str, pd.DataFrame] = {}
    setup_frames: dict[tuple[str, int], pd.DataFrame] = {}
    data_summary: dict[str, Any] = {}
    for symbol in args.symbols:
        bars_parts, stream_parts = [], {name: [] for name in ("open_interest", "account_ratio", "funding", "mark", "index", "premium")}
        for segment in [*args.train_segments, *args.evaluation_segments]:
            bars, streams = load_segment(args.data_root, segment, symbol)
            bars_parts.append(bars)
            for name, stream in streams.items(): stream_parts[name].append(stream)
        minute = concatenate(bars_parts, "start_time_ms")
        minute = minute[(minute["start_time_ms"] >= train_start) & (minute["start_time_ms"] < eval_end)].reset_index(drop=True)
        if minute.empty: raise ResearchError(f"no data for {symbol}")
        streams = {name: concatenate(parts, "available_at_ms") for name, parts in stream_parts.items()}
        minute_by_symbol[symbol] = minute
        data_summary[symbol] = {"rows_1m": len(minute), "first": iso_ms(int(minute["start_time_ms"].iloc[0])), "last": iso_ms(int(minute["start_time_ms"].iloc[-1])), "streams": {name: len(stream) for name, stream in streams.items()}}
        for tf in (5, 15): setup_frames[(symbol, tf)] = enrich(resample(minute, tf), tf, streams, minute)
    for tf in (5, 15):
        mapping = {symbol: setup_frames[(symbol, tf)] for symbol in args.symbols}; add_smt(mapping)
        for symbol, frame in mapping.items(): setup_frames[(symbol, tf)] = frame
    candidate_parts = [raw_candidates(symbol, setup_frames[(symbol, tf)]) for symbol in args.symbols for tf in (5, 15)]
    candidate_parts = [part for part in candidate_parts if not part.empty]
    if not candidate_parts: raise ResearchError("zero SMC/ICT candidates")
    candidates = pd.concat(candidate_parts, ignore_index=True).sort_values("decision_time_ms").reset_index(drop=True)
    candidates = candidates[(candidates["decision_time_ms"] >= train_start) & (candidates["decision_time_ms"] < eval_end)].reset_index(drop=True)
    grids = setup_grid()
    geometry_paths: dict[float, pd.DataFrame] = {}
    for retrace in sorted({config.retrace for config in grids}):
        records = []
        geometry = SetupConfig(5, 0, 0, 0, retrace, False, False)
        for row in candidates.to_dict("records"):
            records.append(simulate(row, minute_by_symbol[row["symbol"]], setup_frames[(row["symbol"], int(row["timeframe_min"]))], geometry, eval_end))
        geometry_paths[retrace] = pd.DataFrame(records)
    trials = {}
    for retrace, paths in geometry_paths.items():
        trial = candidates.merge(paths, on=["candidate_id", "symbol", "direction", "decision_time_ms"], how="left")
        trial["label_end_time_ms"] = trial["exit_time_ms"].fillna(trial["order_end_time_ms"])
        trials[retrace] = trial
    cheap = []
    for config in grids:
        trial, mask = trials[config.retrace], setup_mask(trials[config.retrace], config)
        resolved = mask & trial["filled"].fillna(False) & trial["resolved"].fillna(False) & (trial["label_end_time_ms"] < train_end) & trial["net_r"].notna()
        if resolved.sum() < args.minimum_candidates: continue
        sample = trial.loc[resolved, ["decision_time_ms", "net_r"]]
        thirds = np.linspace(train_start, train_end, 4, dtype=np.int64)
        means = [float(sample[(sample["decision_time_ms"] >= a) & (sample["decision_time_ms"] < b)]["net_r"].mean()) if len(sample[(sample["decision_time_ms"] >= a) & (sample["decision_time_ms"] < b)]) else -10 for a, b in zip(thirds[:-1], thirds[1:])]
        score = 0.5*float(sample["net_r"].mean())+0.3*min(means)+0.15*float(sample["net_r"].median())+0.01*math.log1p(len(sample))
        cheap.append({"config": asdict(config), "key": config.key, "score": score, "count": int(len(sample)), "third_means": means})
    if not cheap: raise ResearchError("no configuration survived the chronological pre-2024 screen")
    cheap.sort(key=lambda item: item["score"], reverse=True)
    ml_results = []
    prediction_start = train_start+120*DAY_MS
    for screen in cheap[:30]:
        config = SetupConfig(**screen["config"]); trial = trials[config.retrace].copy(); eligible = setup_mask(trial, config)
        for policy in ("monthly", "quarterly", "frozen"):
            scores = prequential_scores(trial, eligible, prediction_start, train_end, policy)
            available = scores[eligible & (trial["decision_time_ms"] >= prediction_start) & (trial["decision_time_ms"] < train_end)].dropna()
            if len(available) < 20: continue
            for threshold in sorted({float(available.quantile(q)) for q in (0.5, 0.6, 0.7, 0.8, 0.88, 0.94)}):
                trial["ml_score"] = scores
                metrics = account_sim(trial[eligible], minute_by_symbol, AccountConfig(0.01, 10), prediction_start, train_end, threshold)
                if metrics["completed_trades"] < 8 or metrics["liquidation_events"]: continue
                objective = metrics["geometric_daily_growth"]*10_000 + metrics["max_drawdown"]*0.25 + 0.02*math.log1p(metrics["completed_trades"])-0.15*max(0, (metrics["top_5_pnl_share"] or 0)-0.65)
                ml_results.append({"config": asdict(config), "key": config.key, "policy": policy, "threshold": threshold, "objective": objective, "metrics": compact(metrics), "screen": screen})
    if not ml_results: raise ResearchError("no decision-ready pre-2024 ML configuration")
    ml_results.sort(key=lambda item: item["objective"], reverse=True)
    selected = ml_results[0]; config = SetupConfig(**selected["config"]); trial = trials[config.retrace].copy(); eligible = setup_mask(trial, config)
    trial["ml_score"] = prequential_scores(trial, eligible, prediction_start, eval_end, selected["policy"])
    pre = trial[eligible & (trial["decision_time_ms"] < train_end)]
    risk_results = []
    for account in account_grid():
        metrics = account_sim(pre, minute_by_symbol, account, prediction_start, train_end, float(selected["threshold"]))
        if metrics["completed_trades"] < 8 or metrics["liquidation_events"] or metrics["final_nav"] <= 0: continue
        objective = metrics["geometric_daily_growth"]*10_000+metrics["max_drawdown"]*0.15-0.1*max(0, (metrics["top_5_pnl_share"] or 0)-0.7)
        risk_results.append({"config": asdict(account), "key": account.key, "objective": objective, "metrics": compact(metrics)})
    if not risk_results: raise ResearchError("alpha failed account sizing/liquidation-distance checks")
    risk_results.sort(key=lambda item: item["objective"], reverse=True); account = AccountConfig(**risk_results[0]["config"])
    pre_metrics = account_sim(pre, minute_by_symbol, account, prediction_start, train_end, float(selected["threshold"]))
    evaluation = trial[eligible & (trial["decision_time_ms"] >= eval_start) & (trial["decision_time_ms"] < eval_end)]
    h1_metrics = account_sim(evaluation, minute_by_symbol, account, eval_start, eval_end, float(selected["threshold"]))
    decision = "ADVANCE_FULL_CAUSAL_EVALUATION" if h1_metrics["geometric_daily_growth"] > 0 and h1_metrics["completed_trades"] >= 20 and not h1_metrics["liquidation_events"] else "REVISE_CORE_SYSTEMIZATION"
    summary = {"schema_version": 1, "system_id": "SYS-SWIPALNAM-LIQUIDITY-DELIVERY-ML-V1", "decision": decision, "target_hit_2024h1": bool(h1_metrics["geometric_daily_growth"] >= 0.01), "fixed_latency_ms": LATENCY_MS, "data": data_summary, "periods": {"train_start": args.train_start, "train_end_exclusive": args.train_end_exclusive, "evaluation_start": args.evaluation_start, "evaluation_end_exclusive": args.evaluation_end_exclusive}, "candidate_count": len(candidates), "configuration_count": len(grids), "configuration_screen_survivors": len(cheap), "selected_structural_configuration": asdict(config), "selected_structural_key": config.key, "selected_retraining_policy": selected["policy"], "selected_ml_score_threshold": selected["threshold"], "selected_account_configuration": asdict(account), "selected_account_key": account.key, "pre2024_metrics": compact(pre_metrics), "provisional_2024h1_metrics": compact(h1_metrics), "top_structural_screens": cheap[:30], "top_ml_alternatives": ml_results[:20], "top_account_alternatives": risk_results[:20], "causality_notes": ["pivots become visible only after right-side confirmation", "all market state is backward as-of joined by available_at_ms", "orders activate 500 ms after the last input availability", "a zone touch only arms entry at the next minute open", "same-minute ambiguity is stop-first", "labels become trainable only after path resolution", "one global pending/position slot", "no elapsed-time forced exit"]}
    args.output.mkdir(parents=True, exist_ok=True); write_json(args.output/"RUN_SUMMARY.json", summary)
    pd.DataFrame(pre_metrics["trades"]).to_csv(args.output/"PRE2024_TRADES.csv", index=False); pd.DataFrame(h1_metrics["trades"]).to_csv(args.output/"2024H1_TRADES.csv", index=False)
    pd.DataFrame(pre_metrics["daily_nav"]).to_csv(args.output/"PRE2024_DAILY_NAV.csv", index=False); pd.DataFrame(h1_metrics["daily_nav"]).to_csv(args.output/"2024H1_DAILY_NAV.csv", index=False)
    print(json.dumps({"decision": decision, "target_hit_2024h1": summary["target_hit_2024h1"], "pre2024": compact(pre_metrics), "provisional_2024h1": compact(h1_metrics), "structural_key": config.key, "account_key": account.key}, ensure_ascii=False, indent=2, default=json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
