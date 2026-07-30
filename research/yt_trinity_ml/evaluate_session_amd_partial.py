#!/usr/bin/env python3
"""Causal coarse-lane evaluation for the YT Trinity session AMD/PO3 system.

The evaluator consumes immutable canonical Bybit shards, verifies every manifest and
referenced file hash, derives only backward-looking features, trains a three-head
model with chronological calibration, and replays one global pending/open slot.

This is the one-minute economic lane. A survivor still requires the separate Bybit
event-tape lane before Result Registry insertion or deployment approval.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import platform
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge

MS_MINUTE = 60_000
MS_5M = 5 * MS_MINUTE
UTC = timezone.utc
NY = ZoneInfo("America/New_York")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")

DEFAULT_CONTRACT: dict[str, Any] = {
    "schema_version": 1,
    "system_id": "YTTRI-SESSION-AMD-PARTIAL-ML-V1",
    "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
    "corpus": {
        "public_video_count": 186,
        "channel_counts": {"swipalnam": 26, "chartbro": 62, "indicator_sensei": 98},
        "youtube2text_count": 179,
        "transcribeyoutube_retry_count": 7,
        "merged_corpus_sha256": "db4d48691562f68c7b53c7b12fad88eeeb101fafd9bdb81a7a891bb3a32ad00",
        "videos_sha256": "73a5a2d028dd8a31fef7afab9f25e15b456877f4d8e0e3a0db63cca149a470ff",
    },
    "evaluation": {
        "training_segment": "PRE_2024_2023",
        "official_segment": "2024_H1",
        "start_nav": 10000.0,
        "start_utc": "2024-01-01T00:00:00Z",
        "end_exclusive_utc": "2024-07-01T00:00:00Z",
        "new_order_activation_delay_ms": 500,
        "one_global_slot": True,
        "no_elapsed_time_exit": True,
    },
    "alpha": {
        "timezone": "America/New_York",
        "asia": ["20:00", "00:00"],
        "london": ["02:00", "05:00"],
        "ny_am": ["07:00", "10:00"],
        "references": {
            "london": ["asia", "previous_day"],
            "ny_am": ["london", "previous_day"],
        },
        "atr_period": 14,
        "sweep_buffer_atr": 0.05,
        "stop_buffer_atr": 0.05,
        "confirmation_bars": 6,
        "mss_pivot_lookback_bars": 3,
        "minimum_displacement_body_atr": 0.20,
        "minimum_displacement_range_atr": 0.45,
        "long_close_location_min": 0.62,
        "short_close_location_max": 0.38,
        "passive_queue_penetration_bps": 0.5,
        "tp1_fraction": 0.50,
        "tp1": "reference_range_midpoint",
        "final_target": "opposite_reference_liquidity",
        "after_tp1_stop": "entry_price",
        "pending_cancel": "structural_invalidation_or_target_only",
    },
    "model": {
        "heads": ["target_before_invalidation_probability", "net_r_expectation", "passive_fill_probability"],
        "base_calibration_days": 90,
        "initial_active_at_utc": "2024-01-01T00:00:00Z",
        "monthly_update_at_utc": "first_calendar_day_00:10",
        "minimum_base_rows": 300,
        "minimum_calibration_rows": 80,
        "minimum_passive_fill_rows": 100,
        "eligibility": {"minimum_win_probability": 0.50, "minimum_expected_net_r": 0.0, "minimum_passive_fill_probability": 0.25},
        "estimator": {
            "learning_rate": 0.05,
            "max_iter": 180,
            "max_leaf_nodes": 7,
            "min_samples_leaf": 25,
            "l2_regularization": 2.0,
            "random_state": 41,
        },
    },
    "risk": {
        "risk_fraction": 0.015,
        "max_leverage": 50.0,
        "maintenance_margin_fraction": 0.005,
        "liquidation_buffer_fraction": 0.0025,
        "quantity_rules": {
            "BTCUSDT": {"step": 0.001, "minimum": 0.001},
            "ETHUSDT": {"step": 0.01, "minimum": 0.01},
            "SOLUSDT": {"step": 0.1, "minimum": 0.1},
            "XRPUSDT": {"step": 1.0, "minimum": 1.0},
        },
    },
    "costs": {
        "base": {
            "market_entry_effective_bps": 7.5,
            "passive_entry_effective_bps": 2.0,
            "taker_exit_effective_bps": 7.5,
            "description": "VIP0 fees plus fixed coarse-lane spread/slippage; 15bp market round trip and 9.5bp passive-entry/taker-exit before funding",
        },
        "stress": {
            "market_entry_effective_bps": 12.0,
            "passive_entry_effective_bps": 8.0,
            "taker_exit_effective_bps": 12.0,
            "description": "24bp market and 20bp passive/taker all-in stress before funding",
        },
    },
}


@dataclass(frozen=True)
class PricePath:
    event_id: str
    action: str
    side: int
    decision_time_ms: int
    active_time_ms: int
    slot_end_time_ms: int
    status: str
    entry_time_ms: int | None
    entry_price: float | None
    stop_price: float
    tp1_price: float
    target_price: float
    tp1_time_ms: int | None
    exit_time_ms: int | None
    exit_price: float | None
    exit_reason: str | None
    legs: tuple[tuple[int, float, float, str], ...]


@dataclass
class ModelBundle:
    active_at_ms: int
    training_cutoff_ms: int
    base_rows: int
    calibration_rows: int
    feature_names: list[str]
    win_model: Any
    r_model: Any
    fill_model: Any
    win_calibrator: Any
    r_calibrator: Any
    fill_calibrator: Any
    constants: dict[str, float] = field(default_factory=dict)


@dataclass
class ConstantProbability:
    probability: float

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        p = np.full(len(x), np.clip(self.probability, 1e-6, 1 - 1e-6), dtype=float)
        return np.column_stack([1.0 - p, p])


@dataclass
class ConstantRegression:
    value: float

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.full(len(x), self.value, dtype=float)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default)


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    raise TypeError(f"cannot JSON encode {type(value).__name__}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_ms(value: str | pd.Timestamp | datetime) -> int:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return int(stamp.value // 1_000_000)


def iso_ms(value: int | None) -> str | None:
    if value is None:
        return None
    return pd.Timestamp(value, unit="ms", tz="UTC").isoformat().replace("+00:00", "Z")


def floor_step(value: float, step: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 0.0
    return math.floor((value + 1e-12) / step) * step


def find_shards(root: Path) -> dict[tuple[str, str], Path]:
    shards: dict[tuple[str, str], Path] = {}
    for path in root.rglob("DATASET_MANIFEST.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        key = (str(manifest.get("physical_segment")), str(manifest.get("symbol")))
        if key[0] and key[1] and key[1] in SYMBOLS:
            if key in shards:
                raise RuntimeError(f"duplicate canonical shard for {key}: {shards[key]} and {path.parent}")
            expected = (path.parent / "DATASET_MANIFEST.sha256").read_text(encoding="utf-8").split()[0]
            actual = sha256_file(path)
            if actual != expected:
                raise RuntimeError(f"manifest hash mismatch: {path}")
            for item in manifest.get("files", []):
                target = path.parent / item["path"]
                if not target.is_file():
                    raise FileNotFoundError(target)
                if sha256_file(target) != item["sha256"]:
                    raise RuntimeError(f"canonical file hash mismatch: {target}")
            shards[key] = path.parent
    return shards


def load_named(shard: Path, kind: str, name: str) -> pd.DataFrame:
    manifest = json.loads((shard / "DATASET_MANIFEST.json").read_text(encoding="utf-8"))
    matches = [item for item in manifest["files"] if item["kind"] == kind and item["name"] == name]
    if len(matches) != 1:
        raise KeyError(f"expected one {kind}/{name} in {shard}; got {len(matches)}")
    return pd.read_parquet(shard / matches[0]["path"], engine="pyarrow")


def concat_named(shards: Mapping[tuple[str, str], Path], symbol: str, kind: str, name: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for segment in ("PRE_2024_2023", "2024_H1"):
        key = (segment, symbol)
        if key not in shards:
            raise KeyError(f"missing canonical shard {key}")
        frame = load_named(shards[key], kind, name).copy()
        frame["physical_segment"] = segment
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    time_col = "start_time_ms" if "start_time_ms" in out.columns else "timestamp_ms"
    out = out.sort_values(time_col).drop_duplicates(time_col, keep="last").reset_index(drop=True)
    return out


def safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = safe_div(up, down)
    return 100 - (100 / (1 + rs))


def prepare_symbol_data(shards: Mapping[tuple[str, str], Path], symbol: str) -> dict[str, pd.DataFrame]:
    minute = concat_named(shards, symbol, "trade_bar", "1m")
    five = concat_named(shards, symbol, "trade_bar", "5m")
    hour = concat_named(shards, symbol, "trade_bar", "1h")
    mark = concat_named(shards, symbol, "stream", "mark_price_1m")
    premium = concat_named(shards, symbol, "stream", "premium_index_1m")
    oi = concat_named(shards, symbol, "stream", "open_interest_5m")
    ratio = concat_named(shards, symbol, "stream", "account_ratio_5m")
    funding = concat_named(shards, symbol, "stream", "funding_events")

    for frame in (minute, five, hour):
        complete_col = "is_complete" if "is_complete" in frame.columns else "observed"
        frame["valid"] = frame[complete_col].fillna(False).astype(bool)
        for col in ("open", "high", "low", "close", "volume", "turnover"):
            if col in frame:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
    minute = minute.sort_values("start_time_ms").reset_index(drop=True)
    five = five.sort_values("start_time_ms").reset_index(drop=True)
    hour = hour.sort_values("start_time_ms").reset_index(drop=True)
    mark = mark.sort_values("start_time_ms").reset_index(drop=True)
    funding = funding.sort_values("timestamp_ms").reset_index(drop=True)

    prev_close = five["close"].shift(1)
    tr = pd.concat(
        [(five["high"] - five["low"]), (five["high"] - prev_close).abs(), (five["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    five["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    five["bar_range"] = five["high"] - five["low"]
    five["body"] = five["close"] - five["open"]
    five["body_abs_atr"] = safe_div(five["body"].abs(), five["atr"])
    five["range_atr"] = safe_div(five["bar_range"], five["atr"])
    five["close_location"] = safe_div(five["close"] - five["low"], five["bar_range"])
    five["upper_wick_atr"] = safe_div(five["high"] - five[["open", "close"]].max(axis=1), five["atr"])
    five["lower_wick_atr"] = safe_div(five[["open", "close"]].min(axis=1) - five["low"], five["atr"])
    five["ema9"] = five["close"].ewm(span=9, adjust=False, min_periods=9).mean()
    five["ema21"] = five["close"].ewm(span=21, adjust=False, min_periods=21).mean()
    five["ema50"] = five["close"].ewm(span=50, adjust=False, min_periods=50).mean()
    five["ema9_21_atr"] = safe_div(five["ema9"] - five["ema21"], five["atr"])
    five["ema21_50_atr"] = safe_div(five["ema21"] - five["ema50"], five["atr"])
    five["ema21_slope_atr"] = safe_div(five["ema21"].diff(3), five["atr"])
    five["rsi14"] = rsi(five["close"], 14) / 100.0
    ema12 = five["close"].ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = five["close"].ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    five["macd_hist_atr"] = safe_div(macd - macd.ewm(span=9, adjust=False, min_periods=9).mean(), five["atr"])
    mean20 = five["close"].rolling(20, min_periods=20).mean()
    std20 = five["close"].rolling(20, min_periods=20).std(ddof=0)
    five["bb_width_atr"] = safe_div(4 * std20, five["atr"])
    five["atr_ratio_1d"] = safe_div(five["atr"], five["atr"].rolling(288, min_periods=96).median())
    volume_log = np.log1p(five["volume"].clip(lower=0))
    five["volume_z48"] = safe_div(volume_log - volume_log.rolling(48, min_periods=24).mean(), volume_log.rolling(48, min_periods=24).std(ddof=0))
    five["turnover_z48"] = safe_div(
        np.log1p(five["turnover"].clip(lower=0)) - np.log1p(five["turnover"].clip(lower=0)).rolling(48, min_periods=24).mean(),
        np.log1p(five["turnover"].clip(lower=0)).rolling(48, min_periods=24).std(ddof=0),
    )
    five["return_1"] = five["close"].pct_change()
    five["return_3"] = five["close"].pct_change(3)
    five["return_12"] = five["close"].pct_change(12)

    five["utc_dt"] = pd.to_datetime(five["start_time_ms"], unit="ms", utc=True)
    five["ny_dt"] = five["utc_dt"].dt.tz_convert(NY)
    five["ny_hour_float"] = five["ny_dt"].dt.hour + five["ny_dt"].dt.minute / 60.0
    five["time_sin"] = np.sin(2 * np.pi * five["ny_hour_float"] / 24.0)
    five["time_cos"] = np.cos(2 * np.pi * five["ny_hour_float"] / 24.0)
    utc_day = five["utc_dt"].dt.floor("D")
    cumulative_volume = five["volume"].where(five["valid"]).groupby(utc_day).cumsum()
    cumulative_turnover = five["turnover"].where(five["valid"]).groupby(utc_day).cumsum()
    five["utc_day_vwap"] = safe_div(cumulative_turnover, cumulative_volume)
    five["vwap_distance_atr"] = safe_div(five["close"] - five["utc_day_vwap"], five["atr"])

    hour_prev = hour["close"].shift(1)
    hour_tr = pd.concat(
        [(hour["high"] - hour["low"]), (hour["high"] - hour_prev).abs(), (hour["low"] - hour_prev).abs()], axis=1
    ).max(axis=1)
    hour["h1_atr"] = hour_tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    hour["h1_ema20"] = hour["close"].ewm(span=20, adjust=False, min_periods=20).mean()
    hour["h1_ema50"] = hour["close"].ewm(span=50, adjust=False, min_periods=50).mean()
    hour["h1_trend_atr"] = safe_div(hour["h1_ema20"] - hour["h1_ema50"], hour["h1_atr"])
    hour["h1_return_6"] = hour["close"].pct_change(6)
    hour_context = hour[["available_at_ms", "h1_trend_atr", "h1_return_6"]].sort_values("available_at_ms")

    def asof_context(base: pd.DataFrame, context: pd.DataFrame, columns: Sequence[str], prefix: str = "") -> pd.DataFrame:
        right = context[["available_at_ms", *columns]].copy().sort_values("available_at_ms")
        if prefix:
            right = right.rename(columns={name: f"{prefix}{name}" for name in columns})
        return pd.merge_asof(base.sort_values("available_at_ms"), right, on="available_at_ms", direction="backward")

    five = asof_context(five, hour_context, ["h1_trend_atr", "h1_return_6"])

    oi = oi.copy()
    oi["oi_log_change_12"] = np.log(oi["open_interest"].replace(0, np.nan)).diff(12)
    five = asof_context(five, oi, ["open_interest", "oi_log_change_12"], "oi_")
    ratio = ratio.copy()
    ratio["account_imbalance"] = ratio["buy_ratio"] - ratio["sell_ratio"]
    five = asof_context(five, ratio, ["buy_ratio", "sell_ratio", "account_imbalance"], "ratio_")
    premium = premium.copy()
    premium["premium_close"] = premium["close"]
    five = asof_context(five, premium, ["premium_close"], "premium_")

    minute["utc_dt"] = pd.to_datetime(minute["start_time_ms"], unit="ms", utc=True)
    mark["utc_dt"] = pd.to_datetime(mark["start_time_ms"], unit="ms", utc=True)
    return {"minute": minute, "five": five, "mark": mark, "funding": funding}


def local_session_date(stamp: pd.Timestamp) -> date:
    local = stamp.tz_convert(NY)
    d = local.date()
    if local.hour >= 20:
        return d + timedelta(days=1)
    return d


def build_ranges(five: pd.DataFrame) -> dict[str, dict[date, dict[str, float]]]:
    ranges: dict[str, dict[date, dict[str, float]]] = {"asia": {}, "london": {}, "ny_am": {}, "previous_day": {}}
    valid = five[five["valid"] & five[["open", "high", "low", "close"]].notna().all(axis=1)].copy()
    valid["local_date"] = valid["ny_dt"].dt.date
    valid["session_date"] = [local_session_date(stamp) for stamp in valid["utc_dt"]]
    hour = valid["ny_dt"].dt.hour

    masks = {
        "asia": hour >= 20,
        "london": (hour >= 2) & (hour < 5),
        "ny_am": (hour >= 7) & (hour < 10),
    }
    for name, mask in masks.items():
        selected = valid[mask]
        for key, group in selected.groupby("session_date", sort=True):
            ranges[name][key] = {
                "high": float(group["high"].max()),
                "low": float(group["low"].min()),
                "mid": float((group["high"].max() + group["low"].min()) / 2),
                "start_time_ms": int(group["start_time_ms"].iloc[0]),
                "end_time_ms": int(group["start_time_ms"].iloc[-1] + MS_5M),
            }
    for key, group in valid.groupby("local_date", sort=True):
        ranges["previous_day"][key + timedelta(days=1)] = {
            "high": float(group["high"].max()),
            "low": float(group["low"].min()),
            "mid": float((group["high"].max() + group["low"].min()) / 2),
            "start_time_ms": int(group["start_time_ms"].iloc[0]),
            "end_time_ms": int(group["start_time_ms"].iloc[-1] + MS_5M),
        }
    return ranges


def event_feature_columns() -> list[str]:
    return [
        "sweep_depth_atr", "stop_distance_atr", "target_distance_atr", "tp1_distance_atr",
        "reference_range_atr", "displacement_body_atr", "displacement_range_atr",
        "displacement_close_location", "displacement_gap_atr", "bars_to_confirmation",
        "volume_z48", "turnover_z48", "ema9_21_atr", "ema21_50_atr", "ema21_slope_atr",
        "rsi14", "macd_hist_atr", "bb_width_atr", "atr_ratio_1d", "return_1", "return_3",
        "return_12", "vwap_distance_atr", "h1_trend_atr", "h1_return_6",
        "oi_oi_log_change_12", "ratio_account_imbalance", "premium_premium_close",
        "time_sin", "time_cos", "upper_wick_atr", "lower_wick_atr", "range_atr",
        "body_abs_atr", "side_trend_alignment", "side_vwap_alignment", "side_momentum_alignment",
    ]


def generate_events(symbol: str, five: pd.DataFrame, contract: Mapping[str, Any]) -> pd.DataFrame:
    cfg = contract["alpha"]
    ranges = build_ranges(five)
    rows: list[dict[str, Any]] = []
    valid_dates = sorted(set(ranges["previous_day"]) | set(ranges["asia"]) | set(ranges["london"]))
    five_index = five.reset_index(drop=True)
    local_hours = five_index["ny_dt"].dt.hour
    session_dates = pd.Series([local_session_date(stamp) for stamp in five_index["utc_dt"]], index=five_index.index)

    for session_date in valid_dates:
        for target_session, hour_start, hour_end in (("london", 2, 5), ("ny_am", 7, 10)):
            references = cfg["references"][target_session]
            mask = (session_dates == session_date) & (local_hours >= hour_start) & (local_hours < hour_end)
            indices = five_index.index[mask].tolist()
            if not indices:
                continue
            used: set[tuple[str, int]] = set()
            for ref_name in references:
                ref = ranges.get(ref_name, {}).get(session_date)
                if not ref or not np.isfinite(ref["high"]) or not np.isfinite(ref["low"]) or ref["high"] <= ref["low"]:
                    continue
                for idx in indices:
                    bar = five_index.loc[idx]
                    atr = float(bar.get("atr", np.nan))
                    if not bool(bar.get("valid")) or not np.isfinite(atr) or atr <= 0:
                        continue
                    candidates: list[tuple[int, float, float]] = []
                    if float(bar["low"]) <= ref["low"] - cfg["sweep_buffer_atr"] * atr and float(bar["close"]) > ref["low"]:
                        candidates.append((1, float(bar["low"]), ref["low"]))
                    if float(bar["high"]) >= ref["high"] + cfg["sweep_buffer_atr"] * atr and float(bar["close"]) < ref["high"]:
                        candidates.append((-1, float(bar["high"]), ref["high"]))
                    for side, sweep_extreme, swept_level in candidates:
                        if (ref_name, side) in used:
                            continue
                        lookback_start = max(0, idx - int(cfg["mss_pivot_lookback_bars"]))
                        prior = five_index.loc[lookback_start:idx - 1]
                        if prior.empty or not prior["valid"].all():
                            continue
                        mss_level = float(prior["high"].max() if side == 1 else prior["low"].min())
                        confirmation_idx: int | None = None
                        for j in range(idx + 1, min(len(five_index), idx + 1 + int(cfg["confirmation_bars"]))):
                            cbar = five_index.loc[j]
                            if not bool(cbar.get("valid")):
                                break
                            catr = float(cbar.get("atr", np.nan))
                            if not np.isfinite(catr) or catr <= 0:
                                continue
                            body = float(cbar["close"] - cbar["open"])
                            bar_range = float(cbar["high"] - cbar["low"])
                            close_location = float((cbar["close"] - cbar["low"]) / bar_range) if bar_range > 0 else 0.5
                            displaced = (
                                side == 1
                                and float(cbar["close"]) > mss_level
                                and body >= cfg["minimum_displacement_body_atr"] * catr
                                and bar_range >= cfg["minimum_displacement_range_atr"] * catr
                                and close_location >= cfg["long_close_location_min"]
                            ) or (
                                side == -1
                                and float(cbar["close"]) < mss_level
                                and -body >= cfg["minimum_displacement_body_atr"] * catr
                                and bar_range >= cfg["minimum_displacement_range_atr"] * catr
                                and close_location <= cfg["short_close_location_max"]
                            )
                            if displaced:
                                confirmation_idx = j
                                break
                        if confirmation_idx is None:
                            continue
                        cbar = five_index.loc[confirmation_idx]
                        catr = float(cbar["atr"])
                        stop = sweep_extreme - side * cfg["stop_buffer_atr"] * atr
                        tp1 = float(ref["mid"])
                        target = float(ref["high"] if side == 1 else ref["low"])
                        entry_estimate = float(cbar["close"])
                        if not (stop < entry_estimate < tp1 < target) if side == 1 else not (target < tp1 < entry_estimate < stop):
                            continue
                        gap_atr = 0.0
                        if confirmation_idx >= 2:
                            two_back = five_index.loc[confirmation_idx - 2]
                            if side == 1:
                                gap_atr = max(0.0, float(cbar["low"] - two_back["high"]) / catr)
                            else:
                                gap_atr = max(0.0, float(two_back["low"] - cbar["high"]) / catr)
                        event_id = f"{symbol}:{session_date.isoformat()}:{target_session}:{ref_name}:{'L' if side == 1 else 'S'}:{int(bar['start_time_ms'])}"
                        row: dict[str, Any] = {
                            "event_id": event_id,
                            "symbol": symbol,
                            "session_date": session_date.isoformat(),
                            "target_session": target_session,
                            "reference": ref_name,
                            "side": side,
                            "sweep_time_ms": int(bar["start_time_ms"]),
                            "confirmation_time_ms": int(cbar["start_time_ms"]),
                            "decision_time_ms": int(cbar["available_at_ms"]),
                            "sweep_extreme": sweep_extreme,
                            "swept_level": swept_level,
                            "stop_price": float(stop),
                            "tp1_price": tp1,
                            "target_price": target,
                            "passive_limit_price": float((cbar["open"] + cbar["close"]) / 2.0),
                            "atr": catr,
                            "sweep_depth_atr": float(abs(sweep_extreme - swept_level) / atr),
                            "stop_distance_atr": float(abs(entry_estimate - stop) / catr),
                            "target_distance_atr": float(abs(target - entry_estimate) / catr),
                            "tp1_distance_atr": float(abs(tp1 - entry_estimate) / catr),
                            "reference_range_atr": float((ref["high"] - ref["low"]) / catr),
                            "displacement_body_atr": float(abs(cbar["close"] - cbar["open"]) / catr),
                            "displacement_range_atr": float((cbar["high"] - cbar["low"]) / catr),
                            "displacement_close_location": float(cbar["close_location"]),
                            "displacement_gap_atr": gap_atr,
                            "bars_to_confirmation": confirmation_idx - idx,
                        }
                        for name in event_feature_columns():
                            if name in row:
                                continue
                            row[name] = float(cbar.get(name, np.nan)) if name in cbar else np.nan
                        row["side_trend_alignment"] = side * float(cbar.get("ema21_50_atr", np.nan))
                        row["side_vwap_alignment"] = side * float(cbar.get("vwap_distance_atr", np.nan))
                        row["side_momentum_alignment"] = side * float(cbar.get("macd_hist_atr", np.nan))
                        rows.append(row)
                        used.add((ref_name, side))
    events = pd.DataFrame(rows)
    if events.empty:
        return events
    events = events.sort_values(["decision_time_ms", "symbol", "event_id"]).drop_duplicates("event_id").reset_index(drop=True)
    return events


def next_minute_index(times: np.ndarray, active_time_ms: int) -> int:
    earliest = ((active_time_ms // MS_MINUTE) + 1) * MS_MINUTE
    return int(np.searchsorted(times, earliest, side="left"))


def simulate_path(event: Mapping[str, Any], action: str, minute: pd.DataFrame, contract: Mapping[str, Any]) -> PricePath:
    side = int(event["side"])
    stop = float(event["stop_price"])
    tp1 = float(event["tp1_price"])
    target = float(event["target_price"])
    decision = int(event["decision_time_ms"])
    active = decision + int(contract["evaluation"]["new_order_activation_delay_ms"])
    times = minute["start_time_ms"].to_numpy(dtype=np.int64)
    opens = minute["open"].to_numpy(dtype=float)
    highs = minute["high"].to_numpy(dtype=float)
    lows = minute["low"].to_numpy(dtype=float)
    valid = minute["valid"].to_numpy(dtype=bool)
    start = next_minute_index(times, active)
    if start >= len(times):
        return PricePath(str(event["event_id"]), action, side, decision, active, int(times[-1] + MS_MINUTE), "UNRESOLVED", None, None, stop, tp1, target, None, None, None, None, ())

    entry_idx: int | None = None
    entry_price: float | None = None
    queue_fraction = float(contract["alpha"]["passive_queue_penetration_bps"]) * 1e-4
    if action == "market":
        for idx in range(start, len(times)):
            if valid[idx] and np.isfinite(opens[idx]):
                entry_idx = idx
                entry_price = float(opens[idx])
                break
    elif action == "passive":
        limit = float(event["passive_limit_price"])
        if side == 1 and not (stop < limit < tp1):
            return PricePath(str(event["event_id"]), action, side, decision, active, active, "INVALID_ACTION", None, None, stop, tp1, target, None, None, None, "INVALID_LIMIT", ())
        if side == -1 and not (target < tp1 < limit < stop):
            return PricePath(str(event["event_id"]), action, side, decision, active, active, "INVALID_ACTION", None, None, stop, tp1, target, None, None, None, "INVALID_LIMIT", ())
        for idx in range(start, len(times)):
            if not valid[idx]:
                continue
            stop_hit = lows[idx] <= stop if side == 1 else highs[idx] >= stop
            target_hit = highs[idx] >= target if side == 1 else lows[idx] <= target
            fill_hit = lows[idx] <= limit * (1 - queue_fraction) if side == 1 else highs[idx] >= limit * (1 + queue_fraction)
            if fill_hit and stop_hit:
                entry_idx = idx
                entry_price = limit
                break
            if target_hit:
                return PricePath(str(event["event_id"]), action, side, decision, active, int(times[idx]), "CANCELLED", None, None, stop, tp1, target, None, None, None, "TARGET_BEFORE_FILL", ())
            if stop_hit:
                return PricePath(str(event["event_id"]), action, side, decision, active, int(times[idx]), "CANCELLED", None, None, stop, tp1, target, None, None, None, "INVALIDATED_BEFORE_FILL", ())
            if fill_hit:
                entry_idx = idx
                entry_price = limit
                break
    else:
        raise ValueError(action)

    if entry_idx is None or entry_price is None:
        return PricePath(str(event["event_id"]), action, side, decision, active, int(times[-1] + MS_MINUTE), "PENDING_UNRESOLVED", None, None, stop, tp1, target, None, None, None, None, ())

    tp1_time: int | None = None
    legs: list[tuple[int, float, float, str]] = []
    remaining = 1.0
    break_even = float(entry_price)
    for idx in range(entry_idx, len(times)):
        if not valid[idx]:
            continue
        current_stop = break_even if tp1_time is not None else stop
        stop_hit = lows[idx] <= current_stop if side == 1 else highs[idx] >= current_stop
        target_hit = highs[idx] >= target if side == 1 else lows[idx] <= target
        tp1_hit = highs[idx] >= tp1 if side == 1 else lows[idx] <= tp1
        if stop_hit:
            legs.append((int(times[idx]), remaining, float(current_stop), "BE" if tp1_time is not None else "STOP"))
            reason = "BE" if tp1_time is not None else "STOP"
            return PricePath(str(event["event_id"]), action, side, decision, active, int(times[idx] + MS_MINUTE), "FILLED_CLOSED", int(times[entry_idx]), float(entry_price), stop, tp1, target, tp1_time, int(times[idx]), float(current_stop), reason, tuple(legs))
        if idx == entry_idx:
            continue
        if tp1_time is None and tp1_hit:
            fraction = float(contract["alpha"]["tp1_fraction"])
            tp1_time = int(times[idx])
            legs.append((int(times[idx]), fraction, tp1, "TP1"))
            remaining -= fraction
            continue
        if tp1_time is not None and target_hit:
            legs.append((int(times[idx]), remaining, target, "TARGET"))
            return PricePath(str(event["event_id"]), action, side, decision, active, int(times[idx] + MS_MINUTE), "FILLED_CLOSED", int(times[entry_idx]), float(entry_price), stop, tp1, target, tp1_time, int(times[idx]), target, "TARGET", tuple(legs))
    return PricePath(str(event["event_id"]), action, side, decision, active, int(times[-1] + MS_MINUTE), "FILLED_OPEN", int(times[entry_idx]), float(entry_price), stop, tp1, target, tp1_time, None, None, "OPEN", tuple(legs))


def funding_per_unit(path: PricePath, funding: pd.DataFrame, mark: pd.DataFrame, end_ms: int | None = None) -> float:
    if path.entry_time_ms is None:
        return 0.0
    finish = path.exit_time_ms if path.exit_time_ms is not None else end_ms
    if finish is None:
        return 0.0
    rows = funding[(funding["timestamp_ms"] >= path.entry_time_ms) & (funding["timestamp_ms"] <= finish)]
    if rows.empty:
        return 0.0
    mark_times = mark["start_time_ms"].to_numpy(dtype=np.int64)
    mark_close = mark["close"].to_numpy(dtype=float)
    total = 0.0
    for row in rows.itertuples(index=False):
        timestamp = int(row.timestamp_ms)
        idx = int(np.searchsorted(mark_times, timestamp, side="right") - 1)
        if idx < 0 or not np.isfinite(mark_close[idx]):
            continue
        remaining = 1.0
        if path.tp1_time_ms is not None and timestamp >= path.tp1_time_ms:
            remaining = 1.0 - float(DEFAULT_CONTRACT["alpha"]["tp1_fraction"])
        total += -path.side * remaining * float(mark_close[idx]) * float(row.funding_rate)
    return total


def scenario_rates(contract: Mapping[str, Any], scenario: str, action: str) -> tuple[float, float]:
    cfg = contract["costs"][scenario]
    entry = cfg["market_entry_effective_bps"] if action == "market" else cfg["passive_entry_effective_bps"]
    return float(entry) * 1e-4, float(cfg["taker_exit_effective_bps"]) * 1e-4


def unit_economics(path: PricePath, funding: pd.DataFrame, mark: pd.DataFrame, contract: Mapping[str, Any], scenario: str, segment_end_ms: int) -> dict[str, float | bool]:
    if path.entry_time_ms is None or path.entry_price is None:
        return {"filled": False, "closed": False, "net_pnl": 0.0, "net_r": 0.0, "planned_loss": 0.0, "funding": 0.0}
    entry_rate, exit_rate = scenario_rates(contract, scenario, path.action)
    entry = float(path.entry_price)
    entry_cost = entry * entry_rate
    stop_cost = abs(float(path.stop_price)) * exit_rate
    planned_loss = abs(entry - float(path.stop_price)) + entry_cost + stop_cost
    pnl = -entry_cost
    for _, fraction, price, _ in path.legs:
        pnl += path.side * fraction * (float(price) - entry) - fraction * abs(float(price)) * exit_rate
    funding_value = funding_per_unit(path, funding, mark, end_ms=segment_end_ms)
    pnl += funding_value
    closed = path.exit_time_ms is not None
    net_r = pnl / planned_loss if planned_loss > 0 else 0.0
    return {"filled": True, "closed": closed, "net_pnl": float(pnl), "net_r": float(net_r), "planned_loss": float(planned_loss), "funding": float(funding_value)}


def build_action_table(events_by_symbol: Mapping[str, pd.DataFrame], data_by_symbol: Mapping[str, Mapping[str, pd.DataFrame]], contract: Mapping[str, Any]) -> tuple[pd.DataFrame, dict[tuple[str, str], PricePath]]:
    rows: list[dict[str, Any]] = []
    paths: dict[tuple[str, str], PricePath] = {}
    segment_end_ms = utc_ms(contract["evaluation"]["end_exclusive_utc"]) - MS_MINUTE
    for symbol, events in events_by_symbol.items():
        minute = data_by_symbol[symbol]["minute"]
        funding = data_by_symbol[symbol]["funding"]
        mark = data_by_symbol[symbol]["mark"]
        for event in events.to_dict("records"):
            for action in ("market", "passive"):
                path = simulate_path(event, action, minute, contract)
                paths[(str(event["event_id"]), action)] = path
                base = unit_economics(path, funding, mark, contract, "base", segment_end_ms)
                stress = unit_economics(path, funding, mark, contract, "stress", segment_end_ms)
                row = dict(event)
                row.update(
                    {
                        "action": action,
                        "path_status": path.status,
                        "filled": bool(base["filled"]),
                        "closed": bool(base["closed"]),
                        "outcome_time_ms": path.slot_end_time_ms,
                        "entry_time_ms": path.entry_time_ms,
                        "exit_time_ms": path.exit_time_ms,
                        "base_net_r": float(base["net_r"]),
                        "stress_net_r": float(stress["net_r"]),
                        "base_net_pnl_per_unit": float(base["net_pnl"]),
                        "base_planned_loss_per_unit": float(base["planned_loss"]),
                        "base_funding_per_unit": float(base["funding"]),
                    }
                )
                rows.append(row)
    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values(["decision_time_ms", "symbol", "event_id", "action"]).reset_index(drop=True)
    return table, paths


def model_matrix(frame: pd.DataFrame, feature_names: Sequence[str] | None = None) -> tuple[np.ndarray, list[str]]:
    numeric = event_feature_columns()
    data: dict[str, pd.Series] = {}
    for name in numeric:
        data[name] = pd.to_numeric(frame.get(name, np.nan), errors="coerce")
    data["side_long"] = (frame["side"].astype(int) == 1).astype(float)
    data["action_passive"] = (frame["action"] == "passive").astype(float)
    for value in SYMBOLS:
        data[f"symbol_{value}"] = (frame["symbol"] == value).astype(float)
    for value in ("london", "ny_am"):
        data[f"session_{value}"] = (frame["target_session"] == value).astype(float)
    for value in ("asia", "london", "previous_day"):
        data[f"reference_{value}"] = (frame["reference"] == value).astype(float)
    matrix = pd.DataFrame(data).replace([np.inf, -np.inf], np.nan)
    if feature_names is None:
        feature_names = list(matrix.columns)
    matrix = matrix.reindex(columns=list(feature_names))
    medians = matrix.median(axis=0, skipna=True).fillna(0.0)
    matrix = matrix.fillna(medians).fillna(0.0)
    return matrix.to_numpy(dtype=float), list(feature_names)


def fit_probability(x: np.ndarray, y: np.ndarray, params: Mapping[str, Any]) -> Any:
    values = np.unique(y)
    if len(values) < 2:
        return ConstantProbability(float(np.mean(y)) if len(y) else 0.5)
    model = HistGradientBoostingClassifier(
        learning_rate=params["learning_rate"], max_iter=params["max_iter"], max_leaf_nodes=params["max_leaf_nodes"],
        min_samples_leaf=params["min_samples_leaf"], l2_regularization=params["l2_regularization"],
        random_state=params["random_state"], early_stopping=False,
    )
    model.fit(x, y)
    return model


def fit_regression(x: np.ndarray, y: np.ndarray, params: Mapping[str, Any]) -> Any:
    if len(y) < 2 or float(np.nanstd(y)) < 1e-9:
        return ConstantRegression(float(np.nanmean(y)) if len(y) else 0.0)
    model = HistGradientBoostingRegressor(
        learning_rate=params["learning_rate"], max_iter=params["max_iter"], max_leaf_nodes=params["max_leaf_nodes"],
        min_samples_leaf=params["min_samples_leaf"], l2_regularization=params["l2_regularization"],
        random_state=params["random_state"] + 1, early_stopping=False, loss="squared_error",
    )
    model.fit(x, np.clip(y, -5.0, 10.0))
    return model


def fit_logistic_calibrator(raw: np.ndarray, y: np.ndarray) -> Any:
    if len(np.unique(y)) < 2:
        return ConstantProbability(float(np.mean(y)) if len(y) else 0.5)
    model = LogisticRegression(C=1.0, solver="lbfgs", max_iter=500, class_weight="balanced", random_state=73)
    model.fit(raw.reshape(-1, 1), y)
    return model


def calibrated_probability(calibrator: Any, raw: np.ndarray) -> np.ndarray:
    return calibrator.predict_proba(raw.reshape(-1, 1))[:, 1]


def fit_model_bundle(rows: pd.DataFrame, active_at_ms: int, contract: Mapping[str, Any]) -> ModelBundle | None:
    cfg = contract["model"]
    history = rows[(rows["outcome_time_ms"] < active_at_ms) & rows["closed"]].copy()
    calibration_start = active_at_ms - int(cfg["base_calibration_days"]) * 24 * 60 * MS_MINUTE
    base = history[history["outcome_time_ms"] < calibration_start]
    calibration = history[history["outcome_time_ms"] >= calibration_start]
    if len(base) < int(cfg["minimum_base_rows"]) or len(calibration) < int(cfg["minimum_calibration_rows"]):
        return None
    x_base, names = model_matrix(base)
    filled_base = base["filled"].to_numpy(dtype=bool)
    win_y = (base.loc[filled_base, "base_net_r"].to_numpy(dtype=float) > 0).astype(int)
    r_y = base.loc[filled_base, "base_net_r"].to_numpy(dtype=float)
    if int(filled_base.sum()) < 150:
        return None
    params = cfg["estimator"]
    win_model = fit_probability(x_base[filled_base], win_y, params)
    r_model = fit_regression(x_base[filled_base], r_y, params)
    passive_base = base["action"].eq("passive").to_numpy()
    fill_x = x_base[passive_base]
    fill_y = base.loc[passive_base, "filled"].to_numpy(dtype=int)
    if len(fill_y) >= int(cfg["minimum_passive_fill_rows"]):
        fill_model = fit_probability(fill_x, fill_y, params)
    else:
        fill_model = ConstantProbability(float(np.mean(fill_y)) if len(fill_y) else 0.5)

    x_cal, _ = model_matrix(calibration, names)
    filled_cal = calibration["filled"].to_numpy(dtype=bool)
    raw_win = win_model.predict_proba(x_cal[filled_cal])[:, 1]
    win_calibrator = fit_logistic_calibrator(raw_win, (calibration.loc[filled_cal, "base_net_r"].to_numpy() > 0).astype(int))
    raw_r = r_model.predict(x_cal[filled_cal])
    r_calibrator = Ridge(alpha=5.0)
    r_calibrator.fit(raw_r.reshape(-1, 1), np.clip(calibration.loc[filled_cal, "base_net_r"].to_numpy(dtype=float), -5, 10))
    passive_cal = calibration["action"].eq("passive").to_numpy()
    if passive_cal.sum() >= 20:
        raw_fill = fill_model.predict_proba(x_cal[passive_cal])[:, 1]
        fill_calibrator = fit_logistic_calibrator(raw_fill, calibration.loc[passive_cal, "filled"].to_numpy(dtype=int))
    else:
        fill_calibrator = ConstantProbability(float(calibration.loc[passive_cal, "filled"].mean()) if passive_cal.sum() else 0.5)
    return ModelBundle(
        active_at_ms=active_at_ms,
        training_cutoff_ms=active_at_ms,
        base_rows=len(base),
        calibration_rows=len(calibration),
        feature_names=names,
        win_model=win_model,
        r_model=r_model,
        fill_model=fill_model,
        win_calibrator=win_calibrator,
        r_calibrator=r_calibrator,
        fill_calibrator=fill_calibrator,
    )


def build_model_schedule(actions: pd.DataFrame, contract: Mapping[str, Any]) -> list[ModelBundle]:
    start = pd.Timestamp(contract["evaluation"]["start_utc"])
    end = pd.Timestamp(contract["evaluation"]["end_exclusive_utc"])
    cutoffs = [utc_ms(start)]
    current = (start + pd.offsets.MonthBegin(1)).normalize()
    while current < end:
        cutoffs.append(utc_ms(current + pd.Timedelta(minutes=10)))
        current = current + pd.offsets.MonthBegin(1)
    schedule: list[ModelBundle] = []
    last: ModelBundle | None = None
    for cutoff in cutoffs:
        bundle = fit_model_bundle(actions, cutoff, contract)
        if bundle is not None:
            schedule.append(bundle)
            last = bundle
        elif last is None:
            raise RuntimeError(f"insufficient pre-2024 data to fit initial model at {iso_ms(cutoff)}")
    return schedule


def score_with_bundle(frame: pd.DataFrame, bundle: ModelBundle) -> pd.DataFrame:
    x, _ = model_matrix(frame, bundle.feature_names)
    raw_win = bundle.win_model.predict_proba(x)[:, 1]
    p_win = calibrated_probability(bundle.win_calibrator, raw_win)
    raw_r = bundle.r_model.predict(x)
    expected_r_filled = bundle.r_calibrator.predict(raw_r.reshape(-1, 1))
    passive = frame["action"].eq("passive").to_numpy()
    p_fill = np.ones(len(frame), dtype=float)
    if passive.any():
        raw_fill = bundle.fill_model.predict_proba(x[passive])[:, 1]
        p_fill[passive] = calibrated_probability(bundle.fill_calibrator, raw_fill)
    out = frame.copy()
    out["model_active_at_ms"] = bundle.active_at_ms
    out["p_win"] = np.clip(p_win, 0, 1)
    out["p_fill"] = np.clip(p_fill, 0, 1)
    out["expected_r_filled"] = expected_r_filled
    out["expected_net_r"] = out["p_fill"] * out["expected_r_filled"]
    return out


def score_official(actions: pd.DataFrame, schedule: Sequence[ModelBundle], contract: Mapping[str, Any]) -> pd.DataFrame:
    start_ms = utc_ms(contract["evaluation"]["start_utc"])
    end_ms = utc_ms(contract["evaluation"]["end_exclusive_utc"])
    official = actions[(actions["decision_time_ms"] >= start_ms) & (actions["decision_time_ms"] < end_ms)].copy()
    parts: list[pd.DataFrame] = []
    for index, bundle in enumerate(schedule):
        next_active = schedule[index + 1].active_at_ms if index + 1 < len(schedule) else end_ms
        subset = official[(official["decision_time_ms"] >= bundle.active_at_ms) & (official["decision_time_ms"] < next_active)]
        if not subset.empty:
            parts.append(score_with_bundle(subset, bundle))
    scored = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if scored.empty:
        return scored
    eligibility = contract["model"]["eligibility"]
    scored["eligible"] = (
        (scored["p_win"] >= float(eligibility["minimum_win_probability"]))
        & (scored["expected_net_r"] > float(eligibility["minimum_expected_net_r"]))
        & ((scored["action"] != "passive") | (scored["p_fill"] >= float(eligibility["minimum_passive_fill_probability"])))
    )
    return scored


def choose_global_slot(scored: pd.DataFrame, paths: Mapping[tuple[str, str], PricePath]) -> pd.DataFrame:
    if scored.empty:
        return scored
    eligible = scored[scored["eligible"]].copy()
    if eligible.empty:
        return eligible
    eligible = eligible.sort_values(["event_id", "expected_net_r", "p_win", "p_fill"], ascending=[True, False, False, False])
    per_event = eligible.groupby("event_id", sort=False, as_index=False).head(1)
    per_event = per_event.sort_values(["decision_time_ms", "expected_net_r", "p_win", "symbol"], ascending=[True, False, False, True])
    selected_rows: list[pd.Series] = []
    slot_free_at = -1
    for decision_time, group in per_event.groupby("decision_time_ms", sort=True):
        if int(decision_time) < slot_free_at:
            continue
        choice = group.iloc[0]
        path = paths[(str(choice["event_id"]), str(choice["action"]))]
        selected_rows.append(choice)
        slot_free_at = max(int(path.slot_end_time_ms), int(decision_time) + 1)
    return pd.DataFrame(selected_rows).reset_index(drop=True) if selected_rows else per_event.iloc[:0].copy()


def mark_series(data_by_symbol: Mapping[str, Mapping[str, pd.DataFrame]], symbol: str, timeline: np.ndarray) -> np.ndarray:
    mark = data_by_symbol[symbol]["mark"]
    times = mark["start_time_ms"].to_numpy(dtype=np.int64)
    close = mark["close"].to_numpy(dtype=float)
    index = np.searchsorted(times, timeline, side="right") - 1
    values = np.full(len(timeline), np.nan, dtype=float)
    valid = index >= 0
    values[valid] = close[index[valid]]
    return values


def replay_account(
    selected: pd.DataFrame,
    paths: Mapping[tuple[str, str], PricePath],
    data_by_symbol: Mapping[str, Mapping[str, pd.DataFrame]],
    contract: Mapping[str, Any],
    scenario: str,
) -> dict[str, Any]:
    start_ms = utc_ms(contract["evaluation"]["start_utc"])
    end_ms = utc_ms(contract["evaluation"]["end_exclusive_utc"])
    timeline = np.arange(start_ms, end_ms, MS_MINUTE, dtype=np.int64)
    equity = np.full(len(timeline), np.nan, dtype=float)
    cash = float(contract["evaluation"]["start_nav"])
    cursor = 0
    trades: list[dict[str, Any]] = []
    liquidated = False
    open_state: dict[str, Any] | None = None

    for row in selected.sort_values("decision_time_ms").itertuples(index=False):
        path = paths[(str(row.event_id), str(row.action))]
        if path.entry_time_ms is None or path.entry_price is None:
            trades.append({
                "event_id": str(row.event_id), "symbol": row.symbol, "action": row.action,
                "decision_time_utc": iso_ms(int(row.decision_time_ms)), "status": path.status,
                "expected_net_r": float(row.expected_net_r), "p_win": float(row.p_win), "p_fill": float(row.p_fill),
            })
            continue
        entry_idx_global = int(np.searchsorted(timeline, path.entry_time_ms, side="left"))
        if entry_idx_global >= len(timeline):
            continue
        if entry_idx_global > cursor:
            equity[cursor:entry_idx_global] = cash
        entry_rate, exit_rate = scenario_rates(contract, scenario, path.action)
        planning_entry_rate, planning_exit_rate = scenario_rates(contract, "base", path.action)
        entry = float(path.entry_price)
        planned_loss_per_unit = abs(entry - path.stop_price) + entry * planning_entry_rate + abs(path.stop_price) * planning_exit_rate
        risk_budget = cash * float(contract["risk"]["risk_fraction"])
        risk_qty = risk_budget / planned_loss_per_unit if planned_loss_per_unit > 0 else 0.0
        stop_fraction = abs(entry - path.stop_price) / entry
        safe_leverage = 1.0 / max(1e-9, stop_fraction + float(contract["risk"]["maintenance_margin_fraction"]) + float(contract["risk"]["liquidation_buffer_fraction"]) + planning_entry_rate + planning_exit_rate)
        allowed_leverage = min(float(contract["risk"]["max_leverage"]), safe_leverage)
        leverage_qty = cash * allowed_leverage / entry
        rule = contract["risk"]["quantity_rules"][row.symbol]
        qty = floor_step(min(risk_qty, leverage_qty), float(rule["step"]))
        if qty < float(rule["minimum"]):
            trades.append({"event_id": str(row.event_id), "symbol": row.symbol, "action": row.action, "status": "SKIPPED_MIN_QTY"})
            cursor = entry_idx_global
            continue
        initial_qty = qty
        remaining_qty = qty
        entry_cost = qty * entry * entry_rate
        cash_before = cash
        cash -= entry_cost
        mark_values = mark_series(data_by_symbol, row.symbol, timeline)
        symbol_funding = data_by_symbol[row.symbol]["funding"]
        funding_rows = symbol_funding[(symbol_funding["timestamp_ms"] >= path.entry_time_ms) & (symbol_funding["timestamp_ms"] < end_ms)]
        funding_by_minute = {int(record.timestamp_ms): float(record.funding_rate) for record in funding_rows.itertuples(index=False)}
        legs_by_minute: dict[int, list[tuple[float, float, str]]] = defaultdict(list)
        for leg_time, fraction, price, reason in path.legs:
            legs_by_minute[int(leg_time)].append((float(fraction), float(price), str(reason)))
        final_idx = int(np.searchsorted(timeline, path.exit_time_ms, side="left")) if path.exit_time_ms is not None else len(timeline) - 1
        final_idx = min(final_idx, len(timeline) - 1)
        minimum_margin_ratio = float("inf")
        trade_funding = 0.0
        trade_exit_cost = 0.0
        realized_pnl = -entry_cost
        for index in range(entry_idx_global, final_idx + 1):
            minute_ms = int(timeline[index])
            mark_price = float(mark_values[index]) if np.isfinite(mark_values[index]) else entry
            if minute_ms in funding_by_minute and remaining_qty > 0:
                payment = -path.side * remaining_qty * mark_price * funding_by_minute[minute_ms]
                cash += payment
                realized_pnl += payment
                trade_funding += payment
            if minute_ms in legs_by_minute:
                for fraction, price, reason in legs_by_minute[minute_ms]:
                    leg_qty = min(remaining_qty, initial_qty * fraction)
                    if leg_qty <= 0:
                        continue
                    leg_pnl = path.side * leg_qty * (price - entry)
                    fee = leg_qty * abs(price) * exit_rate
                    cash += leg_pnl - fee
                    realized_pnl += leg_pnl - fee
                    trade_exit_cost += fee
                    remaining_qty -= leg_qty
            estimated_close_cost = remaining_qty * abs(mark_price) * exit_rate
            unrealized = path.side * remaining_qty * (mark_price - entry)
            current_equity = cash + unrealized - estimated_close_cost
            equity[index] = current_equity
            if remaining_qty > 0:
                notional = remaining_qty * abs(mark_price)
                margin_ratio = current_equity / notional if notional > 0 else float("inf")
                minimum_margin_ratio = min(minimum_margin_ratio, margin_ratio)
                if current_equity <= notional * float(contract["risk"]["maintenance_margin_fraction"]):
                    liquidated = True
            if remaining_qty <= max(1e-12, float(rule["step"]) / 10):
                remaining_qty = 0.0
                final_idx = index
                break
        cursor = min(final_idx + 1, len(timeline))
        if remaining_qty > 0:
            last_mark = float(mark_values[min(final_idx, len(timeline) - 1)]) if np.isfinite(mark_values[min(final_idx, len(timeline) - 1)]) else entry
            open_state = {
                "event_id": str(row.event_id), "symbol": row.symbol, "side": path.side, "quantity": remaining_qty,
                "entry_price": entry, "mark_price": last_mark, "stop_price": path.stop_price,
                "target_price": path.target_price,
            }
        trades.append(
            {
                "event_id": str(row.event_id), "symbol": row.symbol, "action": row.action,
                "decision_time_utc": iso_ms(int(row.decision_time_ms)), "entry_time_utc": iso_ms(path.entry_time_ms),
                "exit_time_utc": iso_ms(path.exit_time_ms), "status": path.status, "exit_reason": path.exit_reason,
                "quantity": qty, "entry_price": entry, "stop_price": path.stop_price, "tp1_price": path.tp1_price,
                "target_price": path.target_price, "planned_risk_usdt": risk_budget,
                "allowed_leverage": allowed_leverage, "notional_to_nav": qty * entry / max(1e-12, cash_before),
                "entry_cost_usdt": entry_cost, "exit_cost_usdt": trade_exit_cost, "funding_usdt": trade_funding,
                "realized_pnl_usdt": realized_pnl, "account_return": realized_pnl / max(1e-12, cash_before),
                "minimum_margin_ratio": None if not np.isfinite(minimum_margin_ratio) else minimum_margin_ratio,
                "expected_net_r": float(row.expected_net_r), "p_win": float(row.p_win), "p_fill": float(row.p_fill),
                "base_label_net_r": float(row.base_net_r), "stress_label_net_r": float(row.stress_net_r),
                "target_session": row.target_session, "reference": row.reference, "side": int(row.side),
                "model_active_at_utc": iso_ms(int(row.model_active_at_ms)),
            }
        )
    if cursor < len(timeline):
        equity[cursor:] = cash if open_state is None else equity[cursor - 1]
    equity = pd.Series(equity).ffill().fillna(float(contract["evaluation"]["start_nav"])).to_numpy(dtype=float)
    ending_nav = float(equity[-1])
    running_peak = np.maximum.accumulate(equity)
    drawdown = equity / running_peak - 1.0
    max_drawdown = float(np.nanmin(drawdown))
    timestamps = pd.to_datetime(timeline, unit="ms", utc=True)
    daily = pd.DataFrame({"timestamp": timestamps, "nav": equity}).set_index("timestamp")["nav"].resample("1D").last()
    daily = daily.reindex(pd.date_range(contract["evaluation"]["start_utc"], periods=182, freq="1D", tz="UTC")).ffill()
    day_count = len(daily)
    daily_geo = (ending_nav / float(contract["evaluation"]["start_nav"])) ** (1.0 / day_count) - 1.0
    filled_trades = [trade for trade in trades if trade.get("quantity", 0) and trade.get("realized_pnl_usdt") is not None]
    closed = [trade for trade in filled_trades if trade.get("exit_time_utc")]
    gross_profit = sum(max(0.0, float(trade["realized_pnl_usdt"])) for trade in closed)
    gross_loss = -sum(min(0.0, float(trade["realized_pnl_usdt"])) for trade in closed)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    win_rate = sum(float(trade["realized_pnl_usdt"]) > 0 for trade in closed) / len(closed) if closed else 0.0
    returns = [float(trade["account_return"]) for trade in closed]
    top_share = 0.0
    positive_total = sum(max(0.0, value) for value in returns)
    if positive_total > 0:
        top_share = max([max(0.0, value) for value in returns] or [0.0]) / positive_total
    daily_rows = [{"date": index.date().isoformat(), "nav": float(value)} for index, value in daily.items()]
    return {
        "scenario": scenario,
        "start_nav": float(contract["evaluation"]["start_nav"]),
        "ending_nav": ending_nav,
        "account_multiple": ending_nav / float(contract["evaluation"]["start_nav"]),
        "total_return": ending_nav / float(contract["evaluation"]["start_nav"]) - 1.0,
        "day_count": day_count,
        "daily_geometric_growth": float(daily_geo),
        "max_drawdown": max_drawdown,
        "selected_slots": len(selected),
        "filled_trades": len(filled_trades),
        "closed_trades": len(closed),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "top_trade_positive_return_share": top_share,
        "liquidated": liquidated,
        "open_state_at_end": open_state,
        "trades": trades,
        "daily_nav": daily_rows,
    }


def pre2024_diagnostics(actions: pd.DataFrame, schedule: Sequence[ModelBundle], contract: Mapping[str, Any]) -> dict[str, Any]:
    cutoff = utc_ms(contract["evaluation"]["start_utc"])
    history = actions[(actions["decision_time_ms"] >= utc_ms("2023-09-01T00:00:00Z")) & (actions["decision_time_ms"] < cutoff) & actions["closed"]]
    if history.empty:
        return {"rows": 0}
    bundle = schedule[0]
    scored = score_with_bundle(history, bundle)
    eligibility = contract["model"]["eligibility"]
    scored["eligible"] = (
        (scored["p_win"] >= float(eligibility["minimum_win_probability"]))
        & (scored["expected_net_r"] > float(eligibility["minimum_expected_net_r"]))
        & ((scored["action"] != "passive") | (scored["p_fill"] >= float(eligibility["minimum_passive_fill_probability"])))
    )
    selected = scored[scored["eligible"]].sort_values(["event_id", "expected_net_r"], ascending=[True, False]).groupby("event_id", as_index=False).head(1)
    return {
        "rows": len(history), "eligible_event_actions": int(scored["eligible"].sum()), "selected_events": len(selected),
        "selected_mean_base_net_r": float(selected["base_net_r"].mean()) if len(selected) else 0.0,
        "selected_median_base_net_r": float(selected["base_net_r"].median()) if len(selected) else 0.0,
        "selected_positive_rate": float((selected["base_net_r"] > 0).mean()) if len(selected) else 0.0,
    }


def self_test() -> None:
    contract = DEFAULT_CONTRACT
    times = np.arange(0, 6 * MS_MINUTE, MS_MINUTE, dtype=np.int64)
    minute = pd.DataFrame(
        {
            "start_time_ms": times,
            "open": [100, 100, 101, 102, 103, 104],
            "high": [100.5, 101, 102.5, 104, 105.5, 105],
            "low": [99.5, 99.8, 100.5, 101.5, 102.5, 103.5],
            "close": [100, 100.5, 102, 103, 105, 104.5],
            "valid": True,
        }
    )
    event = {
        "event_id": "TEST", "side": 1, "decision_time_ms": -MS_MINUTE, "stop_price": 98.0,
        "tp1_price": 102.0, "target_price": 105.0, "passive_limit_price": 99.5,
    }
    path = simulate_path(event, "market", minute, contract)
    assert path.entry_time_ms == 0
    assert path.tp1_time_ms == 2 * MS_MINUTE
    assert path.exit_reason == "TARGET"
    assert len(path.legs) == 2
    assert floor_step(1.234, 0.01) == 1.23
    dummy = pd.DataFrame(
        {
            "side": [1], "action": ["market"], "symbol": ["BTCUSDT"], "target_session": ["london"],
            "reference": ["asia"], **{name: [0.0] for name in event_feature_columns()},
        }
    )
    x, names = model_matrix(dummy)
    assert x.shape == (1, len(names))
    print(json.dumps({"self_test": "PASS", "feature_count": len(names)}, indent=2))


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract = json.loads(args.contract.read_text(encoding="utf-8")) if args.contract else json.loads(json.dumps(DEFAULT_CONTRACT))
    data_root = args.data_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    shards = find_shards(data_root)
    required = {(segment, symbol) for segment in ("PRE_2024_2023", "2024_H1") for symbol in SYMBOLS}
    missing = sorted(required.difference(shards))
    if missing:
        raise RuntimeError(f"missing required canonical shards: {missing}")

    data_by_symbol: dict[str, dict[str, pd.DataFrame]] = {}
    events_by_symbol: dict[str, pd.DataFrame] = {}
    for symbol in SYMBOLS:
        print(f"prepare {symbol}", flush=True)
        data_by_symbol[symbol] = prepare_symbol_data(shards, symbol)
        events_by_symbol[symbol] = generate_events(symbol, data_by_symbol[symbol]["five"], contract)
        print(f"events {symbol}: {len(events_by_symbol[symbol])}", flush=True)

    actions, paths = build_action_table(events_by_symbol, data_by_symbol, contract)
    if actions.empty:
        raise RuntimeError("no candidate actions generated")
    schedule = build_model_schedule(actions, contract)
    scored = score_official(actions, schedule, contract)
    selected = choose_global_slot(scored, paths)
    base = replay_account(selected, paths, data_by_symbol, contract, "base")
    stress = replay_account(selected, paths, data_by_symbol, contract, "stress")
    pre2024 = pre2024_diagnostics(actions, schedule, contract)

    manifests = []
    for key in sorted(required):
        manifest_path = shards[key] / "DATASET_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifests.append({"physical_segment": key[0], "symbol": key[1], "dataset_id": manifest["dataset_id"], "manifest_sha256": sha256_file(manifest_path)})
    model_rows = [
        {
            "active_at_utc": iso_ms(bundle.active_at_ms), "training_cutoff_utc": iso_ms(bundle.training_cutoff_ms),
            "base_rows": bundle.base_rows, "calibration_rows": bundle.calibration_rows,
        }
        for bundle in schedule
    ]
    candidate_counts = {symbol: int(len(events)) for symbol, events in events_by_symbol.items()}
    action_status_counts = actions["path_status"].value_counts(dropna=False).to_dict()
    result: dict[str, Any] = {
        "schema_version": 1,
        "result_id": "R-YTTRI-SESSION-AMD-PARTIAL-ML-2024H1-COARSE-V1",
        "status": "COARSE_ECONOMIC_SCREEN",
        "rank_eligible": False,
        "rank_ineligibility": "Sub-minute event-tape execution and continuous 2024H2-2026H1 path are not yet complete.",
        "system_id": contract["system_id"],
        "work_claim_id": contract["claim_id"],
        "contract_sha256": hashlib.sha256(canonical_json(contract).encode("utf-8")).hexdigest(),
        "runner": {"platform": platform.platform(), "python": sys.version, "github_run_id": os.environ.get("GITHUB_RUN_ID"), "github_sha": os.environ.get("GITHUB_SHA")},
        "data_manifests": manifests,
        "candidate_event_counts": candidate_counts,
        "action_count": int(len(actions)),
        "action_status_counts": action_status_counts,
        "model_schedule": model_rows,
        "official_scored_actions": int(len(scored)),
        "official_eligible_actions": int(scored["eligible"].sum()) if len(scored) else 0,
        "official_selected_slots": int(len(selected)),
        "pre2024_diagnostics": pre2024,
        "base": base,
        "stress": stress,
    }
    result["decision"] = (
        "ADVANCE_EVENT_TAPE_AND_CONTINUE"
        if base["daily_geometric_growth"] > 0 and stress["daily_geometric_growth"] > 0 and not base["liquidated"] and not stress["liquidated"]
        else "ABANDON_OR_REDESIGN_ALPHA"
    )
    compact = dict(result)
    compact["base"] = {key: value for key, value in base.items() if key not in {"trades", "daily_nav"}}
    compact["stress"] = {key: value for key, value in stress.items() if key not in {"trades", "daily_nav"}}
    compact["payload_sha256_before_field"] = hashlib.sha256(canonical_json(compact).encode("utf-8")).hexdigest()

    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")
    (output / "result_compact.json").write_text(json.dumps(compact, ensure_ascii=False, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")
    (output / "contract.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    actions.to_parquet(output / "candidate_actions.parquet", index=False, engine="pyarrow", compression="zstd")
    scored.to_parquet(output / "official_scored_actions.parquet", index=False, engine="pyarrow", compression="zstd")
    selected.to_parquet(output / "official_selected_slots.parquet", index=False, engine="pyarrow", compression="zstd")
    print(json.dumps(compact, ensure_ascii=False, indent=2, sort_keys=True, default=json_default))
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.self_test and (args.data_root is None or args.output is None):
        parser.error("--data-root and --output are required unless --self-test is used")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
