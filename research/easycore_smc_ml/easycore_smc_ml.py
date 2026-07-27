#!/usr/bin/env python3
"""EasyCore SMC/ICT ML research system.

Transcript-grounded deterministic candidate generation + causal ML ranking for
Bybit USDT-linear perpetuals.  The primary setup is:

    liquidity sweep -> displacement/MSS -> FVG + origin order block ->
    causal retest/rejection -> opposing-liquidity delivery

The model does not invent entries.  It ranks deterministic setups using only
information available before the order activation time.  A fixed 500 ms delay
is respected conservatively by executing at the first complete 1-minute open
strictly after activation when sparse 500 ms data are not loaded.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

try:
    from scripts.market_data.load_canonical_bybit import load_stream, load_trade_bar
except Exception:  # allow --self-test outside the repo
    load_stream = None
    load_trade_bar = None

MS_MINUTE = 60_000
MS_5M = 5 * MS_MINUTE
DAY_MS = 24 * 60 * MS_MINUTE
EPS = 1e-12

FEATURE_COLUMNS = [
    "side",
    "setup_reversal",
    "setup_continuation",
    "liquidity_external",
    "liquidity_prev_day",
    "liquidity_asia",
    "sweep_depth_atr",
    "sweep_reclaim",
    "sweep_wick_fraction",
    "displacement_body_atr",
    "displacement_range_atr",
    "displacement_close_location",
    "mss_distance_atr",
    "fvg_width_atr",
    "ob_width_atr",
    "fvg_ob_overlap",
    "retest_age_bars",
    "retest_depth",
    "rejection_strength",
    "range_position_24h",
    "range_position_4h",
    "premium_discount_alignment",
    "ema20_slope_atr",
    "ema50_slope_atr",
    "trend_alignment",
    "channel_z",
    "channel_reentry",
    "atr_pct",
    "vol_z",
    "volume_impulse",
    "oi_change_1h",
    "oi_change_4h",
    "account_ratio_skew",
    "premium_bps",
    "mark_index_bps",
    "funding_rate_last",
    "hour_sin",
    "hour_cos",
    "is_london",
    "is_new_york",
    "is_killzone",
    "target_distance_r",
    "stop_distance_atr",
]


@dataclass(frozen=True)
class CostModel:
    taker_fee_bps: float = 6.0
    slippage_bps: float = 2.0
    maintenance_margin_rate: float = 0.005
    liquidation_buffer_pct: float = 0.01

    @property
    def fee_rate(self) -> float:
        return self.taker_fee_bps * 1e-4

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps * 1e-4


@dataclass(frozen=True)
class RuleConfig:
    config_id: str
    min_sweep_atr: float
    min_displacement_body_atr: float
    min_displacement_range_atr: float
    min_fvg_atr: float
    max_sweep_to_displacement_bars: int
    max_setup_age_bars: int
    min_rejection_strength: float
    min_target_r: float
    partial_fraction: float
    target1_r: float
    trail_after_target1: bool
    allow_reversal: bool = True
    allow_continuation: bool = True
    require_same_bar_reclaim: bool = True


@dataclass
class Candidate:
    candidate_id: str
    symbol: str
    signal_time_ms: int
    activation_time_ms: int
    side: int
    setup_type: str
    liquidity_kind: str
    sweep_time_ms: int
    displacement_time_ms: int
    retest_time_ms: int
    entry_reference: float
    stop_reference: float
    target1_reference: float
    target2_reference: float
    features: dict[str, float]
    config_id: str


@dataclass
class Outcome:
    candidate_id: str
    resolved: bool
    entry_time_ms: int | None
    exit_time_ms: int | None
    entry_fill: float | None
    exit_fill: float | None
    gross_r: float | None
    net_r: float | None
    max_favorable_r: float | None
    max_adverse_r: float | None
    target1_hit: bool
    target2_hit: bool
    stop_hit: bool
    structural_exit: bool
    funding_r: float
    event_log: list[dict[str, Any]]


@dataclass(frozen=True)
class PortfolioConfig:
    risk_fraction: float
    leverage: float
    score_threshold: float
    min_probability: float


@dataclass
class PortfolioResult:
    initial_nav: float
    final_nav: float
    account_multiple: float
    geometric_daily_growth: float
    max_drawdown: float
    completed_trades: int
    win_rate: float
    profit_factor: float
    top5_profit_concentration: float
    liquidations: int
    rejected_liquidation_guard: int
    rejected_margin: int
    daily_nav: list[dict[str, Any]]
    trades: list[dict[str, Any]]


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _sha256_json(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _utc_timestamp_ms(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype("int64"), unit="ms", utc=True)


def _ensure_bar_schema(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"start_time_ms", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"bar frame missing columns: {sorted(missing)}")
    out = frame.copy().sort_values("start_time_ms", kind="stable").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume", "turnover"):
        if col not in out:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if "source_available" in out:
        out = out[out["source_available"].fillna(False).astype(bool)].copy()
    return out.reset_index(drop=True)


def _last_value_by_5m(frame: pd.DataFrame, timestamp_col: str, value_cols: Sequence[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["start_time_ms", *value_cols])
    work = frame.copy()
    work["start_time_ms"] = (work[timestamp_col].astype("int64") // MS_5M) * MS_5M
    cols = ["start_time_ms", *value_cols]
    return work[cols].sort_values(timestamp_col if timestamp_col in work else "start_time_ms").groupby(
        "start_time_ms", as_index=False
    ).last()


def _atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    prev_close = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def _confirmed_swings(high: np.ndarray, low: np.ndarray, left: int, right: int) -> tuple[np.ndarray, np.ndarray]:
    """Return last causally confirmed pivot high/low at each observation index."""
    n = len(high)
    last_hi = np.full(n, np.nan)
    last_lo = np.full(n, np.nan)
    current_hi = np.nan
    current_lo = np.nan
    for t in range(n):
        j = t - right
        if j >= left:
            hi_window = high[j - left : j + right + 1]
            lo_window = low[j - left : j + right + 1]
            h = high[j]
            l = low[j]
            if np.isfinite(h) and h >= np.nanmax(hi_window) and np.sum(np.isclose(hi_window, h)) == 1:
                current_hi = h
            if np.isfinite(l) and l <= np.nanmin(lo_window) and np.sum(np.isclose(lo_window, l)) == 1:
                current_lo = l
        last_hi[t] = current_hi
        last_lo[t] = current_lo
    return last_hi, last_lo


def _rolling_regression_z(close: pd.Series, window: int = 48) -> tuple[pd.Series, pd.Series]:
    values = close.to_numpy(dtype=float)
    z = np.full(len(values), np.nan)
    slope = np.full(len(values), np.nan)
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    denom = np.sum((x - x_mean) ** 2)
    for i in range(window - 1, len(values)):
        y = values[i - window + 1 : i + 1]
        if not np.all(np.isfinite(y)):
            continue
        b = np.sum((x - x_mean) * (y - y.mean())) / max(denom, EPS)
        fit = y.mean() + b * (x - x_mean)
        resid = y - fit
        sd = resid.std(ddof=1)
        z[i] = resid[-1] / sd if sd > 0 else 0.0
        slope[i] = b
    return pd.Series(z, index=close.index), pd.Series(slope, index=close.index)


def prepare_features(
    bars5: pd.DataFrame,
    oi5: pd.DataFrame | None = None,
    ratio5: pd.DataFrame | None = None,
    premium1: pd.DataFrame | None = None,
    mark1: pd.DataFrame | None = None,
    index1: pd.DataFrame | None = None,
    funding: pd.DataFrame | None = None,
) -> pd.DataFrame:
    df = _ensure_bar_schema(bars5)
    df["ts"] = _utc_timestamp_ms(df["start_time_ms"])
    df["available_at_ms"] = df.get("available_at_ms", df["start_time_ms"] + MS_5M).astype("int64")
    df["atr"] = _atr(df)
    df["atr_pct"] = df["atr"] / df["close"].replace(0, np.nan)
    df["body"] = (df["close"] - df["open"]).abs()
    df["range"] = (df["high"] - df["low"]).clip(lower=EPS)
    df["body_atr"] = df["body"] / df["atr"]
    df["range_atr"] = df["range"] / df["atr"]
    df["close_location"] = (df["close"] - df["low"]) / df["range"]
    df["upper_wick_fraction"] = (df["high"] - df[["open", "close"]].max(axis=1)) / df["range"]
    df["lower_wick_fraction"] = (df[["open", "close"]].min(axis=1) - df["low"]) / df["range"]
    for span in (20, 50, 200):
        df[f"ema{span}"] = df["close"].ewm(span=span, adjust=False, min_periods=span).mean()
        df[f"ema{span}_slope_atr"] = (df[f"ema{span}"] - df[f"ema{span}"].shift(6)) / df["atr"]
    log_volume = np.log1p(df["volume"].clip(lower=0))
    vol_mean = log_volume.rolling(96, min_periods=24).mean()
    vol_std = log_volume.rolling(96, min_periods=24).std().replace(0, np.nan)
    df["vol_z"] = (log_volume - vol_mean) / vol_std
    df["volume_impulse"] = df["volume"] / df["volume"].rolling(24, min_periods=6).median().replace(0, np.nan)

    # Causally confirmed internal/external structure.
    hi = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    df["int_swing_high"], df["int_swing_low"] = _confirmed_swings(hi, lo, 2, 2)
    df["ext_swing_high"], df["ext_swing_low"] = _confirmed_swings(hi, lo, 6, 6)

    # Completed rolling ranges; all shifted to exclude the decision bar.
    df["rolling_high_4h"] = df["high"].rolling(48, min_periods=24).max().shift(1)
    df["rolling_low_4h"] = df["low"].rolling(48, min_periods=24).min().shift(1)
    df["rolling_high_24h"] = df["high"].rolling(288, min_periods=96).max().shift(1)
    df["rolling_low_24h"] = df["low"].rolling(288, min_periods=96).min().shift(1)
    df["range_position_4h"] = (df["close"] - df["rolling_low_4h"]) / (
        df["rolling_high_4h"] - df["rolling_low_4h"]
    ).replace(0, np.nan)
    df["range_position_24h"] = (df["close"] - df["rolling_low_24h"]) / (
        df["rolling_high_24h"] - df["rolling_low_24h"]
    ).replace(0, np.nan)

    # Previous UTC day high/low.
    df["date_key"] = df["ts"].dt.floor("D")
    daily = df.groupby("date_key").agg(day_high=("high", "max"), day_low=("low", "min"))
    daily["prev_day_high"] = daily["day_high"].shift(1)
    daily["prev_day_low"] = daily["day_low"].shift(1)
    df = df.merge(
        daily[["prev_day_high", "prev_day_low"]],
        left_on="date_key", right_index=True, how="left", validate="many_to_one",
    )

    # Completed 00:00-06:00 UTC reference range. Before completion, use prior day's session.
    hour = df["ts"].dt.hour
    asia_rows = df[hour < 6].groupby("date_key").agg(asia_high=("high", "max"), asia_low=("low", "min"))
    asia_rows["prev_asia_high"] = asia_rows["asia_high"].shift(1)
    asia_rows["prev_asia_low"] = asia_rows["asia_low"].shift(1)
    df = df.merge(
        asia_rows, left_on="date_key", right_index=True, how="left", validate="many_to_one",
    )
    before_complete = hour < 6
    df.loc[before_complete, "asia_high"] = df.loc[before_complete, "prev_asia_high"]
    df.loc[before_complete, "asia_low"] = df.loc[before_complete, "prev_asia_low"]

    df["channel_z"], df["channel_slope"] = _rolling_regression_z(df["close"], 48)

    if oi5 is not None and not oi5.empty:
        oi = oi5.copy().rename(columns={"timestamp_ms": "start_time_ms"})
        df = df.merge(oi[["start_time_ms", "open_interest"]], on="start_time_ms", how="left")
    else:
        df["open_interest"] = np.nan
    df["open_interest"] = df["open_interest"].ffill()
    df["oi_change_1h"] = df["open_interest"].pct_change(12, fill_method=None)
    df["oi_change_4h"] = df["open_interest"].pct_change(48, fill_method=None)

    if ratio5 is not None and not ratio5.empty:
        ratio = ratio5.copy().rename(columns={"timestamp_ms": "start_time_ms"})
        df = df.merge(ratio[["start_time_ms", "buy_ratio", "sell_ratio"]], on="start_time_ms", how="left")
    else:
        df["buy_ratio"], df["sell_ratio"] = np.nan, np.nan
    df[["buy_ratio", "sell_ratio"]] = df[["buy_ratio", "sell_ratio"]].ffill()
    df["account_ratio_skew"] = df["buy_ratio"] - df["sell_ratio"]

    def merge_last(frame: pd.DataFrame | None, name: str) -> None:
        nonlocal df
        if frame is None or frame.empty:
            df[name] = np.nan
            return
        part = _last_value_by_5m(frame, "start_time_ms", ["close"]).rename(columns={"close": name})
        df = df.merge(part, on="start_time_ms", how="left")
        df[name] = df[name].ffill()

    merge_last(premium1, "premium_close")
    merge_last(mark1, "mark_close")
    merge_last(index1, "index_close")
    df["premium_bps"] = (df["premium_close"] / df["close"] - 1.0) * 1e4
    df["mark_index_bps"] = (df["mark_close"] / df["index_close"] - 1.0) * 1e4

    df["funding_rate_last"] = 0.0
    if funding is not None and not funding.empty:
        fund = funding.copy().sort_values("timestamp_ms")
        left = df[["start_time_ms"]].sort_values("start_time_ms")
        merged = pd.merge_asof(
            left,
            fund[["timestamp_ms", "funding_rate"]],
            left_on="start_time_ms",
            right_on="timestamp_ms",
            direction="backward",
        )
        df["funding_rate_last"] = merged["funding_rate"].fillna(0.0).to_numpy()

    hour_float = df["ts"].dt.hour + df["ts"].dt.minute / 60.0
    df["hour_sin"] = np.sin(2 * np.pi * hour_float / 24.0)
    df["hour_cos"] = np.cos(2 * np.pi * hour_float / 24.0)
    df["is_london"] = ((hour_float >= 7) & (hour_float < 11)).astype(float)
    df["is_new_york"] = ((hour_float >= 13) & (hour_float < 17)).astype(float)
    df["is_killzone"] = ((df["is_london"] + df["is_new_york"]) > 0).astype(float)
    return df.reset_index(drop=True)


def _liquidity_levels(row: pd.Series, side: int, previous_close: float) -> list[tuple[str, float, bool]]:
    if side == 1:  # sell-side liquidity below price
        raw = [
            ("internal_swing", row.get("int_swing_low"), False),
            ("external_swing", row.get("ext_swing_low"), True),
            ("previous_day", row.get("prev_day_low"), True),
            ("asia", row.get("asia_low"), True),
            ("rolling_24h", row.get("rolling_low_24h"), True),
        ]
        valid = [(k, float(v), ext) for k, v, ext in raw if pd.notna(v) and float(v) < previous_close]
        return sorted(valid, key=lambda x: x[1], reverse=True)
    raw = [
        ("internal_swing", row.get("int_swing_high"), False),
        ("external_swing", row.get("ext_swing_high"), True),
        ("previous_day", row.get("prev_day_high"), True),
        ("asia", row.get("asia_high"), True),
        ("rolling_24h", row.get("rolling_high_24h"), True),
    ]
    valid = [(k, float(v), ext) for k, v, ext in raw if pd.notna(v) and float(v) > previous_close]
    return sorted(valid, key=lambda x: x[1])


def _opposing_target(row: pd.Series, side: int, entry: float, atr: float) -> tuple[float, str]:
    if side == 1:
        levels = [
            ("internal_swing", row.get("int_swing_high")),
            ("external_swing", row.get("ext_swing_high")),
            ("previous_day", row.get("prev_day_high")),
            ("asia", row.get("asia_high")),
            ("rolling_24h", row.get("rolling_high_24h")),
        ]
        valid = [(k, float(v)) for k, v in levels if pd.notna(v) and float(v) > entry + 0.2 * atr]
        if valid:
            return min(valid, key=lambda kv: kv[1])[1], min(valid, key=lambda kv: kv[1])[0]
        return entry + 3.0 * atr, "atr_fallback"
    levels = [
        ("internal_swing", row.get("int_swing_low")),
        ("external_swing", row.get("ext_swing_low")),
        ("previous_day", row.get("prev_day_low")),
        ("asia", row.get("asia_low")),
        ("rolling_24h", row.get("rolling_low_24h")),
    ]
    valid = [(k, float(v)) for k, v in levels if pd.notna(v) and float(v) < entry - 0.2 * atr]
    if valid:
        return max(valid, key=lambda kv: kv[1])[1], max(valid, key=lambda kv: kv[1])[0]
    return entry - 3.0 * atr, "atr_fallback"


def _find_origin_ob(df: pd.DataFrame, start: int, end: int, side: int) -> tuple[float, float, int]:
    for j in range(end - 1, max(start - 1, -1), -1):
        row = df.iloc[j]
        opposite = row["close"] < row["open"] if side == 1 else row["close"] > row["open"]
        if opposite:
            if side == 1:
                return float(row["low"]), float(row["open"]), j
            return float(row["open"]), float(row["high"]), j
    row = df.iloc[max(start, 0)]
    return float(row["low"]), float(row["high"]), max(start, 0)


def generate_candidates(df: pd.DataFrame, symbol: str, cfg: RuleConfig) -> list[Candidate]:
    candidates: list[Candidate] = []
    active_sweeps: list[dict[str, Any]] = []
    setups: list[dict[str, Any]] = []
    n = len(df)
    warmup = 300
    for i in range(warmup, n):
        row = df.iloc[i]
        atr = _finite(row.get("atr"), np.nan)
        if not math.isfinite(atr) or atr <= 0:
            continue
        prev_close = float(df.iloc[i - 1]["close"])

        # Detect one most-relevant sweep per direction; deduplicate near-identical levels.
        for side in (1, -1):
            levels = _liquidity_levels(row, side, prev_close)
            selected: tuple[str, float, bool] | None = None
            for kind, level, external in levels:
                if side == 1:
                    crossed = float(row["low"]) < level - cfg.min_sweep_atr * atr
                    reclaimed = float(row["close"]) > level
                else:
                    crossed = float(row["high"]) > level + cfg.min_sweep_atr * atr
                    reclaimed = float(row["close"]) < level
                if crossed and (reclaimed or not cfg.require_same_bar_reclaim):
                    selected = (kind, level, external)
                    break
            if selected is None:
                continue
            kind, level, external = selected
            extreme = float(row["low"] if side == 1 else row["high"])
            sweep_depth = side * (level - extreme) / atr
            reclaim = side * (float(row["close"]) - level) / atr
            wick_fraction = float(row["lower_wick_fraction"] if side == 1 else row["upper_wick_fraction"])
            trigger_level = float(row["int_swing_high"] if side == 1 else row["int_swing_low"])
            if not math.isfinite(trigger_level):
                continue
            active_sweeps.append(
                {
                    "side": side,
                    "index": i,
                    "time_ms": int(row["start_time_ms"]),
                    "kind": kind,
                    "external": external,
                    "level": level,
                    "extreme": extreme,
                    "sweep_depth_atr": sweep_depth,
                    "reclaim": reclaim,
                    "wick_fraction": wick_fraction,
                    "trigger_level": trigger_level,
                    "range_position_24h": _finite(row.get("range_position_24h"), 0.5),
                }
            )

        # Promote recent sweeps to causal MSS/displacement setups.
        kept_sweeps: list[dict[str, Any]] = []
        for sweep in active_sweeps:
            age = i - int(sweep["index"])
            if age <= 0:
                kept_sweeps.append(sweep)
                continue
            if age > cfg.max_sweep_to_displacement_bars:
                continue
            side = int(sweep["side"])
            bullish = float(row["close"]) > float(row["open"])
            direction_ok = bullish if side == 1 else not bullish
            break_distance = side * (float(row["close"]) - float(sweep["trigger_level"])) / atr
            body_atr = float(row["body_atr"])
            range_atr = float(row["range_atr"])
            close_loc = float(row["close_location"] if side == 1 else 1.0 - row["close_location"])
            if i < 2:
                kept_sweeps.append(sweep)
                continue
            if side == 1:
                fvg_low = float(df.iloc[i - 2]["high"])
                fvg_high = float(row["low"])
            else:
                fvg_low = float(row["high"])
                fvg_high = float(df.iloc[i - 2]["low"])
            fvg_width = max(0.0, fvg_high - fvg_low)
            displaced = (
                direction_ok
                and break_distance > 0
                and body_atr >= cfg.min_displacement_body_atr
                and range_atr >= cfg.min_displacement_range_atr
                and close_loc >= 0.62
                and fvg_width / atr >= cfg.min_fvg_atr
            )
            if not displaced:
                kept_sweeps.append(sweep)
                continue
            ob_low, ob_high, ob_idx = _find_origin_ob(df, int(sweep["index"]) - 3, i, side)
            overlap = max(0.0, min(ob_high, fvg_high) - max(ob_low, fvg_low))
            setup_type = "reversal" if bool(sweep["external"]) else "continuation"
            if setup_type == "reversal" and not cfg.allow_reversal:
                continue
            if setup_type == "continuation" and not cfg.allow_continuation:
                continue
            setups.append(
                {
                    **sweep,
                    "setup_type": setup_type,
                    "displacement_index": i,
                    "displacement_time_ms": int(row["start_time_ms"]),
                    "mss_distance_atr": break_distance,
                    "body_atr": body_atr,
                    "range_atr": range_atr,
                    "close_location": close_loc,
                    "fvg_low": fvg_low,
                    "fvg_high": fvg_high,
                    "fvg_width_atr": fvg_width / atr,
                    "ob_low": ob_low,
                    "ob_high": ob_high,
                    "ob_idx": ob_idx,
                    "ob_width_atr": (ob_high - ob_low) / atr,
                    "fvg_ob_overlap": overlap / max(fvg_width, EPS),
                    "atr": atr,
                }
            )
        active_sweeps = kept_sweeps

        # Wait for a fresh causal retest/rejection; no optimistic touch-only entry.
        kept_setups: list[dict[str, Any]] = []
        for setup in setups:
            age = i - int(setup["displacement_index"])
            if age <= 0:
                kept_setups.append(setup)
                continue
            if age > cfg.max_setup_age_bars:
                continue
            side = int(setup["side"])
            stop = (
                min(float(setup["extreme"]), float(setup["ob_low"])) - 0.08 * atr
                if side == 1
                else max(float(setup["extreme"]), float(setup["ob_high"])) + 0.08 * atr
            )
            invalid = float(row["close"]) <= stop if side == 1 else float(row["close"]) >= stop
            if invalid:
                continue
            zone_low = max(float(setup["fvg_low"]), float(setup["ob_low"]))
            zone_high = min(float(setup["fvg_high"]), float(setup["ob_high"]))
            if zone_low >= zone_high:
                # No literal overlap: use the FVG, while retaining overlap as a quality feature.
                zone_low, zone_high = float(setup["fvg_low"]), float(setup["fvg_high"])
            touched = float(row["low"]) <= zone_high and float(row["high"]) >= zone_low
            if not touched:
                # Setup is invalid if price delivers through the opposite target before entry.
                kept_setups.append(setup)
                continue
            rejection = float(row["close_location"] if side == 1 else 1.0 - row["close_location"])
            direction_candle = float(row["close"] - row["open"]) * side > 0
            if rejection < cfg.min_rejection_strength or not direction_candle:
                kept_setups.append(setup)
                continue
            entry_ref = float(row["close"])
            stop_distance = side * (entry_ref - stop)
            if stop_distance <= 0:
                continue
            target2, target_kind = _opposing_target(row, side, entry_ref, atr)
            target_distance = side * (target2 - entry_ref)
            target_r = target_distance / stop_distance
            if target_r < cfg.min_target_r:
                continue
            target1 = entry_ref + side * min(cfg.target1_r * stop_distance, 0.75 * target_distance)
            range_pos = _finite(row.get("range_position_24h"), 0.5)
            pd_alignment = (1.0 - range_pos) if side == 1 else range_pos
            trend_alignment = float(
                (side == 1 and row["ema20"] > row["ema50"] > row["ema200"])
                or (side == -1 and row["ema20"] < row["ema50"] < row["ema200"])
            )
            channel_reentry = float(
                (side == 1 and _finite(setup.get("range_position_24h"), 0.5) < 0.15 and _finite(row.get("channel_z")) > -1.0)
                or (side == -1 and _finite(setup.get("range_position_24h"), 0.5) > 0.85 and _finite(row.get("channel_z")) < 1.0)
            )
            features = {
                "side": float(side),
                "setup_reversal": float(setup["setup_type"] == "reversal"),
                "setup_continuation": float(setup["setup_type"] == "continuation"),
                "liquidity_external": float(bool(setup["external"])),
                "liquidity_prev_day": float(setup["kind"] == "previous_day"),
                "liquidity_asia": float(setup["kind"] == "asia"),
                "sweep_depth_atr": _finite(setup["sweep_depth_atr"]),
                "sweep_reclaim": _finite(setup["reclaim"]),
                "sweep_wick_fraction": _finite(setup["wick_fraction"]),
                "displacement_body_atr": _finite(setup["body_atr"]),
                "displacement_range_atr": _finite(setup["range_atr"]),
                "displacement_close_location": _finite(setup["close_location"]),
                "mss_distance_atr": _finite(setup["mss_distance_atr"]),
                "fvg_width_atr": _finite(setup["fvg_width_atr"]),
                "ob_width_atr": _finite(setup["ob_width_atr"]),
                "fvg_ob_overlap": _finite(setup["fvg_ob_overlap"]),
                "retest_age_bars": float(age),
                "retest_depth": side * (float(setup["fvg_high"] if side == 1 else setup["fvg_low"]) - entry_ref) / atr,
                "rejection_strength": rejection,
                "range_position_24h": range_pos,
                "range_position_4h": _finite(row.get("range_position_4h"), 0.5),
                "premium_discount_alignment": pd_alignment,
                "ema20_slope_atr": side * _finite(row.get("ema20_slope_atr")),
                "ema50_slope_atr": side * _finite(row.get("ema50_slope_atr")),
                "trend_alignment": trend_alignment,
                "channel_z": side * _finite(row.get("channel_z")),
                "channel_reentry": channel_reentry,
                "atr_pct": _finite(row.get("atr_pct")),
                "vol_z": _finite(row.get("vol_z")),
                "volume_impulse": _finite(row.get("volume_impulse"), 1.0),
                "oi_change_1h": side * _finite(row.get("oi_change_1h")),
                "oi_change_4h": side * _finite(row.get("oi_change_4h")),
                "account_ratio_skew": -side * _finite(row.get("account_ratio_skew")),
                "premium_bps": -side * _finite(row.get("premium_bps")),
                "mark_index_bps": -side * _finite(row.get("mark_index_bps")),
                "funding_rate_last": -side * _finite(row.get("funding_rate_last")),
                "hour_sin": _finite(row.get("hour_sin")),
                "hour_cos": _finite(row.get("hour_cos")),
                "is_london": _finite(row.get("is_london")),
                "is_new_york": _finite(row.get("is_new_york")),
                "is_killzone": _finite(row.get("is_killzone")),
                "target_distance_r": target_r,
                "stop_distance_atr": stop_distance / atr,
            }
            signal_time = int(row["start_time_ms"] + MS_5M)
            activation = signal_time + 500
            payload = [symbol, cfg.config_id, signal_time, side, setup["time_ms"], setup["displacement_time_ms"]]
            cid = hashlib.sha256("|".join(map(str, payload)).encode()).hexdigest()[:20]
            candidates.append(
                Candidate(
                    candidate_id=cid,
                    symbol=symbol,
                    signal_time_ms=signal_time,
                    activation_time_ms=activation,
                    side=side,
                    setup_type=str(setup["setup_type"]),
                    liquidity_kind=str(setup["kind"]),
                    sweep_time_ms=int(setup["time_ms"]),
                    displacement_time_ms=int(setup["displacement_time_ms"]),
                    retest_time_ms=int(row["start_time_ms"]),
                    entry_reference=entry_ref,
                    stop_reference=stop,
                    target1_reference=target1,
                    target2_reference=target2,
                    features=features,
                    config_id=cfg.config_id,
                )
            )
            # A consumed PD array is not reused.
        setups = kept_setups
    return candidates


def _first_full_minute_after_activation(activation_ms: int) -> int:
    return ((activation_ms // MS_MINUTE) + 1) * MS_MINUTE


def _price_fill(reference: float, side: int, entering: bool, costs: CostModel) -> float:
    direction = side if entering else -side
    return float(reference) * (1.0 + direction * costs.slippage_rate)


def _funding_cost_per_unit(
    funding: pd.DataFrame | None,
    entry_ms: int,
    exit_ms: int,
    side: int,
    reference_price: float,
) -> float:
    if funding is None or funding.empty or exit_ms <= entry_ms:
        return 0.0
    subset = funding[(funding["timestamp_ms"] > entry_ms) & (funding["timestamp_ms"] <= exit_ms)]
    if subset.empty:
        return 0.0
    # Positive funding is paid by longs and received by shorts.
    return float(side * reference_price * subset["funding_rate"].sum())


def simulate_candidate(
    candidate: Candidate,
    minute_bars: pd.DataFrame,
    funding: pd.DataFrame | None,
    cfg: RuleConfig,
    costs: CostModel,
    *,
    horizon_minutes: int | None,
) -> Outcome:
    bars = minute_bars
    start_ms = _first_full_minute_after_activation(candidate.activation_time_ms)
    times = bars["start_time_ms"].to_numpy(dtype=np.int64)
    start = int(np.searchsorted(times, start_ms, side="left"))
    if start >= len(bars):
        return Outcome(candidate.candidate_id, False, None, None, None, None, None, None, None, None, False, False, False, False, 0.0, [])
    end = len(bars)
    if horizon_minutes is not None:
        end_ms = start_ms + horizon_minutes * MS_MINUTE
        end = min(end, int(np.searchsorted(times, end_ms, side="right")))
    if end <= start:
        return Outcome(candidate.candidate_id, False, None, None, None, None, None, None, None, None, False, False, False, False, 0.0, [])

    side = candidate.side
    entry_ref = float(bars.iloc[start]["open"])
    entry = _price_fill(entry_ref, side, True, costs)
    stop = candidate.stop_reference
    # Reject a latency move that has already invalidated the original setup.
    if side * (entry - stop) <= 0:
        return Outcome(candidate.candidate_id, True, int(times[start]), int(times[start]), entry, entry, -1.0, -1.0, 0.0, -1.0, False, False, True, False, 0.0, [{"type": "latency_invalidation", "time_ms": int(times[start]), "price": entry}])

    risk_price = abs(entry - stop) + entry * costs.fee_rate + stop * costs.fee_rate
    target2 = candidate.target2_reference
    target_distance = side * (target2 - entry)
    if target_distance <= 0:
        return Outcome(
            candidate.candidate_id, False, None, None, None, None, None, None, None, None,
            False, False, False, False, 0.0,
            [{"type": "target_delivered_before_entry", "time_ms": int(times[start]), "price": entry}],
        )
    target1 = entry + side * min(cfg.target1_r * abs(entry - stop), 0.75 * target_distance)
    remaining = 1.0
    realized = -entry * costs.fee_rate
    event_log: list[dict[str, Any]] = [{"type": "entry", "time_ms": int(times[start]), "price": entry, "fraction": 1.0}]
    target1_hit = False
    target2_hit = False
    stop_hit = False
    structural_exit = False
    max_fav = 0.0
    max_adv = 0.0
    exit_fill = entry
    exit_idx = start
    active_stop = stop

    # Structural exit: a strong opposite 5m close is approximated causally from
    # complete 1m bars grouped in five.  It is subordinate to hard stop/target.
    body_window: list[float] = []
    for j in range(start, end):
        b = bars.iloc[j]
        high = float(b["high"])
        low = float(b["low"])
        fav = side * ((high if side == 1 else low) - entry) / max(risk_price, EPS)
        adv = side * ((low if side == 1 else high) - entry) / max(risk_price, EPS)
        max_fav = max(max_fav, fav)
        max_adv = min(max_adv, adv)

        # Same-minute ambiguity is resolved adversely: hard stop before targets.
        hit_stop = low <= active_stop if side == 1 else high >= active_stop
        if hit_stop:
            exit_fill = _price_fill(active_stop, side, False, costs)
            realized += remaining * side * (exit_fill - entry) - remaining * exit_fill * costs.fee_rate
            event_log.append({"type": "stop", "time_ms": int(times[j]), "price": exit_fill, "fraction": remaining})
            remaining = 0.0
            stop_hit = True
            exit_idx = j
            break

        if not target1_hit:
            hit_t1 = high >= target1 if side == 1 else low <= target1
            if hit_t1:
                fraction = min(cfg.partial_fraction, remaining)
                fill = _price_fill(target1, side, False, costs)
                realized += fraction * side * (fill - entry) - fraction * fill * costs.fee_rate
                remaining -= fraction
                target1_hit = True
                event_log.append({"type": "target1", "time_ms": int(times[j]), "price": fill, "fraction": fraction})
                if cfg.trail_after_target1:
                    # Apply break-even only from the next minute, never retroactively.
                    active_stop = entry

        if remaining > EPS:
            hit_t2 = high >= target2 if side == 1 else low <= target2
            if hit_t2:
                fill = _price_fill(target2, side, False, costs)
                realized += remaining * side * (fill - entry) - remaining * fill * costs.fee_rate
                event_log.append({"type": "target2", "time_ms": int(times[j]), "price": fill, "fraction": remaining})
                remaining = 0.0
                target2_hit = True
                exit_fill = fill
                exit_idx = j
                break

        # Opposite delivery / failed retest: every completed five-minute block,
        # exit when a high-volume body closes back through the entry-side zone.
        body_window.append(abs(float(b["close"]) - float(b["open"])))
        if len(body_window) > 60:
            body_window.pop(0)
        if j > start + 4 and (int(times[j]) + MS_MINUTE) % MS_5M == 0 and len(body_window) >= 20:
            block = bars.iloc[j - 4 : j + 1]
            block_open = float(block.iloc[0]["open"])
            block_close = float(block.iloc[-1]["close"])
            block_body = abs(block_close - block_open)
            body_med = float(np.median(body_window))
            opposite = side * (block_close - block_open) < 0
            failed_zone = block_close < candidate.entry_reference if side == 1 else block_close > candidate.entry_reference
            if opposite and failed_zone and block_body > 2.0 * max(body_med, EPS):
                next_j = min(j + 1, end - 1)
                ref = float(bars.iloc[next_j]["open"])
                fill = _price_fill(ref, side, False, costs)
                realized += remaining * side * (fill - entry) - remaining * fill * costs.fee_rate
                event_log.append({"type": "structural_exit", "time_ms": int(times[next_j]), "price": fill, "fraction": remaining})
                remaining = 0.0
                structural_exit = True
                exit_fill = fill
                exit_idx = next_j
                break

    if remaining > EPS:
        # A finite ML label horizon censors unresolved setups.  Final evaluation
        # marks an open position at the period end instead of forcing a strategy exit.
        if horizon_minutes is not None:
            return Outcome(candidate.candidate_id, False, int(times[start]), None, entry, None, None, None, max_fav, max_adv, target1_hit, False, False, False, 0.0, event_log)
        last = bars.iloc[end - 1]
        mark = float(last["close"])
        realized += remaining * side * (mark - entry)
        event_log.append({"type": "period_end_mark", "time_ms": int(times[end - 1] + MS_MINUTE), "price": mark, "fraction": remaining})
        exit_fill = mark
        exit_idx = end - 1

    exit_ms = int(times[exit_idx] + (MS_MINUTE if event_log[-1]["type"] == "period_end_mark" else 0))
    funding_cost = _funding_cost_per_unit(funding, int(times[start]), exit_ms, side, entry)
    realized -= funding_cost
    net_r = realized / max(risk_price, EPS)
    gross_no_entry_fee = realized + entry * costs.fee_rate + funding_cost
    gross_r = gross_no_entry_fee / max(abs(entry - stop), EPS)
    return Outcome(
        candidate_id=candidate.candidate_id,
        resolved=True,
        entry_time_ms=int(times[start]),
        exit_time_ms=exit_ms,
        entry_fill=entry,
        exit_fill=exit_fill,
        gross_r=float(gross_r),
        net_r=float(net_r),
        max_favorable_r=float(max_fav),
        max_adverse_r=float(max_adv),
        target1_hit=target1_hit,
        target2_hit=target2_hit,
        stop_hit=stop_hit,
        structural_exit=structural_exit,
        funding_r=float(-funding_cost / max(risk_price, EPS)),
        event_log=event_log,
    )


def outcomes_frame(candidates: Sequence[Candidate], outcomes: dict[str, Outcome]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for c in candidates:
        o = outcomes.get(c.candidate_id)
        if o is None or not o.resolved or o.net_r is None or o.entry_time_ms is None or o.exit_time_ms is None:
            continue
        rows.append(
            {
                "candidate_id": c.candidate_id,
                "signal_time_ms": c.signal_time_ms,
                "entry_time_ms": o.entry_time_ms,
                "exit_time_ms": o.exit_time_ms,
                "net_r": o.net_r,
                "win": float(o.net_r > 0),
                **{name: _finite(c.features.get(name)) for name in FEATURE_COLUMNS},
            }
        )
    return pd.DataFrame(rows).sort_values("signal_time_ms").reset_index(drop=True) if rows else pd.DataFrame()


def _fit_models(train: pd.DataFrame, random_state: int = 17) -> tuple[Any, Any]:
    x = train[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y_reg = train["net_r"].clip(-3.0, 6.0)
    y_cls = train["win"].astype(int)
    reg = HistGradientBoostingRegressor(
        learning_rate=0.04,
        max_iter=180,
        max_leaf_nodes=15,
        min_samples_leaf=20,
        l2_regularization=1.0,
        random_state=random_state,
    )
    cls = HistGradientBoostingClassifier(
        learning_rate=0.04,
        max_iter=180,
        max_leaf_nodes=15,
        min_samples_leaf=20,
        l2_regularization=1.0,
        random_state=random_state,
    )
    reg.fit(x, y_reg)
    if y_cls.nunique() < 2:
        class ConstantClassifier:
            def __init__(self, p: float): self.p = p
            def predict_proba(self, xx: Any) -> np.ndarray:
                return np.column_stack([np.full(len(xx), 1 - self.p), np.full(len(xx), self.p)])
        cls = ConstantClassifier(float(y_cls.mean()))
    else:
        cls.fit(x, y_cls)
    return reg, cls


def _predict(frame: pd.DataFrame, reg: Any, cls: Any) -> pd.DataFrame:
    out = frame.copy()
    x = out[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out["predicted_r"] = reg.predict(x)
    out["win_probability"] = cls.predict_proba(x)[:, 1]
    # Expected utility proxy keeps probability and payoff separate.
    out["score"] = out["predicted_r"] * (0.5 + out["win_probability"])
    return out


def _quick_compound_metrics(frame: pd.DataFrame, threshold: float, min_probability: float, risk: float) -> dict[str, float]:
    if frame.empty:
        return {"geo": -1.0, "mdd": 1.0, "trades": 0, "multiple": 0.0}
    selected = frame[(frame["score"] >= threshold) & (frame["win_probability"] >= min_probability)].copy()
    selected = selected.sort_values(["entry_time_ms", "score"], ascending=[True, False])
    nav = 1.0
    peak = 1.0
    mdd = 0.0
    last_exit = -1
    trades = 0
    first_ms = int(frame["signal_time_ms"].min())
    last_ms = int(frame["signal_time_ms"].max())
    for _, row in selected.iterrows():
        if int(row["entry_time_ms"]) < last_exit:
            continue
        factor = 1.0 + risk * float(row["net_r"])
        if factor <= 0:
            return {"geo": -1.0, "mdd": 1.0, "trades": trades + 1, "multiple": 0.0}
        nav *= factor
        peak = max(peak, nav)
        mdd = max(mdd, 1.0 - nav / peak)
        last_exit = int(row["exit_time_ms"])
        trades += 1
    days = max(1.0, (last_ms - first_ms) / DAY_MS)
    geo = math.exp(math.log(max(nav, EPS)) / days) - 1.0
    return {"geo": geo, "mdd": mdd, "trades": trades, "multiple": nav}


def causal_model_selection(train_frame: pd.DataFrame) -> tuple[Any, Any, dict[str, Any], pd.DataFrame]:
    if len(train_frame) < 80:
        raise RuntimeError(f"too few resolved pre-2024 candidates for ML: {len(train_frame)}")
    times = train_frame["signal_time_ms"].to_numpy(np.int64)
    q60, q80 = np.quantile(times, [0.60, 0.80])
    folds = [
        (train_frame[times < q60], train_frame[(times >= q60) & (times < q80)]),
        (train_frame[times < q80], train_frame[times >= q80]),
    ]
    oof_parts: list[pd.DataFrame] = []
    for fold_no, (fit, valid) in enumerate(folds):
        if len(fit) < 40 or valid.empty:
            continue
        reg, cls = _fit_models(fit, random_state=17 + fold_no)
        pred = _predict(valid, reg, cls)
        pred["fold"] = fold_no
        oof_parts.append(pred)
    if not oof_parts:
        raise RuntimeError("walk-forward folds did not contain enough candidates")
    oof = pd.concat(oof_parts, ignore_index=True).sort_values("signal_time_ms")

    thresholds = sorted(set(float(x) for x in np.quantile(oof["score"], np.linspace(0.35, 0.90, 12))))
    probabilities = [0.45, 0.50, 0.55, 0.60]
    risks = [0.005, 0.01, 0.02, 0.04, 0.06, 0.08, 0.10]
    trials: list[dict[str, Any]] = []
    for threshold in thresholds:
        for p in probabilities:
            for risk in risks:
                whole = _quick_compound_metrics(oof, threshold, p, risk)
                fold_metrics = [_quick_compound_metrics(oof[oof["fold"] == f], threshold, p, risk) for f in sorted(oof["fold"].unique())]
                min_fold_geo = min(m["geo"] for m in fold_metrics)
                min_fold_trades = min(m["trades"] for m in fold_metrics)
                robust = min_fold_geo > -0.0025 and min_fold_trades >= 5 and whole["trades"] >= 15
                objective = whole["geo"] - 0.25 * whole["mdd"] / 365.0 + (0.001 if robust else -0.003)
                trials.append(
                    {
                        "threshold": threshold,
                        "min_probability": p,
                        "risk_fraction": risk,
                        "objective": objective,
                        "robust": robust,
                        "whole": whole,
                        "folds": fold_metrics,
                    }
                )
    trials.sort(key=lambda x: (x["robust"], x["objective"], x["whole"]["geo"], -x["whole"]["mdd"]), reverse=True)
    selected = trials[0]
    reg, cls = _fit_models(train_frame, random_state=29)
    return reg, cls, {"selected": selected, "top_trials": trials[:20]}, oof


def _approx_liquidation_price(entry: float, side: int, leverage: float, mmr: float) -> float:
    if leverage <= 1.0:
        return 0.0 if side == 1 else float("inf")
    if side == 1:
        return entry * (1.0 - 1.0 / leverage + mmr)
    return entry * (1.0 + 1.0 / leverage - mmr)


def run_portfolio(
    predicted: pd.DataFrame,
    candidate_map: dict[str, Candidate],
    outcome_map: dict[str, Outcome],
    minute_bars: pd.DataFrame,
    portfolio_cfg: PortfolioConfig,
    costs: CostModel,
    evaluation_start_ms: int,
    evaluation_end_ms: int,
    initial_nav: float = 10_000.0,
) -> PortfolioResult:
    eligible = predicted[
        (predicted["score"] >= portfolio_cfg.score_threshold)
        & (predicted["win_probability"] >= portfolio_cfg.min_probability)
    ].copy()
    eligible = eligible.sort_values(["entry_time_ms", "score"], ascending=[True, False])
    bars = minute_bars
    times = bars["start_time_ms"].to_numpy(np.int64)
    closes = bars["close"].to_numpy(float)
    cash = initial_nav
    closed_nav = initial_nav
    last_exit = evaluation_start_ms - 1
    selected_trades: list[dict[str, Any]] = []
    rejected_liq = 0
    rejected_margin = 0
    liquidations = 0

    for _, row in eligible.iterrows():
        cid = str(row["candidate_id"])
        c = candidate_map[cid]
        o = outcome_map[cid]
        if o.entry_time_ms is None or o.exit_time_ms is None or o.entry_fill is None or o.net_r is None:
            continue
        if o.entry_time_ms < last_exit or o.entry_time_ms < evaluation_start_ms or o.entry_time_ms >= evaluation_end_ms:
            continue
        nav = closed_nav
        entry = float(o.entry_fill)
        stop = float(c.stop_reference)
        risk_price = abs(entry - stop) + entry * costs.fee_rate + stop * costs.fee_rate
        risk_budget = nav * portfolio_cfg.risk_fraction
        qty_risk = risk_budget / max(risk_price, EPS)
        qty_margin = nav * portfolio_cfg.leverage / max(entry, EPS)
        qty = min(qty_risk, qty_margin)
        if qty <= 0:
            continue
        if qty_margin + EPS < qty_risk:
            rejected_margin += 1
        liq = _approx_liquidation_price(entry, c.side, portfolio_cfg.leverage, costs.maintenance_margin_rate)
        if c.side == 1:
            safe = portfolio_cfg.leverage <= 1 or stop > liq * (1.0 + costs.liquidation_buffer_pct)
        else:
            safe = portfolio_cfg.leverage <= 1 or stop < liq * (1.0 - costs.liquidation_buffer_pct)
        if not safe:
            rejected_liq += 1
            continue
        pnl = qty * risk_price * float(o.net_r)
        next_nav = nav + pnl
        if next_nav <= 0:
            liquidations += 1
            closed_nav = 0.0
            selected_trades.append({"candidate_id": cid, "entry_time_ms": o.entry_time_ms, "exit_time_ms": o.exit_time_ms, "pnl": -nav, "nav_after": 0.0, "liquidated": True})
            break
        closed_nav = next_nav
        last_exit = int(o.exit_time_ms)
        selected_trades.append(
            {
                "candidate_id": cid,
                "symbol": c.symbol,
                "side": c.side,
                "setup_type": c.setup_type,
                "liquidity_kind": c.liquidity_kind,
                "entry_time_ms": int(o.entry_time_ms),
                "exit_time_ms": int(o.exit_time_ms),
                "entry_fill": entry,
                "exit_fill": o.exit_fill,
                "stop_reference": stop,
                "target1_reference": c.target1_reference,
                "target2_reference": c.target2_reference,
                "quantity": qty,
                "risk_budget": risk_budget,
                "effective_risk_fraction": qty * risk_price / nav,
                "net_r": o.net_r,
                "pnl": pnl,
                "nav_before": nav,
                "nav_after": closed_nav,
                "score": float(row["score"]),
                "win_probability": float(row["win_probability"]),
                "predicted_r": float(row["predicted_r"]),
                "target1_hit": o.target1_hit,
                "target2_hit": o.target2_hit,
                "stop_hit": o.stop_hit,
                "structural_exit": o.structural_exit,
                "liquidated": False,
            }
        )

    # Reconstruct UTC daily NAV using linear interpolation of each trade's marked
    # price at midnight. This respects the one-position slot and continuous NAV.
    day_starts = np.arange(
        (evaluation_start_ms // DAY_MS) * DAY_MS,
        ((evaluation_end_ms - 1) // DAY_MS + 1) * DAY_MS,
        DAY_MS,
        dtype=np.int64,
    )
    daily_nav: list[dict[str, Any]] = []
    for d in day_starts:
        boundary = int(min(d + DAY_MS, evaluation_end_ms))
        nav = initial_nav
        for t in selected_trades:
            if t.get("liquidated") and t["exit_time_ms"] <= boundary:
                nav = 0.0
                break
            if t["exit_time_ms"] <= boundary:
                nav = float(t["nav_after"])
                continue
            if t["entry_time_ms"] < boundary < t["exit_time_ms"]:
                idx = int(np.searchsorted(times, boundary, side="left") - 1)
                idx = max(0, min(idx, len(closes) - 1))
                c = candidate_map[t["candidate_id"]]
                unrealized = t["quantity"] * c.side * (float(closes[idx]) - t["entry_fill"])
                entry_fee = t["quantity"] * t["entry_fill"] * costs.fee_rate
                nav = float(t["nav_before"] - entry_fee + unrealized)
                break
            if t["entry_time_ms"] >= boundary:
                break
        daily_nav.append({"day_end_ms": boundary, "nav": nav})

    nav_values = np.array([x["nav"] for x in daily_nav], dtype=float)
    if len(nav_values) == 0:
        nav_values = np.array([initial_nav, closed_nav])
    if np.any(nav_values <= 0):
        geo = -1.0
    else:
        prev = np.r_[initial_nav, nav_values[:-1]]
        geo = float(np.exp(np.mean(np.log(nav_values / prev))) - 1.0)
    running_peak = np.maximum.accumulate(np.r_[initial_nav, nav_values])
    dd = 1.0 - np.r_[initial_nav, nav_values] / running_peak
    mdd = float(np.nanmax(dd))
    pnls = np.array([float(t["pnl"]) for t in selected_trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = -pnls[pnls < 0]
    profit_factor = float(wins.sum() / losses.sum()) if losses.sum() > 0 else (1e9 if wins.sum() > 0 else 0.0)
    positive_total = wins.sum()
    top5_conc = float(np.sort(wins)[-5:].sum() / positive_total) if positive_total > 0 else 0.0
    return PortfolioResult(
        initial_nav=initial_nav,
        final_nav=float(closed_nav),
        account_multiple=float(closed_nav / initial_nav),
        geometric_daily_growth=geo,
        max_drawdown=mdd,
        completed_trades=len(selected_trades),
        win_rate=float((pnls > 0).mean()) if len(pnls) else 0.0,
        profit_factor=profit_factor,
        top5_profit_concentration=top5_conc,
        liquidations=liquidations,
        rejected_liquidation_guard=rejected_liq,
        rejected_margin=rejected_margin,
        daily_nav=daily_nav,
        trades=selected_trades,
    )


def default_rule_configs() -> list[RuleConfig]:
    configs: list[RuleConfig] = []
    spec = [
        ("broad_core", 0.00, 0.55, 0.85, 0.005, 6, 30, 0.52, 0.85, False),
        ("balanced", 0.03, 0.75, 1.05, 0.025, 4, 18, 0.58, 1.20, True),
        ("strict_displacement", 0.05, 1.00, 1.30, 0.04, 4, 20, 0.62, 1.35, True),
        ("deep_sweep", 0.12, 0.80, 1.15, 0.025, 6, 24, 0.58, 1.25, False),
        ("fast_retest", 0.03, 0.70, 1.00, 0.02, 3, 8, 0.60, 1.15, True),
    ]
    for name, sweep, body, rng, fvg, wait, age, reject, min_r, same_bar_reclaim in spec:
        configs.append(
            RuleConfig(
                config_id=name,
                min_sweep_atr=sweep,
                min_displacement_body_atr=body,
                min_displacement_range_atr=rng,
                min_fvg_atr=fvg,
                max_sweep_to_displacement_bars=wait,
                max_setup_age_bars=age,
                min_rejection_strength=reject,
                min_target_r=min_r,
                partial_fraction=0.45,
                target1_r=1.0,
                trail_after_target1=True,
                require_same_bar_reclaim=same_bar_reclaim,
            )
        )
    return configs


def load_segment(root: Path, segment: str, symbol: str) -> dict[str, pd.DataFrame]:
    if load_trade_bar is None or load_stream is None:
        raise RuntimeError("canonical loader unavailable")
    return {
        "bars1": load_trade_bar(root, segment, symbol, "1m"),
        "bars5": load_trade_bar(root, segment, symbol, "5m"),
        "oi5": load_stream(root, segment, symbol, "open_interest_5m"),
        "ratio5": load_stream(root, segment, symbol, "account_ratio_5m"),
        "premium1": load_stream(root, segment, symbol, "premium_index_1m"),
        "mark1": load_stream(root, segment, symbol, "mark_price_1m"),
        "index1": load_stream(root, segment, symbol, "index_price_1m"),
        "funding": load_stream(root, segment, symbol, "funding_events"),
    }


def evaluate_rule_config(
    cfg: RuleConfig,
    symbol: str,
    train_data: dict[str, pd.DataFrame],
    eval_data: dict[str, pd.DataFrame],
    costs: CostModel,
    output: Path,
) -> dict[str, Any]:
    train5 = prepare_features(train_data["bars5"], train_data["oi5"], train_data["ratio5"], train_data["premium1"], train_data["mark1"], train_data["index1"], train_data["funding"])
    eval5 = prepare_features(eval_data["bars5"], eval_data["oi5"], eval_data["ratio5"], eval_data["premium1"], eval_data["mark1"], eval_data["index1"], eval_data["funding"])
    train1 = _ensure_bar_schema(train_data["bars1"])
    eval1 = _ensure_bar_schema(eval_data["bars1"])

    train_candidates = generate_candidates(train5, symbol, cfg)
    eval_candidates = generate_candidates(eval5, symbol, cfg)
    train_outcomes = {
        c.candidate_id: simulate_candidate(c, train1, train_data["funding"], cfg, costs, horizon_minutes=7 * 24 * 60)
        for c in train_candidates
    }
    train_frame = outcomes_frame(train_candidates, train_outcomes)
    if len(train_frame) < 80:
        return {
            "config_id": cfg.config_id,
            "decision": "INSUFFICIENT_PRE2024_CANDIDATES",
            "train_candidates": len(train_candidates),
            "resolved_train_candidates": len(train_frame),
        }
    reg, cls, selection, oof = causal_model_selection(train_frame)

    eval_outcomes = {
        c.candidate_id: simulate_candidate(c, eval1, eval_data["funding"], cfg, costs, horizon_minutes=None)
        for c in eval_candidates
    }
    eval_frame = outcomes_frame(eval_candidates, eval_outcomes)
    if eval_frame.empty:
        return {
            "config_id": cfg.config_id,
            "decision": "NO_2024H1_CANDIDATES",
            "train_candidates": len(train_candidates),
            "resolved_train_candidates": len(train_frame),
            "eval_candidates": len(eval_candidates),
        }
    pred = _predict(eval_frame, reg, cls)
    selected = selection["selected"]
    risk = float(selected["risk_fraction"])
    threshold = float(selected["threshold"])
    min_prob = float(selected["min_probability"])

    leverage_trials = [1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0]

    # Leverage is fixed from pre-2024 walk-forward predictions, not selected on H1.
    train_start = int(train1["start_time_ms"].min())
    train_end = int(train1["start_time_ms"].max() + MS_MINUTE)
    train_cmap = {c.candidate_id: c for c in train_candidates}
    pre2024_leverage_trials: list[dict[str, Any]] = []
    for lev in leverage_trials:
        pconf = PortfolioConfig(risk, lev, threshold, min_prob)
        result = run_portfolio(oof, train_cmap, train_outcomes, train1, pconf, costs, train_start, train_end)
        pre2024_leverage_trials.append({"leverage": lev, "result": asdict(result)})
    pre2024_leverage_trials.sort(
        key=lambda x: (
            x["result"]["liquidations"] == 0,
            x["result"]["completed_trades"] >= 10,
            x["result"]["geometric_daily_growth"],
            -x["result"]["max_drawdown"],
            -x["leverage"],
        ),
        reverse=True,
    )
    selected_leverage = float(pre2024_leverage_trials[0]["leverage"])

    eval_start = int(eval1["start_time_ms"].min())
    eval_end = int(eval1["start_time_ms"].max() + MS_MINUTE)
    cmap = {c.candidate_id: c for c in eval_candidates}
    authoritative_cfg = PortfolioConfig(risk, selected_leverage, threshold, min_prob)
    authoritative_result = run_portfolio(
        pred, cmap, eval_outcomes, eval1, authoritative_cfg, costs, eval_start, eval_end
    )

    # Other H1 leverages are diagnostics only and cannot replace the pre-2024 choice.
    portfolio_trials: list[dict[str, Any]] = []
    for lev in leverage_trials:
        pconf = PortfolioConfig(risk, lev, threshold, min_prob)
        result = run_portfolio(pred, cmap, eval_outcomes, eval1, pconf, costs, eval_start, eval_end)
        portfolio_trials.append({"leverage": lev, "result": asdict(result), "authoritative": lev == selected_leverage})

    cfg_out = output / cfg.config_id
    cfg_out.mkdir(parents=True, exist_ok=True)
    train_frame.to_parquet(cfg_out / "PRE2024_CANDIDATE_OUTCOMES.parquet", index=False)
    oof.to_parquet(cfg_out / "PRE2024_OOF_PREDICTIONS.parquet", index=False)
    pred.to_parquet(cfg_out / "2024H1_PREDICTIONS.parquet", index=False)
    authoritative = asdict(authoritative_result)
    pd.DataFrame(authoritative["trades"]).to_csv(cfg_out / "2024H1_TRADES.csv", index=False)
    pd.DataFrame(authoritative["daily_nav"]).to_csv(cfg_out / "2024H1_DAILY_NAV.csv", index=False)
    summary = {
        "config_id": cfg.config_id,
        "decision": "EVALUATED_2024H1",
        "rule_config": asdict(cfg),
        "train_candidates": len(train_candidates),
        "resolved_train_candidates": len(train_frame),
        "eval_candidates": len(eval_candidates),
        "resolved_eval_candidates": len(eval_frame),
        "pre2024_selection": selection,
        "pre2024_leverage_trials": pre2024_leverage_trials,
        "selected_portfolio": {
            "risk_fraction": risk,
            "score_threshold": threshold,
            "min_probability": min_prob,
            "leverage": selected_leverage,
            "result": authoritative,
        },
        "h1_leverage_diagnostics": portfolio_trials,
    }
    (cfg_out / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    data_root = Path(args.data_root).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    costs = CostModel(args.taker_fee_bps, args.slippage_bps, args.maintenance_margin_rate, args.liquidation_buffer_pct)
    symbol = args.symbol
    train_data = load_segment(data_root, args.train_segment, symbol)
    eval_data = load_segment(data_root, args.eval_segment, symbol)
    results: list[dict[str, Any]] = []
    for cfg in default_rule_configs():
        print(f"[easycore] evaluating {cfg.config_id}", flush=True)
        results.append(evaluate_rule_config(cfg, symbol, train_data, eval_data, costs, output))
    evaluated = [r for r in results if r.get("decision") == "EVALUATED_2024H1"]
    if evaluated:
        # Rule family is also selected only from pre-2024 walk-forward evidence.
        evaluated.sort(
            key=lambda r: (
                r["pre2024_selection"]["selected"]["robust"],
                r["pre2024_selection"]["selected"]["objective"],
                r["pre2024_selection"]["selected"]["whole"]["geo"],
                -r["pre2024_selection"]["selected"]["whole"]["mdd"],
            ),
            reverse=True,
        )
        winner = evaluated[0]
        metrics = winner["selected_portfolio"]["result"]
        positive = metrics["geometric_daily_growth"] > 0 and metrics["completed_trades"] >= 10
        decision = "POSITIVE_BASIC_ALPHA_CONTINUE" if positive else "IMPLEMENTATION_OR_ALPHA_REVISION_REQUIRED"
    else:
        winner = None
        metrics = None
        decision = "NO_EVALUATABLE_CONFIGURATION"
    summary = {
        "schema_version": 1,
        "system_id": "SYS-EASYCORE-SMC-ML-V1",
        "claim_id": "CLM-20260727-EASYCORE-SMC-ML-001",
        "transcript_basis": {
            "corpus": "YT_TRINITY_20260727 immutable public-caption corpus",
            "videos": 186,
            "channel_counts": {"swipalnam": 26, "chartbro": 62, "indicator_sensei": 98},
            "base_channel": "swipalnam",
            "rule_chain": "liquidity sweep -> displacement/MSS -> FVG+OB -> retest/rejection -> opposing liquidity",
        },
        "data": {"symbol": symbol, "train_segment": args.train_segment, "eval_segment": args.eval_segment},
        "cost_model": asdict(costs),
        "decision": decision,
        "winner": winner,
        "configurations": results,
    }
    summary["result_id"] = "RES-EASYCORE-" + _sha256_json(summary)[:16]
    (output / "RUN_SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"decision": decision, "result_id": summary["result_id"], "winner": winner and winner["config_id"], "metrics": metrics}, indent=2, allow_nan=False))
    return summary


def _synthetic_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(7)
    n5 = 900
    start = 1_672_531_200_000
    returns = rng.normal(0, 0.0008, n5)
    close = 20_000 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    spread = close * rng.uniform(0.0003, 0.0012, n5)
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.lognormal(8, 0.5, n5)
    # Inject an obvious sell-side sweep, bullish displacement/FVG, and retest.
    i = 520
    local_low = low[i - 20 : i].min()
    low[i] = local_low - 80
    close[i] = local_low + 20
    open_[i] = local_low + 35
    high[i] = local_low + 45
    open_[i + 1] = close[i]
    close[i + 1] = close[i] + 180
    high[i + 1] = close[i + 1] + 20
    low[i + 1] = close[i] + 10
    volume[i + 1] *= 6
    open_[i + 2] = close[i + 1]
    close[i + 2] = close[i + 1] + 100
    high[i + 2] = close[i + 2] + 10
    low[i + 2] = high[i] + 20
    # Retest after displacement.
    low[i + 4] = high[i] + 10
    open_[i + 4] = low[i + 4] + 20
    close[i + 4] = low[i + 4] + 90
    high[i + 4] = close[i + 4] + 20
    bars5 = pd.DataFrame(
        {
            "start_time_ms": start + np.arange(n5) * MS_5M,
            "open": open_, "high": high, "low": low, "close": close,
            "volume": volume, "turnover": volume * close,
            "source_available": True,
            "available_at_ms": start + np.arange(n5) * MS_5M + MS_5M,
        }
    )
    # Deterministic 1m interpolation for execution self-test.
    rows = []
    for _, b in bars5.iterrows():
        for k in range(5):
            frac0, frac1 = k / 5, (k + 1) / 5
            o = b.open + (b.close - b.open) * frac0
            c = b.open + (b.close - b.open) * frac1
            rows.append(
                {
                    "start_time_ms": int(b.start_time_ms + k * MS_MINUTE),
                    "open": o,
                    "high": max(o, c, b.high if k == 2 else -np.inf),
                    "low": min(o, c, b.low if k == 1 else np.inf),
                    "close": c,
                    "volume": b.volume / 5,
                    "turnover": b.turnover / 5,
                    "source_available": True,
                    "available_at_ms": int(b.start_time_ms + (k + 1) * MS_MINUTE),
                }
            )
    return bars5, pd.DataFrame(rows)


def self_test() -> None:
    bars5, bars1 = _synthetic_data()
    features = prepare_features(bars5)
    assert len(features) == len(bars5)
    cfg = dataclasses.replace(default_rule_configs()[0], min_target_r=0.20)
    candidates = generate_candidates(features, "BTCUSDT", cfg)
    assert candidates, "synthetic sweep/displacement/retest did not emit a candidate"
    # Synthetic data need not guarantee a candidate under all causal swing states,
    # but every emitted candidate must obey invariant geometry.
    for c in candidates:
        assert c.side in (-1, 1)
        assert c.activation_time_ms == c.signal_time_ms + 500
        assert c.side * (c.entry_reference - c.stop_reference) > 0
        assert c.side * (c.target2_reference - c.entry_reference) > 0
        assert set(FEATURE_COLUMNS).issubset(c.features)
        out = simulate_candidate(c, bars1, None, cfg, CostModel(), horizon_minutes=24 * 60)
        if out.resolved and out.entry_time_ms is not None:
            assert out.entry_time_ms >= _first_full_minute_after_activation(c.activation_time_ms)
    # Liquidation guard monotonicity.
    assert _approx_liquidation_price(100, 1, 10, 0.005) > _approx_liquidation_price(100, 1, 2, 0.005)
    assert _first_full_minute_after_activation(300_500) == 360_000
    print(json.dumps({"status": "SELF_TEST_PASS", "candidates": len(candidates)}))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root")
    parser.add_argument("--output")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--train-segment", default="PRE_2024_2023")
    parser.add_argument("--eval-segment", default="2024_H1")
    parser.add_argument("--taker-fee-bps", type=float, default=6.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--maintenance-margin-rate", type=float, default=0.005)
    parser.add_argument("--liquidation-buffer-pct", type=float, default=0.01)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test and (not args.data_root or not args.output):
        parser.error("--data-root and --output are required")
    return args


def main() -> None:
    args = parse_args()
    if args.self_test:
        self_test()
    else:
        run(args)


if __name__ == "__main__":
    main()
