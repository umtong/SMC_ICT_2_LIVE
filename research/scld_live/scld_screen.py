#!/usr/bin/env python3
"""Independent SCLD research system.

Only the canonical Bybit market-data loader is reused. No prior strategy,
feature, model, execution, risk, or backtest code is imported.

The system implements two causal SMC/ICT event families:
1) liquidity sweep -> reclaim -> displacement reversal;
2) displacement break -> first mitigation -> continuation.

A monthly expanding-window ML selector ranks completed event candidates. All
feature/model/threshold/risk decisions are made from information available
before the evaluated month. Orders activate 500 ms after the latest input;
with core one-minute execution data the first observable executable price is
the next UTC minute open.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.market_data.load_canonical_bybit import (  # noqa: E402
    load_stream,
    load_trade_bar,
    sha256_file,
)

MS_MIN = 60_000
DAY_MS = 86_400_000
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SEGMENTS = ("PRE_2024_2023", "2024_H1")
TRAIN_START_MS = int(pd.Timestamp("2023-01-01T00:00:00Z").timestamp() * 1000)
EVAL_START_MS = int(pd.Timestamp("2024-01-01T00:00:00Z").timestamp() * 1000)
EVAL_END_MS = int(pd.Timestamp("2024-07-01T00:00:00Z").timestamp() * 1000)

DATASETS = {
    ("PRE_2024_2023", "BTCUSDT"): "DS-BYBIT-LINEAR-BTCUSDT-PRE_2024_2023-CANONICAL-V1",
    ("PRE_2024_2023", "ETHUSDT"): "DS-BYBIT-LINEAR-ETHUSDT-PRE_2024_2023-CANONICAL-V1",
    ("2024_H1", "BTCUSDT"): "DS-BYBIT-LINEAR-BTCUSDT-2024_H1-CANONICAL-V1",
    ("2024_H1", "ETHUSDT"): "DS-BYBIT-LINEAR-ETHUSDT-2024_H1-CANONICAL-V1",
}

FEATURE_COLUMNS = [
    "symbol_code", "setup_code", "direction", "event_window", "event_age",
    "sweep_depth_atr", "reclaim_strength", "zone_width_atr", "mitigation_depth",
    "planned_rr", "stop_atr", "target_atr", "ret_1", "ret_3", "ret_12",
    "ret_48", "range_atr", "body_ratio", "close_location", "upper_wick_atr",
    "lower_wick_atr", "volume_z48", "turnover_z48", "atr_pct",
    "volatility_ratio", "distance_high_24_atr", "distance_low_24_atr",
    "distance_high_96_atr", "distance_low_96_atr", "trend_15m", "trend_1h",
    "location_1h", "range_1h_atr", "oi_change_1", "oi_change_12", "oi_z48",
    "account_imbalance", "account_imbalance_z48", "premium_basis",
    "mark_index_basis", "funding_rate", "other_ret_1", "other_ret_3",
    "other_ret_12", "relative_ret_12", "smt_high_divergence",
    "smt_low_divergence", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
]


@dataclass(frozen=True)
class CostModel:
    entry_fee_bps: float = 5.5
    target_fee_bps: float = 2.0
    stop_fee_bps: float = 5.5
    entry_slippage_bps: float = 1.5
    target_slippage_bps: float = 0.5
    stop_slippage_bps: float = 2.5
    maintenance_margin_rate: float = 0.005

    @staticmethod
    def bp(value: float) -> float:
        return value * 1e-4


@dataclass(frozen=True)
class StrategyConfig:
    sweep_windows: tuple[int, ...] = (12, 24, 48, 96)
    target_windows: tuple[int, ...] = (24, 48, 96, 288, 864)
    displacement_window: int = 24
    continuation_max_age: int = 10
    stop_buffer_atr: float = 0.08
    min_sweep_depth_atr: float = 0.015
    max_sweep_depth_atr: float = 1.60
    min_reclaim_location: float = 0.52
    min_displacement_range_atr: float = 1.10
    min_displacement_body_ratio: float = 0.52
    min_target_atr: float = 0.75
    fallback_target_atr: float = 2.40
    max_target_atr: float = 4.50
    min_planned_rr: float = 1.05
    fixed_latency_ms: int = 500


@dataclass(frozen=True)
class ModelSpec:
    max_leaf_nodes: int
    learning_rate: float
    min_samples_leaf: int
    l2_regularization: float

    def key(self) -> str:
        return (
            f"leaf{self.max_leaf_nodes}_lr{self.learning_rate:g}_"
            f"min{self.min_samples_leaf}_l2{self.l2_regularization:g}"
        )


@dataclass
class SymbolData:
    symbol: str
    bars_1m: pd.DataFrame
    bars_5m: pd.DataFrame
    bars_15m: pd.DataFrame
    bars_1h: pd.DataFrame
    mark_1m: pd.DataFrame
    index_1m: pd.DataFrame
    premium_1m: pd.DataFrame
    oi_5m: pd.DataFrame
    ratio_5m: pd.DataFrame
    funding: pd.DataFrame


@dataclass
class PortfolioConfig:
    expected_r_threshold: float
    min_probability: float
    risk_fraction: float
    leverage_cap: float

    def as_dict(self) -> dict[str, float]:
        return dataclasses.asdict(self)


def utc_ms(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1000)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def verify_canonical_root(root: Path) -> dict[str, Any]:
    verified = []
    for segment in SEGMENTS:
        for symbol in SYMBOLS:
            shard = root / segment / symbol
            manifest_path = shard / "DATASET_MANIFEST.json"
            if not manifest_path.is_file():
                raise FileNotFoundError(f"missing canonical manifest: {manifest_path}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = DATASETS[(segment, symbol)]
            if manifest.get("dataset_id") != expected:
                raise RuntimeError(f"dataset identity mismatch at {manifest_path}")
            expected_hash = (shard / "DATASET_MANIFEST.sha256").read_text().split()[0]
            actual_hash = sha256_file(manifest_path)
            if actual_hash != expected_hash:
                raise RuntimeError(f"manifest hash mismatch: {manifest_path}")
            verified.append({
                "segment": segment,
                "symbol": symbol,
                "dataset_id": expected,
                "manifest_sha256": actual_hash,
                "coverage": manifest.get("coverage", {}),
            })
    return {"verified_shards": verified, "count": len(verified)}


def concat_parts(parts: Sequence[pd.DataFrame], time_col: str) -> pd.DataFrame:
    frame = pd.concat(parts, ignore_index=True)
    frame = frame.sort_values(time_col, kind="stable").drop_duplicates(time_col, keep="last")
    return frame.reset_index(drop=True)


def load_symbol_data(root: Path, symbol: str) -> SymbolData:
    bars = {
        timeframe: concat_parts(
            [load_trade_bar(root, segment, symbol, timeframe) for segment in SEGMENTS],
            "start_time_ms",
        )
        for timeframe in ("1m", "5m", "15m", "1h")
    }
    streams = {}
    for name in (
        "mark_price_1m", "index_price_1m", "premium_index_1m",
        "open_interest_5m", "account_ratio_5m", "funding_events",
    ):
        time_col = "timestamp_ms" if name in {
            "open_interest_5m", "account_ratio_5m", "funding_events"
        } else "start_time_ms"
        streams[name] = concat_parts(
            [load_stream(root, segment, symbol, name) for segment in SEGMENTS],
            time_col,
        )
    return SymbolData(
        symbol=symbol, bars_1m=bars["1m"], bars_5m=bars["5m"],
        bars_15m=bars["15m"], bars_1h=bars["1h"],
        mark_1m=streams["mark_price_1m"], index_1m=streams["index_price_1m"],
        premium_1m=streams["premium_index_1m"], oi_5m=streams["open_interest_5m"],
        ratio_5m=streams["account_ratio_5m"], funding=streams["funding_events"],
    )


def true_range(frame: pd.DataFrame) -> pd.Series:
    previous = frame["close"].shift(1)
    return pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - previous).abs(),
        (frame["low"] - previous).abs(),
    ], axis=1).max(axis=1)


def rolling_z(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=max(8, window // 3)).mean()
    std = series.rolling(window, min_periods=max(8, window // 3)).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def merge_visible(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    left_time: str,
    right_time: str,
    columns: Sequence[str],
) -> pd.DataFrame:
    key = "__visible_right_time"
    right_use = right[[right_time, *columns]].copy()
    right_use = right_use.dropna(subset=[right_time]).sort_values(right_time)
    right_use = right_use.rename(columns={right_time: key})
    return pd.merge_asof(
        left.sort_values(left_time), right_use,
        left_on=left_time, right_on=key,
        direction="backward", allow_exact_matches=True,
    ).drop(columns=[key], errors="ignore")


def context_features(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    out = frame.copy()
    atr = true_range(out).rolling(20, min_periods=8).mean()
    high = out["high"].shift(1).rolling(24, min_periods=8).max()
    low = out["low"].shift(1).rolling(24, min_periods=8).min()
    out[f"{prefix}trend"] = np.log(out["close"] / out["close"].shift(4))
    out[f"{prefix}location"] = (out["close"] - low) / (high - low).replace(0.0, np.nan)
    out[f"{prefix}range_atr"] = (out["high"] - out["low"]) / atr
    return out[[
        "available_at_ms", f"{prefix}trend", f"{prefix}location", f"{prefix}range_atr"
    ]]


def build_market_features(data: SymbolData) -> pd.DataFrame:
    frame = data.bars_5m.copy()
    frame = frame[frame["is_complete"].fillna(False)].copy()
    frame = frame.sort_values("start_time_ms").reset_index(drop=True)
    frame["decision_ms"] = frame["available_at_ms"].astype("int64")
    frame["symbol"] = data.symbol
    frame["symbol_code"] = 0.0 if data.symbol == "BTCUSDT" else 1.0
    tr = true_range(frame)
    frame["atr"] = tr.rolling(24, min_periods=12).mean()
    frame["atr_slow"] = tr.rolling(288, min_periods=72).mean()
    frame["atr_pct"] = frame["atr"] / frame["close"]
    frame["volatility_ratio"] = frame["atr"] / frame["atr_slow"]
    frame["bar_range"] = frame["high"] - frame["low"]
    frame["range_atr"] = frame["bar_range"] / frame["atr"]
    frame["body"] = frame["close"] - frame["open"]
    frame["body_ratio"] = frame["body"].abs() / frame["bar_range"].replace(0.0, np.nan)
    frame["close_location"] = (
        (frame["close"] - frame["low"]) / frame["bar_range"].replace(0.0, np.nan)
    )
    frame["upper_wick_atr"] = (
        frame["high"] - frame[["open", "close"]].max(axis=1)
    ) / frame["atr"]
    frame["lower_wick_atr"] = (
        frame[["open", "close"]].min(axis=1) - frame["low"]
    ) / frame["atr"]
    for horizon in (1, 3, 12, 48):
        frame[f"ret_{horizon}"] = np.log(frame["close"] / frame["close"].shift(horizon))
    frame["volume_z48"] = rolling_z(np.log1p(frame["volume"]), 48)
    frame["turnover_z48"] = rolling_z(np.log1p(frame["turnover"]), 48)
    for window in sorted(set((12, 24, 48, 96, 288, 864))):
        minimum = max(6, window // 3)
        frame[f"prior_high_{window}"] = frame["high"].shift(1).rolling(window, min_periods=minimum).max()
        frame[f"prior_low_{window}"] = frame["low"].shift(1).rolling(window, min_periods=minimum).min()
    frame["distance_high_24_atr"] = (frame["prior_high_24"] - frame["close"]) / frame["atr"]
    frame["distance_low_24_atr"] = (frame["close"] - frame["prior_low_24"]) / frame["atr"]
    frame["distance_high_96_atr"] = (frame["prior_high_96"] - frame["close"]) / frame["atr"]
    frame["distance_low_96_atr"] = (frame["close"] - frame["prior_low_96"]) / frame["atr"]

    ctx15 = context_features(data.bars_15m, "ctx15_")
    frame = merge_visible(frame, ctx15, left_time="decision_ms", right_time="available_at_ms",
                          columns=["ctx15_trend", "ctx15_location", "ctx15_range_atr"])
    frame["trend_15m"] = frame["ctx15_trend"]
    ctx1h = context_features(data.bars_1h, "ctx1h_")
    frame = merge_visible(frame, ctx1h, left_time="decision_ms", right_time="available_at_ms",
                          columns=["ctx1h_trend", "ctx1h_location", "ctx1h_range_atr"])
    frame["trend_1h"] = frame["ctx1h_trend"]
    frame["location_1h"] = frame["ctx1h_location"]
    frame["range_1h_atr"] = frame["ctx1h_range_atr"]

    oi = data.oi_5m.copy()
    oi["oi_change_1"] = np.log(oi["open_interest"] / oi["open_interest"].shift(1))
    oi["oi_change_12"] = np.log(oi["open_interest"] / oi["open_interest"].shift(12))
    oi["oi_z48"] = rolling_z(np.log(oi["open_interest"]), 48)
    frame = merge_visible(frame, oi, left_time="decision_ms", right_time="available_at_ms",
                          columns=["oi_change_1", "oi_change_12", "oi_z48"])

    ratio = data.ratio_5m.copy()
    ratio["account_imbalance"] = ratio["buy_ratio"] - ratio["sell_ratio"]
    ratio["account_imbalance_z48"] = rolling_z(ratio["account_imbalance"], 48)
    frame = merge_visible(frame, ratio, left_time="decision_ms", right_time="available_at_ms",
                          columns=["account_imbalance", "account_imbalance_z48"])

    premium = data.premium_1m.copy()
    premium["premium_basis"] = premium["close"]
    frame = merge_visible(frame, premium, left_time="decision_ms", right_time="available_at_ms",
                          columns=["premium_basis"])
    mark = data.mark_1m[["available_at_ms", "close"]].rename(columns={"close": "mark_close"})
    index = data.index_1m[["available_at_ms", "close"]].rename(columns={"close": "index_close"})
    frame = merge_visible(frame, mark, left_time="decision_ms", right_time="available_at_ms",
                          columns=["mark_close"])
    frame = merge_visible(frame, index, left_time="decision_ms", right_time="available_at_ms",
                          columns=["index_close"])
    frame["mark_index_basis"] = (frame["mark_close"] - frame["index_close"]) / frame["index_close"]
    frame = merge_visible(frame, data.funding, left_time="decision_ms", right_time="available_at_ms",
                          columns=["funding_rate"])
    frame["funding_rate"] = frame["funding_rate"].fillna(0.0)

    dt = pd.to_datetime(frame["decision_ms"], unit="ms", utc=True)
    hour = dt.dt.hour + dt.dt.minute / 60.0
    dow = dt.dt.dayofweek
    frame["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    frame["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    frame["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    frame["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
    return frame.reset_index(drop=True)


def add_cross_asset_features(features: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    output = {}
    for symbol in SYMBOLS:
        other_symbol = "ETHUSDT" if symbol == "BTCUSDT" else "BTCUSDT"
        own = features[symbol]
        other = features[other_symbol][[
            "decision_ms", "ret_1", "ret_3", "ret_12", "high", "low",
            "prior_high_24", "prior_low_24",
        ]].rename(columns={
            "ret_1": "other_ret_1", "ret_3": "other_ret_3", "ret_12": "other_ret_12",
            "high": "other_high", "low": "other_low",
            "prior_high_24": "other_prior_high_24", "prior_low_24": "other_prior_low_24",
        })
        merged = own.merge(other, on="decision_ms", how="left", validate="one_to_one")
        merged["relative_ret_12"] = merged["ret_12"] - merged["other_ret_12"]
        own_high = merged["high"] > merged["prior_high_24"]
        other_high = merged["other_high"] > merged["other_prior_high_24"]
        own_low = merged["low"] < merged["prior_low_24"]
        other_low = merged["other_low"] < merged["other_prior_low_24"]
        merged["smt_high_divergence"] = own_high.astype(float) - other_high.astype(float)
        merged["smt_low_divergence"] = own_low.astype(float) - other_low.astype(float)
        output[symbol] = merged
    return output


def target_from_liquidity(
    frame: pd.DataFrame, idx: int, direction: int, reference: float, atr: float,
    cfg: StrategyConfig,
) -> float:
    if direction == 1:
        levels = [float(frame.at[idx, f"prior_high_{w}"]) for w in cfg.target_windows
                  if pd.notna(frame.at[idx, f"prior_high_{w}"])]
        valid = [level for level in levels if level >= reference + cfg.min_target_atr * atr]
        target = min(valid) if valid else reference + cfg.fallback_target_atr * atr
        return min(target, reference + cfg.max_target_atr * atr)
    levels = [float(frame.at[idx, f"prior_low_{w}"]) for w in cfg.target_windows
              if pd.notna(frame.at[idx, f"prior_low_{w}"])]
    valid = [level for level in levels if level <= reference - cfg.min_target_atr * atr]
    target = max(valid) if valid else reference - cfg.fallback_target_atr * atr
    return max(target, reference - cfg.max_target_atr * atr)


def base_candidate(
    frame: pd.DataFrame, idx: int, *, setup: str, direction: int,
    stop: float, target: float, event_window: int, event_age: int,
    sweep_depth_atr: float = 0.0, reclaim_strength: float = 0.0,
    zone_width_atr: float = 0.0, mitigation_depth: float = 0.0,
) -> dict[str, Any]:
    row = frame.iloc[idx]
    atr = float(row["atr"])
    reference = float(row["close"])
    stop_distance = direction * (reference - stop)
    target_distance = direction * (target - reference)
    candidate = {
        "symbol": row["symbol"], "symbol_code": float(row["symbol_code"]),
        "setup": setup, "setup_code": 0.0 if setup == "sweep_reclaim" else 1.0,
        "direction": direction, "decision_ms": int(row["decision_ms"]),
        "reference_price": reference, "stop": stop, "target": target,
        "event_window": float(event_window), "event_age": float(event_age),
        "sweep_depth_atr": sweep_depth_atr, "reclaim_strength": reclaim_strength,
        "zone_width_atr": zone_width_atr, "mitigation_depth": mitigation_depth,
        "planned_rr": target_distance / stop_distance if stop_distance > 0 else np.nan,
        "stop_atr": stop_distance / atr if atr > 0 else np.nan,
        "target_atr": target_distance / atr if atr > 0 else np.nan,
    }
    for column in FEATURE_COLUMNS:
        if column not in candidate and column in row.index:
            candidate[column] = row[column]
    candidate["atr"] = atr
    return candidate


def generate_sweeps(frame: pd.DataFrame, cfg: StrategyConfig) -> list[dict[str, Any]]:
    candidates = []
    for idx in range(max(cfg.sweep_windows) + 5, len(frame)):
        row = frame.iloc[idx]
        atr = float(row["atr"]) if pd.notna(row["atr"]) else np.nan
        if not np.isfinite(atr) or atr <= 0 or row["bar_range"] <= 0:
            continue
        location = float(row["close_location"])
        best_long = None
        best_short = None
        for window in cfg.sweep_windows:
            low_level = row[f"prior_low_{window}"]
            high_level = row[f"prior_high_{window}"]
            if pd.notna(low_level) and row["low"] < low_level and row["close"] > low_level:
                depth = float((low_level - row["low"]) / atr)
                if cfg.min_sweep_depth_atr <= depth <= cfg.max_sweep_depth_atr and location >= cfg.min_reclaim_location:
                    best_long = (window, depth, float((row["close"] - low_level) / atr))
            if pd.notna(high_level) and row["high"] > high_level and row["close"] < high_level:
                depth = float((row["high"] - high_level) / atr)
                if cfg.min_sweep_depth_atr <= depth <= cfg.max_sweep_depth_atr and location <= 1.0 - cfg.min_reclaim_location:
                    best_short = (window, depth, float((high_level - row["close"]) / atr))
        if best_long:
            window, depth, reclaim = best_long
            stop = float(row["low"] - cfg.stop_buffer_atr * atr)
            target = target_from_liquidity(frame, idx, 1, float(row["close"]), atr, cfg)
            candidate = base_candidate(frame, idx, setup="sweep_reclaim", direction=1,
                                       stop=stop, target=target, event_window=window,
                                       event_age=0, sweep_depth_atr=depth,
                                       reclaim_strength=reclaim)
            if candidate["planned_rr"] >= cfg.min_planned_rr:
                candidates.append(candidate)
        if best_short:
            window, depth, reclaim = best_short
            stop = float(row["high"] + cfg.stop_buffer_atr * atr)
            target = target_from_liquidity(frame, idx, -1, float(row["close"]), atr, cfg)
            candidate = base_candidate(frame, idx, setup="sweep_reclaim", direction=-1,
                                       stop=stop, target=target, event_window=window,
                                       event_age=0, sweep_depth_atr=depth,
                                       reclaim_strength=reclaim)
            if candidate["planned_rr"] >= cfg.min_planned_rr:
                candidates.append(candidate)
    return candidates


def generate_continuations(frame: pd.DataFrame, cfg: StrategyConfig) -> list[dict[str, Any]]:
    candidates = []
    for idx in range(cfg.displacement_window + 5, len(frame)):
        row = frame.iloc[idx]
        atr = float(row["atr"]) if pd.notna(row["atr"]) else np.nan
        if not np.isfinite(atr) or atr <= 0:
            continue
        prior_high = row[f"prior_high_{cfg.displacement_window}"]
        prior_low = row[f"prior_low_{cfg.displacement_window}"]
        bull = (pd.notna(prior_high) and row["close"] > prior_high + 0.02 * atr
                and row["body"] > 0 and row["body_ratio"] >= cfg.min_displacement_body_ratio
                and row["range_atr"] >= cfg.min_displacement_range_atr)
        bear = (pd.notna(prior_low) and row["close"] < prior_low - 0.02 * atr
                and row["body"] < 0 and row["body_ratio"] >= cfg.min_displacement_body_ratio
                and row["range_atr"] >= cfg.min_displacement_range_atr)
        if not bull and not bear:
            continue
        if bull:
            zone_low, zone_high = float(frame.iloc[idx - 2]["high"]), float(row["low"])
            if zone_high <= zone_low:
                zone_low, zone_high = float(prior_high - 0.05 * atr), float(prior_high + 0.10 * atr)
            direction, origin = 1, float(row["low"])
        else:
            zone_low, zone_high = float(row["high"]), float(frame.iloc[idx - 2]["low"])
            if zone_high <= zone_low:
                zone_low, zone_high = float(prior_low - 0.10 * atr), float(prior_low + 0.05 * atr)
            direction, origin = -1, float(row["high"])
        zone_mid = 0.5 * (zone_low + zone_high)
        invalidated = False
        for age in range(1, cfg.continuation_max_age + 1):
            j = idx + age
            if j >= len(frame):
                break
            nxt = frame.iloc[j]
            invalidated |= direction == 1 and nxt["close"] < origin
            invalidated |= direction == -1 and nxt["close"] > origin
            if invalidated:
                break
            touched = nxt["low"] <= zone_high and nxt["high"] >= zone_low
            if not touched:
                continue
            accepted = ((direction == 1 and nxt["close"] > zone_mid and nxt["close"] > nxt["open"])
                        or (direction == -1 and nxt["close"] < zone_mid and nxt["close"] < nxt["open"]))
            if accepted:
                if direction == 1:
                    stop = min(float(nxt["low"]), origin, zone_low) - cfg.stop_buffer_atr * atr
                    mitigation = (zone_high - float(nxt["low"])) / max(zone_high - zone_low, 1e-12)
                else:
                    stop = max(float(nxt["high"]), origin, zone_high) + cfg.stop_buffer_atr * atr
                    mitigation = (float(nxt["high"]) - zone_low) / max(zone_high - zone_low, 1e-12)
                target = target_from_liquidity(frame, j, direction, float(nxt["close"]), float(nxt["atr"]), cfg)
                candidate = base_candidate(
                    frame, j, setup="displacement_mitigation", direction=direction,
                    stop=stop, target=target, event_window=cfg.displacement_window,
                    event_age=age, zone_width_atr=(zone_high - zone_low) / atr,
                    mitigation_depth=mitigation,
                )
                if candidate["planned_rr"] >= cfg.min_planned_rr:
                    candidates.append(candidate)
            break
    return candidates


def generate_candidates(features: dict[str, pd.DataFrame], cfg: StrategyConfig) -> pd.DataFrame:
    rows = []
    for symbol in SYMBOLS:
        rows.extend(generate_sweeps(features[symbol], cfg))
        rows.extend(generate_continuations(features[symbol], cfg))
    frame = pd.DataFrame(rows)
    frame["quality"] = frame["planned_rr"].clip(upper=5.0) + 0.25 * frame["reclaim_strength"].fillna(0.0)
    frame = frame.sort_values(["symbol", "decision_ms", "direction", "setup", "quality"],
                              ascending=[True, True, True, True, False])
    frame = frame.drop_duplicates(["symbol", "decision_ms", "direction", "setup"], keep="first")
    frame["event_id"] = [
        f"{r.symbol}-{int(r.decision_ms)}-{r.setup}-{'L' if int(r.direction) == 1 else 'S'}"
        for r in frame.itertuples()
    ]
    return frame.sort_values(["decision_ms", "symbol", "setup"]).reset_index(drop=True)


def funding_cash_per_unit(data: SymbolData, entry_ms: int, exit_ms: int, direction: int) -> float:
    times = data.funding["timestamp_ms"].to_numpy(dtype=np.int64)
    rates = data.funding["funding_rate"].to_numpy(dtype=float)
    lo = int(np.searchsorted(times, entry_ms, side="right"))
    hi = int(np.searchsorted(times, exit_ms, side="right"))
    mark_times = data.mark_1m["start_time_ms"].to_numpy(dtype=np.int64)
    marks = data.mark_1m["close"].to_numpy(dtype=float)
    cash = 0.0
    for ts, rate in zip(times[lo:hi], rates[lo:hi], strict=True):
        idx = int(np.searchsorted(mark_times, ts, side="right") - 1)
        if idx >= 0 and np.isfinite(marks[idx]):
            cash += -direction * float(marks[idx]) * float(rate)
    return cash


def label_candidates(
    candidates: pd.DataFrame, symbol_data: dict[str, SymbolData],
    cfg: StrategyConfig, costs: CostModel,
) -> pd.DataFrame:
    records = []
    arrays = {}
    for symbol in SYMBOLS:
        bars = symbol_data[symbol].bars_1m
        arrays[symbol] = {column: bars[column].to_numpy() for column in
                          ("start_time_ms", "open", "high", "low", "close")}
    for ordinal, row in enumerate(candidates.itertuples(index=False)):
        market = arrays[row.symbol]
        times = market["start_time_ms"].astype(np.int64)
        activation = int(row.decision_ms) + cfg.fixed_latency_ms
        entry_idx = int(np.searchsorted(times, activation, side="left"))
        if entry_idx >= len(times):
            continue
        entry_ms = int(times[entry_idx])
        entry = float(market["open"][entry_idx])
        direction, stop, target, atr = int(row.direction), float(row.stop), float(row.target), float(row.atr)
        stop_distance = direction * (entry - stop)
        target_distance = direction * (target - entry)
        if not np.isfinite(entry) or stop_distance <= 0 or target_distance <= 0:
            continue
        planned_rr = target_distance / stop_distance
        if planned_rr < cfg.min_planned_rr:
            continue
        outcome = exit_idx = None
        exit_raw = None
        path_min = path_max = entry
        for k in range(entry_idx, len(times)):
            low, high = float(market["low"][k]), float(market["high"][k])
            if not np.isfinite(low) or not np.isfinite(high):
                continue
            path_min, path_max = min(path_min, low), max(path_max, high)
            stop_hit = low <= stop if direction == 1 else high >= stop
            target_hit = high >= target if direction == 1 else low <= target
            if stop_hit:
                outcome, exit_idx, exit_raw = 0, k, stop
                break
            if target_hit:
                outcome, exit_idx, exit_raw = 1, k, target
                break
        if outcome is None:
            continue
        exit_ms = int(times[exit_idx]) + MS_MIN
        funding = funding_cash_per_unit(symbol_data[row.symbol], entry_ms, exit_ms, direction)
        entry_exec = entry * (1 + direction * CostModel.bp(costs.entry_slippage_bps))
        stop_exec = stop * (1 - direction * CostModel.bp(costs.stop_slippage_bps))
        target_exec = target * (1 - direction * CostModel.bp(costs.target_slippage_bps))
        entry_fee = entry_exec * CostModel.bp(costs.entry_fee_bps)
        stop_fee = stop_exec * CostModel.bp(costs.stop_fee_bps)
        target_fee = target_exec * CostModel.bp(costs.target_fee_bps)
        loss_per_unit = abs(entry_exec - stop_exec) + entry_fee + stop_fee
        win_cash = direction * (target_exec - entry_exec) - entry_fee - target_fee + funding
        loss_cash = direction * (stop_exec - entry_exec) - entry_fee - stop_fee + funding
        record = row._asdict()
        record.update({
            "entry_ms": entry_ms, "entry_price": entry, "entry_exec_price": entry_exec,
            "entry_gap_atr": direction * (entry - float(row.reference_price)) / atr,
            "planned_rr": planned_rr, "planned_loss_per_unit": loss_per_unit,
            "planned_win_r": win_cash / loss_per_unit,
            "planned_loss_r": loss_cash / loss_per_unit,
            "outcome": outcome, "exit_ms": exit_ms, "exit_raw_price": exit_raw,
            "funding_cash_per_unit": funding,
            "actual_cash_per_unit": win_cash if outcome == 1 else loss_cash,
            "actual_r": (win_cash if outcome == 1 else loss_cash) / loss_per_unit,
            "holding_minutes": (exit_ms - entry_ms) / MS_MIN,
            "path_min": path_min, "path_max": path_max,
        })
        records.append(record)
        if ordinal and ordinal % 5000 == 0:
            print(f"labeled {ordinal}/{len(candidates)}", flush=True)
    result = pd.DataFrame(records)
    if result.empty:
        raise RuntimeError("no completed candidate labels")
    return result.sort_values(["decision_ms", "symbol", "setup"]).reset_index(drop=True)


def make_model(spec: ModelSpec) -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("model", HistGradientBoostingClassifier(
            learning_rate=spec.learning_rate, max_leaf_nodes=spec.max_leaf_nodes,
            min_samples_leaf=spec.min_samples_leaf,
            l2_regularization=spec.l2_regularization, max_iter=180,
            early_stopping=True, validation_fraction=0.15, n_iter_no_change=20,
            random_state=73017,
        )),
    ])


def recency_weights(decision_ms: pd.Series, cutoff_ms: int) -> np.ndarray:
    age_days = (cutoff_ms - decision_ms.to_numpy(dtype=np.int64)) / DAY_MS
    return np.power(0.5, np.maximum(age_days, 0.0) / 180.0)


def walk_forward_oof(candidates: pd.DataFrame, spec: ModelSpec) -> tuple[np.ndarray, dict[str, Any]]:
    prediction = np.full(len(candidates), np.nan)
    folds = [
        (utc_ms("2023-04-01T00:00:00Z"), utc_ms("2023-07-01T00:00:00Z")),
        (utc_ms("2023-07-01T00:00:00Z"), utc_ms("2023-10-01T00:00:00Z")),
        (utc_ms("2023-10-01T00:00:00Z"), EVAL_START_MS),
    ]
    details = []
    for start, end in folds:
        train = candidates[(candidates["decision_ms"] < start) & (candidates["exit_ms"] < start)]
        valid = candidates[(candidates["decision_ms"] >= start) & (candidates["decision_ms"] < end)]
        if len(train) < 300 or len(valid) < 100 or train["outcome"].nunique() < 2:
            continue
        model = make_model(spec)
        model.fit(train[FEATURE_COLUMNS], train["outcome"],
                  model__sample_weight=recency_weights(train["decision_ms"], start))
        probability = model.predict_proba(valid[FEATURE_COLUMNS])[:, 1]
        prediction[valid.index.to_numpy()] = probability
        details.append({
            "start_ms": start, "end_ms": end, "train_rows": len(train),
            "valid_rows": len(valid),
            "brier": brier_score_loss(valid["outcome"], probability),
            "log_loss": log_loss(valid["outcome"], probability, labels=[0, 1]),
        })
    mask = np.isfinite(prediction)
    if mask.sum() < 300:
        raise RuntimeError(f"insufficient OOF predictions: {int(mask.sum())}")
    summary = {
        "spec": dataclasses.asdict(spec), "folds": details, "rows": int(mask.sum()),
        "brier": brier_score_loss(candidates.loc[mask, "outcome"], prediction[mask]),
        "log_loss": log_loss(candidates.loc[mask, "outcome"], prediction[mask], labels=[0, 1]),
    }
    return prediction, summary


def choose_model(candidates: pd.DataFrame) -> tuple[ModelSpec, np.ndarray, list[dict[str, Any]]]:
    grid = [
        ModelSpec(7, 0.04, 40, 1.0), ModelSpec(7, 0.06, 70, 3.0),
        ModelSpec(15, 0.035, 50, 3.0), ModelSpec(15, 0.055, 80, 6.0),
        ModelSpec(31, 0.03, 70, 8.0), ModelSpec(31, 0.045, 100, 12.0),
    ]
    evaluated = []
    diagnostics = []
    for spec in grid:
        probability, detail = walk_forward_oof(candidates, spec)
        score = detail["log_loss"] + 0.5 * detail["brier"]
        detail["selection_score"] = score
        diagnostics.append(detail)
        evaluated.append((score, spec, probability))
        print(f"model {spec.key()} score={score:.6f}", flush=True)
    evaluated.sort(key=lambda item: item[0])
    _, spec, probability = evaluated[0]
    return spec, probability, diagnostics


def mark_price_at(data: SymbolData, timestamp_ms: int) -> float:
    times = data.mark_1m["start_time_ms"].to_numpy(dtype=np.int64)
    closes = data.mark_1m["close"].to_numpy(dtype=float)
    idx = max(0, int(np.searchsorted(times, timestamp_ms, side="left") - 1))
    while idx >= 0:
        if np.isfinite(closes[idx]):
            return float(closes[idx])
        idx -= 1
    raise RuntimeError("no mark price")


def max_drawdown(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=float)
    return float(np.min(array / np.maximum.accumulate(array) - 1.0)) if len(array) else 0.0


def concentration(pnls: Sequence[float], n: int) -> float:
    positive = np.sort(np.asarray([p for p in pnls if p > 0], dtype=float))
    return float(positive[-n:].sum() / positive.sum()) if len(positive) and positive.sum() > 0 else 1.0


def portfolio_simulation(
    candidates: pd.DataFrame, probabilities: np.ndarray,
    symbol_data: dict[str, SymbolData], config: PortfolioConfig, costs: CostModel,
    *, period_start_ms: int, period_end_ms: int, initial_nav: float = 10_000.0,
) -> dict[str, Any]:
    frame = candidates.copy()
    frame["probability"] = probabilities
    frame["expected_r"] = frame["probability"] * frame["planned_win_r"] + (1 - frame["probability"]) * frame["planned_loss_r"]
    frame = frame[
        np.isfinite(frame["probability"]) &
        (frame["decision_ms"] >= period_start_ms) & (frame["decision_ms"] < period_end_ms) &
        (frame["probability"] >= config.min_probability) &
        (frame["expected_r"] >= config.expected_r_threshold)
    ].sort_values(["decision_ms", "expected_r", "planned_rr"], ascending=[True, False, False])
    cash = initial_nav
    available_after = period_start_ms
    selected = []
    liquidations = 0
    for _, group in frame.groupby("decision_ms", sort=True):
        choice = group.iloc[0]
        if int(choice["entry_ms"]) < available_after or cash <= 0:
            continue
        direction = int(choice["direction"])
        entry = float(choice["entry_exec_price"])
        quantity = cash * config.risk_fraction / float(choice["planned_loss_per_unit"])
        quantity = min(quantity, cash * config.leverage_cap / entry)
        if quantity <= 0:
            continue
        leverage = quantity * entry / cash
        buffer = 1 / leverage - costs.maintenance_margin_rate - CostModel.bp(costs.stop_fee_bps + costs.stop_slippage_bps)
        liquidation_price = entry * (1 - buffer) if direction == 1 else entry * (1 + buffer)
        liquidated = (float(choice["path_min"]) <= liquidation_price if direction == 1
                      else float(choice["path_max"]) >= liquidation_price)
        nav_before = cash
        entry_fee = quantity * entry * CostModel.bp(costs.entry_fee_bps)
        if liquidated:
            liquidations += 1
            cash = max(0.0, cash - entry_fee - 0.995 * nav_before)
            exit_exec = liquidation_price
            outcome = "liquidation"
        else:
            if int(choice["outcome"]) == 1:
                slip, fee, outcome = costs.target_slippage_bps, costs.target_fee_bps, "target"
            else:
                slip, fee, outcome = costs.stop_slippage_bps, costs.stop_fee_bps, "stop"
            exit_exec = float(choice["exit_raw_price"]) * (1 - direction * CostModel.bp(slip))
            cash = (cash - entry_fee + direction * quantity * (exit_exec - entry)
                    - quantity * exit_exec * CostModel.bp(fee)
                    + quantity * float(choice["funding_cash_per_unit"]))
        pnl = cash - nav_before
        selected.append({
            "event_id": choice["event_id"], "symbol": choice["symbol"],
            "setup": choice["setup"], "direction": direction,
            "decision_ms": int(choice["decision_ms"]), "entry_ms": int(choice["entry_ms"]),
            "exit_ms": int(choice["exit_ms"]), "entry_exec_price": entry,
            "exit_exec_price": exit_exec, "stop": float(choice["stop"]),
            "target": float(choice["target"]), "probability": float(choice["probability"]),
            "expected_r": float(choice["expected_r"]), "planned_rr": float(choice["planned_rr"]),
            "quantity": float(quantity), "effective_leverage": float(leverage),
            "nav_before": float(nav_before), "nav_after": float(cash),
            "pnl": float(pnl), "return": float(pnl / nav_before),
            "outcome": outcome, "holding_minutes": float(choice["holding_minutes"]),
        })
        available_after = int(choice["exit_ms"])

    boundaries = np.arange(period_start_ms + DAY_MS, period_end_ms + 1, DAY_MS, dtype=np.int64)
    daily = []
    for boundary in boundaries:
        completed_cash = initial_nav
        active = None
        for trade in selected:
            if trade["entry_ms"] < boundary:
                if trade["exit_ms"] <= boundary:
                    completed_cash = trade["nav_after"]
                elif trade["entry_ms"] < boundary < trade["exit_ms"]:
                    active = trade
                    completed_cash = trade["nav_before"] - trade["quantity"] * trade["entry_exec_price"] * CostModel.bp(costs.entry_fee_bps)
                    break
        nav = completed_cash
        if active:
            mark = mark_price_at(symbol_data[active["symbol"]], int(boundary))
            nav += active["direction"] * active["quantity"] * (mark - active["entry_exec_price"])
        daily.append({"timestamp_ms": int(boundary), "nav": float(nav)})
    final_nav = daily[-1]["nav"] if daily else cash
    if selected and selected[-1]["exit_ms"] <= period_end_ms:
        final_nav = cash
        if daily:
            daily[-1]["nav"] = cash
    values = [initial_nav] + [row["nav"] for row in daily]
    days = max(1, int((period_end_ms - period_start_ms) // DAY_MS))
    growth = math.exp(math.log(final_nav / initial_nav) / days) - 1 if final_nav > 0 else -1.0
    pnls = [trade["pnl"] for trade in selected]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    metrics = {
        "period_start_ms": period_start_ms, "period_end_ms": period_end_ms,
        "calendar_days": days, "initial_nav": initial_nav, "final_nav": final_nav,
        "account_multiple": final_nav / initial_nav, "geometric_daily_growth": growth,
        "max_drawdown": max_drawdown(values), "completed_trades": len(selected),
        "trades_per_calendar_day": len(selected) / days,
        "win_rate": sum(p > 0 for p in pnls) / len(pnls) if pnls else 0.0,
        "mean_trade_return": float(np.mean([t["return"] for t in selected])) if selected else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "top_1_profit_share": concentration(pnls, 1),
        "top_5_profit_share": concentration(pnls, 5),
        "top_10_profit_share": concentration(pnls, 10),
        "liquidations": liquidations,
    }
    return {"config": config.as_dict(), "metrics": metrics, "trades": selected, "daily_nav": daily}


def select_portfolio_config(
    candidates: pd.DataFrame, probabilities: np.ndarray,
    symbol_data: dict[str, SymbolData], costs: CostModel,
) -> tuple[PortfolioConfig, dict[str, Any], list[dict[str, Any]]]:
    start = int(candidates.loc[np.isfinite(probabilities), "decision_ms"].min())
    evaluated = []
    for threshold in (0.00, 0.05, 0.10, 0.18, 0.28):
        for probability in (0.50, 0.55, 0.60, 0.65):
            for risk in (0.0025, 0.005, 0.0075, 0.01, 0.015):
                for leverage in (3.0, 5.0, 8.0):
                    config = PortfolioConfig(threshold, probability, risk, leverage)
                    result = portfolio_simulation(
                        candidates, probabilities, symbol_data, config, costs,
                        period_start_ms=start, period_end_ms=EVAL_START_MS,
                    )
                    m = result["metrics"]
                    feasible = (m["completed_trades"] >= 60 and m["liquidations"] == 0
                                and abs(m["max_drawdown"]) <= 0.35 and m["top_10_profit_share"] <= 0.80)
                    objective = (m["geometric_daily_growth"]
                                 - 0.0025 * max(0, abs(m["max_drawdown"]) - 0.20)
                                 - 0.0015 * max(0, m["top_10_profit_share"] - 0.60)
                                 + 0.00015 * min(m["trades_per_calendar_day"], 1.0)
                                 - (0 if feasible else 0.001))
                    evaluated.append((feasible, m["geometric_daily_growth"], objective, config, result))
    pool = [item for item in evaluated if item[0]] or evaluated
    pool.sort(key=lambda item: (item[1], item[2]), reverse=True)
    best = pool[0]
    compact = sorted([
        {"config": item[3].as_dict(), "feasible": item[0], "objective": item[2], "metrics": item[4]["metrics"]}
        for item in evaluated
    ], key=lambda row: row["objective"], reverse=True)[:30]
    return best[3], best[4], compact


def monthly_probabilities(candidates: pd.DataFrame, spec: ModelSpec) -> tuple[np.ndarray, list[dict[str, Any]]]:
    probabilities = np.full(len(candidates), np.nan)
    diagnostics = []
    for month in pd.date_range("2024-01-01", "2024-06-01", freq="MS", tz="UTC"):
        start = int(month.timestamp() * 1000)
        end = min(int((month + pd.offsets.MonthBegin(1)).timestamp() * 1000), EVAL_END_MS)
        train = candidates[(candidates["decision_ms"] < start) & (candidates["exit_ms"] < start)]
        evaluation = candidates[(candidates["decision_ms"] >= start) & (candidates["decision_ms"] < end)]
        if len(train) < 500 or evaluation.empty or train["outcome"].nunique() < 2:
            continue
        model = make_model(spec)
        model.fit(train[FEATURE_COLUMNS], train["outcome"],
                  model__sample_weight=recency_weights(train["decision_ms"], start))
        p = model.predict_proba(evaluation[FEATURE_COLUMNS])[:, 1]
        probabilities[evaluation.index.to_numpy()] = p
        diagnostics.append({
            "month_start_ms": start, "month_end_ms": end,
            "train_rows": len(train), "eval_rows": len(evaluation),
            "train_positive_rate": float(train["outcome"].mean()),
            "prediction_mean": float(np.mean(p)), "prediction_std": float(np.std(p)),
        })
    return probabilities, diagnostics


def grouped_diagnostics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {}
    frame = pd.DataFrame(trades)
    output = {}
    for column in ("symbol", "setup", "outcome"):
        output[column] = [
            {column: key, "trades": len(group), "pnl": float(group["pnl"].sum()),
             "mean_return": float(group["return"].mean()),
             "win_rate": float((group["pnl"] > 0).mean())}
            for key, group in frame.groupby(column)
        ]
    frame["month"] = pd.to_datetime(frame["entry_ms"], unit="ms", utc=True).dt.strftime("%Y-%m")
    output["month"] = [
        {"month": key, "trades": len(group), "pnl": float(group["pnl"].sum()),
         "mean_return": float(group["return"].mean()), "win_rate": float((group["pnl"] > 0).mean())}
        for key, group in frame.groupby("month")
    ]
    return output


def self_test() -> None:
    assert StrategyConfig().fixed_latency_ms == 500
    assert CostModel.bp(5.5) == 0.00055
    assert abs(max_drawdown([100.0, 110.0, 88.0, 99.0]) + 0.2) < 1e-12
    print("SELF_TEST_OK")


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    data_root = Path(args.data_root).resolve()
    verification = verify_canonical_root(data_root)
    cfg, costs = StrategyConfig(), CostModel()
    symbol_data = {symbol: load_symbol_data(data_root, symbol) for symbol in SYMBOLS}
    features = add_cross_asset_features({symbol: build_market_features(symbol_data[symbol]) for symbol in SYMBOLS})
    candidates = generate_candidates(features, cfg)
    print(f"generated candidates={len(candidates)}", flush=True)
    labeled = label_candidates(candidates, symbol_data, cfg, costs).replace([np.inf, -np.inf], np.nan)
    labeled = labeled.dropna(subset=["planned_loss_per_unit", "planned_win_r", "planned_loss_r", "outcome", "exit_ms"]).reset_index(drop=True)
    for column in FEATURE_COLUMNS:
        if column not in labeled:
            labeled[column] = np.nan
        labeled[column] = pd.to_numeric(labeled[column], errors="coerce")
    train = labeled[(labeled["decision_ms"] < EVAL_START_MS) & (labeled["exit_ms"] < EVAL_START_MS)].copy()
    if len(train) < 1000:
        raise RuntimeError(f"too few pre-2024 labels: {len(train)}")
    spec, train_oof, model_grid = choose_model(train)
    full_oof = np.full(len(labeled), np.nan)
    full_oof[train.index.to_numpy()] = train_oof
    portfolio_config, selection_result, portfolio_grid = select_portfolio_config(
        labeled, full_oof, symbol_data, costs
    )
    evaluation_probability, monthly_models = monthly_probabilities(labeled, spec)
    evaluation = portfolio_simulation(
        labeled, evaluation_probability, symbol_data, portfolio_config, costs,
        period_start_ms=EVAL_START_MS, period_end_ms=EVAL_END_MS,
    )
    evaluation["grouped"] = grouped_diagnostics(evaluation["trades"])
    metrics = evaluation["metrics"]
    if metrics["geometric_daily_growth"] >= 0.01 and metrics["liquidations"] == 0 and metrics["completed_trades"] >= metrics["calendar_days"]:
        decision = "TARGET_BEAT_PROVISIONAL"
    elif metrics["geometric_daily_growth"] > 0 and metrics["completed_trades"] >= 60:
        decision = "POSITIVE_ALPHA_CONTINUE_SYSTEMIZATION"
    else:
        decision = "SYSTEMIZATION_DIAGNOSIS_REQUIRED"
    counts = (labeled.assign(period=np.where(labeled["decision_ms"] < EVAL_START_MS, "PRE_2024_2023", "2024_H1"))
              .groupby(["period", "symbol", "setup"]).size().rename("count").reset_index().to_dict("records"))
    summary = {
        "schema_version": 1, "system_id": "SCLD-LIVE-INDEPENDENT-V1", "decision": decision,
        "independence_contract": {
            "reused": ["canonical Bybit data shards", "scripts.market_data.load_canonical_bybit"],
            "not_reused": ["prior strategy code", "prior feature code", "prior model code",
                           "prior backtest code", "prior execution/risk code", "prior research results for selection"],
        },
        "strategy_config": dataclasses.asdict(cfg), "cost_model": dataclasses.asdict(costs),
        "data_verification": verification, "candidate_rows": len(labeled),
        "candidate_counts": counts, "pre_2024_label_rows": len(train),
        "selected_model": dataclasses.asdict(spec), "model_grid": model_grid,
        "selected_portfolio_config": portfolio_config.as_dict(),
        "pre_2024_oof_selection": selection_result, "portfolio_grid_top30": portfolio_grid,
        "monthly_model_updates": monthly_models, "evaluation_2024_h1": evaluation,
        "runtime_seconds": time.time() - started,
    }
    (output / "RUN_SUMMARY.json").write_text(
        json.dumps(json_safe(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    labeled.to_parquet(output / "CANDIDATES.parquet", index=False)
    pd.DataFrame(evaluation["trades"]).to_csv(output / "TRADES_2024_H1.csv", index=False)
    pd.DataFrame(evaluation["daily_nav"]).to_csv(output / "DAILY_NAV_2024_H1.csv", index=False)
    print(json.dumps(json_safe({
        "system_id": summary["system_id"], "decision": decision,
        "candidate_rows": len(labeled), "selected_model": summary["selected_model"],
        "selected_portfolio_config": summary["selected_portfolio_config"],
        "pre_2024_oof_metrics": selection_result["metrics"],
        "evaluation_2024_h1_metrics": metrics,
        "runtime_seconds": summary["runtime_seconds"],
    }), ensure_ascii=False, indent=2), flush=True)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="artifact/canonical")
    parser.add_argument("--output", default="artifact/scld-live-v1")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        self_test()
    else:
        run(args)


if __name__ == "__main__":
    main()
