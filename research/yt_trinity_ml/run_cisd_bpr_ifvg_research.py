#!/usr/bin/env python3
"""Causal CISD/BPR/IFVG action-value research on Bybit linear perpetuals.

Economic hypothesis
-------------------
A completed external-liquidity raid is not itself an entry.  The event becomes
tradable only after opposing delivery breaks the origin of the raid leg (CISD)
and creates either (a) an overlap of opposite fair-value gaps (BPR), or (b) a
confirmed inversion of the prior opposing FVG.  The ML layer estimates the
value of crossing after confirmation versus resting at the causal zone.

The script freezes the structural generator and model/update method before
looking at 2023 account outcomes.  It opens 2024H1 only when the selected 2023
after-cost continuous account has positive geometric growth.  The 1-minute
replay remains a coarse economic screen and is not rankable until corpus binding
and event-tape replay are complete.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import hashlib
import json
import math
import os
import random
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression

from system.coarse import CoarseEventReplay, CoarseExecutionConfig, CoarseLabeler
from system.core import EventCandidate, FeatureConfig, RiskConfig, build_causal_features
from system.metrics import summarize_account
from system.policy import PolicyDecision


SYMBOLS = ("BTCUSDT", "ETHUSDT")
API_BASES = (
    "https://api.bybit.com",
    "https://api.bytick.com",
    "https://api.bybitglobal.com",
)
INTERVAL_MS = 60_000
DEFAULT_EXECUTION = CoarseExecutionConfig(
    activation_latency_ms=500,
    maker_fee_rate=0.0002,
    taker_fee_rate=0.00055,
    market_slippage_bps=2.0,
    stop_slippage_bps=4.0,
    passive_requires_trade_through=True,
    minimum_spread_bps=0.5,
)


class AlphaFamily(str, Enum):
    CISD_BPR_IFVG_REVERSAL = "CISD_BPR_IFVG_REVERSAL"


VARIANT_CODE = {"BPR": 1.0, "IFVG": 2.0, "CISD_FVG": 3.0}
VARIANT_SETS = {
    "BPR_ONLY": frozenset({"BPR"}),
    "BPR_IFVG": frozenset({"BPR", "IFVG"}),
    "ALL_CAUSAL_ZONES": frozenset({"BPR", "IFVG", "CISD_FVG"}),
}


@dataclass(frozen=True)
class ModelSpec:
    name: str
    max_leaf_nodes: int
    min_samples_leaf: int
    l2_regularization: float
    confidence_penalty: float
    update_cadence_days: int = 28
    activation_lag_minutes: int = 15


MODEL_SPECS = (
    ModelSpec("SHALLOW", 7, 60, 2.0, 0.20),
    ModelSpec("MEDIUM", 15, 35, 1.5, 0.35),
    ModelSpec("LOCAL_STRICT", 31, 24, 2.5, 0.55),
)


@dataclass(frozen=True)
class ActionEstimate:
    action: PolicyDecision
    mean_net_r: float
    q25_net_r: float
    positive_probability: float
    distribution_net_r: float
    residual_scale: float


@dataclass(frozen=True)
class PredictionRecord:
    candidate: EventCandidate
    estimates: tuple[ActionEstimate, ...]


@dataclass(frozen=True)
class ActionScored:
    candidate: EventCandidate
    win_probability: float
    expected_net_r: float
    passive_fill_probability: float
    expected_log_growth: float
    lower_confidence_score: float
    chosen_action: PolicyDecision


class FixedActionPolicy:
    """Select the highest positive precomputed action value in the global slot."""

    def choose(self, scored_candidates: Iterable[ActionScored], slot_available: bool):
        if not slot_available:
            return SimpleNamespace(action=PolicyDecision.ABSTAIN, scored=None, reason="global slot occupied")
        rows = [row for row in scored_candidates if np.isfinite(row.lower_confidence_score)]
        rows = [row for row in rows if row.lower_confidence_score > 0]
        if not rows:
            return SimpleNamespace(action=PolicyDecision.ABSTAIN, scored=None, reason="no positive lower action value")
        selected = max(
            rows,
            key=lambda row: (
                row.lower_confidence_score,
                row.expected_log_growth,
                row.expected_net_r,
                row.candidate.symbol,
            ),
        )
        return SimpleNamespace(action=selected.chosen_action, scored=selected, reason="highest positive causal action value")


def canonical_json(value: Any) -> str:
    def convert(item: Any) -> Any:
        if dataclasses.is_dataclass(item):
            return convert(dataclasses.asdict(item))
        if isinstance(item, pd.Timestamp):
            return item.isoformat()
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, np.generic):
            return item.item()
        if isinstance(item, Mapping):
            return {str(key): convert(val) for key, val in item.items()}
        if isinstance(item, (tuple, list, set, frozenset)):
            return [convert(val) for val in item]
        if isinstance(item, float) and not np.isfinite(item):
            return None
        return item

    return json.dumps(convert(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp


class BybitClient:
    def __init__(self) -> None:
        self.sessions = {base: requests.Session() for base in API_BASES}
        self.preferred_base: str | None = None

    def get(self, path: str, params: Mapping[str, Any], attempts: int = 8) -> dict[str, Any]:
        bases = ([self.preferred_base] if self.preferred_base else []) + [base for base in API_BASES if base != self.preferred_base]
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            base = bases[(attempt - 1) % len(bases)]
            try:
                response = self.sessions[base].get(
                    base + path,
                    params=params,
                    headers={"User-Agent": "SMC-ICT-2-LIVE/1.0", "Accept": "application/json"},
                    timeout=35,
                )
                if response.status_code == 429:
                    time.sleep(min(20.0, 1.5 * attempt + random.random()))
                    continue
                response.raise_for_status()
                payload = response.json()
                if int(payload.get("retCode", -1)) != 0:
                    raise RuntimeError(f"Bybit retCode={payload.get('retCode')} retMsg={payload.get('retMsg')}")
                self.preferred_base = base
                return payload
            except Exception as exc:
                last_error = exc
                time.sleep(min(12.0, 0.7 * attempt + random.random()))
        raise RuntimeError(f"Bybit request failed: {path} {params}: {last_error}")


def fetch_minute_klines(
    symbol: str,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    cache_dir: Path,
) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{symbol}_1m_{start:%Y%m%d}_{end_exclusive:%Y%m%d}.parquet"
    if cache_path.exists():
        frame = pd.read_parquet(cache_path)
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True)).as_unit("ns")
        frame["bar_start"] = pd.to_datetime(frame["bar_start"], utc=True)
        return frame.sort_index()

    client = BybitClient()
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end_exclusive.timestamp() * 1000)
    rows: dict[int, list[Any]] = {}
    cursor = start_ms
    request_count = 0
    while cursor < end_ms:
        window_end = min(end_ms - 1, cursor + 999 * INTERVAL_MS)
        payload = client.get(
            "/v5/market/kline",
            {
                "category": "linear",
                "symbol": symbol,
                "interval": "1",
                "start": cursor,
                "end": window_end,
                "limit": 1000,
            },
        )
        items = payload.get("result", {}).get("list", []) or []
        for item in items:
            if not isinstance(item, Sequence) or len(item) < 7:
                continue
            timestamp_ms = int(item[0])
            if start_ms <= timestamp_ms < end_ms:
                rows[timestamp_ms] = list(item)
        cursor = window_end + 1
        request_count += 1
        if request_count % 100 == 0:
            print(json.dumps({"stage": "download", "symbol": symbol, "requests": request_count, "bars": len(rows)}), flush=True)
        time.sleep(0.025)
    if not rows:
        raise RuntimeError(f"no Bybit klines returned for {symbol}")
    ordered = [rows[key] for key in sorted(rows)]
    frame = pd.DataFrame(
        {
            "start_ms": [int(row[0]) for row in ordered],
            "open": [float(row[1]) for row in ordered],
            "high": [float(row[2]) for row in ordered],
            "low": [float(row[3]) for row in ordered],
            "close": [float(row[4]) for row in ordered],
            "volume": [float(row[5]) for row in ordered],
            "turnover": [float(row[6]) for row in ordered],
        }
    )
    bar_start = pd.to_datetime(frame.pop("start_ms"), unit="ms", utc=True).as_unit("ns")
    frame["bar_start"] = bar_start
    frame["mark_close"] = frame["close"]
    frame["spread_bps"] = DEFAULT_EXECUTION.minimum_spread_bps
    frame.index = bar_start + pd.Timedelta(minutes=1)
    frame.index.name = "available_at"
    frame = frame.sort_index()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cache_path)
    return frame


def fetch_funding(
    symbol: str,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    cache_dir: Path,
) -> dict[tuple[str, pd.Timestamp], float]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{symbol}_funding_{start:%Y%m%d}_{end_exclusive:%Y%m%d}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return {(symbol, utc_timestamp(row["timestamp"])): float(row["rate"]) for row in payload}
    client = BybitClient()
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end_exclusive.timestamp() * 1000)
    cursor = start_ms
    found: dict[int, float] = {}
    window = 45 * 24 * 60 * 60 * 1000
    while cursor < end_ms:
        window_end = min(end_ms - 1, cursor + window)
        payload = client.get(
            "/v5/market/funding/history",
            {
                "category": "linear",
                "symbol": symbol,
                "startTime": cursor,
                "endTime": window_end,
                "limit": 200,
            },
        )
        for row in payload.get("result", {}).get("list", []) or []:
            timestamp_ms = int(row["fundingRateTimestamp"])
            if start_ms <= timestamp_ms < end_ms:
                found[timestamp_ms] = float(row["fundingRate"])
        cursor = window_end + 1
        time.sleep(0.08)
    serial = [
        {"timestamp": pd.Timestamp(timestamp_ms, unit="ms", tz="UTC").isoformat(), "rate": rate}
        for timestamp_ms, rate in sorted(found.items())
    ]
    cache_path.write_text(json.dumps(serial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {(symbol, utc_timestamp(row["timestamp"])): float(row["rate"]) for row in serial}


def resample_decision(frame: pd.DataFrame) -> pd.DataFrame:
    source = frame.set_index("bar_start", drop=False).sort_index()
    grouped = source.resample("5min", label="left", closed="left")
    decision = grouped.agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "turnover": "sum",
            "mark_close": "last",
            "spread_bps": "max",
        }
    ).dropna(subset=["open", "high", "low", "close"])
    decision["bar_start"] = decision.index
    decision.index = pd.DatetimeIndex(decision.index + pd.Timedelta(minutes=5)).as_unit("ns")
    decision.index.name = "available_at"
    return decision.sort_index()


def numeric_features(row: pd.Series) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in row.items():
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value):
            result[str(key)] = float(value)
    return result


def external_levels(row: pd.Series, side: int, price: float) -> list[float]:
    if side > 0:
        candidates = (row.get("last_swing_high"), row.get("previous_day_high"), row.get("previous_week_high"))
        return sorted(float(value) for value in candidates if pd.notna(value) and float(value) > price)
    candidates = (row.get("last_swing_low"), row.get("previous_day_low"), row.get("previous_week_low"))
    return sorted((float(value) for value in candidates if pd.notna(value) and float(value) < price), reverse=True)


def prior_fvg(features: pd.DataFrame, position: int, bearish: bool, lookback: int = 18) -> tuple[int, float, float] | None:
    start = max(2, position - lookback)
    for index in range(position - 1, start - 1, -1):
        row = features.iloc[index]
        if bearish:
            lower, upper = row.get("bear_fvg_lower"), row.get("bear_fvg_upper")
        else:
            lower, upper = row.get("bull_fvg_lower"), row.get("bull_fvg_upper")
        if pd.notna(lower) and pd.notna(upper) and float(lower) < float(upper):
            return index, float(lower), float(upper)
    return None


def delivery_origin(features: pd.DataFrame, sweep_position: int, bullish_reversal: bool) -> float | None:
    start = max(0, sweep_position - 7)
    for index in range(sweep_position, start - 1, -1):
        row = features.iloc[index]
        if bullish_reversal and float(row["close"]) < float(row["open"]):
            return float(row["open"])
        if not bullish_reversal and float(row["close"]) > float(row["open"]):
            return float(row["open"])
    return None


def find_sweep(features: pd.DataFrame, position: int, bullish_reversal: bool) -> tuple[int, float, float] | None:
    start = max(2, position - 7)
    best: tuple[int, float, float] | None = None
    for index in range(start, position):
        row = features.iloc[index]
        atr = float(row.get("atr")) if pd.notna(row.get("atr")) else math.nan
        if not np.isfinite(atr) or atr <= 0:
            continue
        buffer = 0.025 * atr
        if bullish_reversal:
            levels = [row.get("last_swing_low"), row.get("previous_day_low"), row.get("previous_week_low")]
            valid = [float(level) for level in levels if pd.notna(level)]
            swept = [level for level in valid if float(row["low"]) < level - buffer]
            if swept:
                level = min(swept)
                depth = (level - float(row["low"])) / atr
                if best is None or depth > best[2]:
                    best = (index, level, depth)
        else:
            levels = [row.get("last_swing_high"), row.get("previous_day_high"), row.get("previous_week_high")]
            valid = [float(level) for level in levels if pd.notna(level)]
            swept = [level for level in valid if float(row["high"]) > level + buffer]
            if swept:
                level = max(swept)
                depth = (float(row["high"]) - level) / atr
                if best is None or depth > best[2]:
                    best = (index, level, depth)
    return best


def make_candidate(
    features: pd.DataFrame,
    symbol: str,
    position: int,
    bullish_reversal: bool,
    last_key: dict[tuple[int, str], int],
) -> EventCandidate | None:
    row = features.iloc[position]
    atr = float(row.get("atr")) if pd.notna(row.get("atr")) else math.nan
    if not np.isfinite(atr) or atr <= 0:
        return None
    sweep = find_sweep(features, position, bullish_reversal)
    if sweep is None:
        return None
    sweep_position, swept_level, sweep_depth = sweep
    side = 1 if bullish_reversal else -1
    origin = delivery_origin(features, sweep_position, bullish_reversal)
    if origin is None:
        return None
    body_atr = float(row.get("body_atr")) if pd.notna(row.get("body_atr")) else 0.0
    close = float(row["close"])
    if bullish_reversal:
        if body_atr < 0.55 or close <= origin or close <= float(features.iloc[position - 1]["high"]):
            return None
        current_lower, current_upper = row.get("bull_fvg_lower"), row.get("bull_fvg_upper")
        opposite = prior_fvg(features, position, bearish=True)
    else:
        if body_atr > -0.55 or close >= origin or close >= float(features.iloc[position - 1]["low"]):
            return None
        current_lower, current_upper = row.get("bear_fvg_lower"), row.get("bear_fvg_upper")
        opposite = prior_fvg(features, position, bearish=False)
    if pd.isna(current_lower) or pd.isna(current_upper):
        return None
    current_lower = float(current_lower)
    current_upper = float(current_upper)
    if current_lower >= current_upper:
        return None

    variant = "CISD_FVG"
    zone_lower, zone_upper = current_lower, current_upper
    opposite_age = math.nan
    if opposite is not None:
        opposite_position, opposite_lower, opposite_upper = opposite
        opposite_age = float(position - opposite_position)
        overlap_lower = max(current_lower, opposite_lower)
        overlap_upper = min(current_upper, opposite_upper)
        if overlap_lower < overlap_upper:
            variant = "BPR"
            zone_lower, zone_upper = overlap_lower, overlap_upper
        else:
            inverted = close > opposite_upper if bullish_reversal else close < opposite_lower
            if inverted:
                variant = "IFVG"
                zone_lower, zone_upper = opposite_lower, opposite_upper
    if (side, variant) in last_key and position - last_key[(side, variant)] < 8:
        return None
    entry = (zone_lower + zone_upper) / 2
    sweep_row = features.iloc[sweep_position]
    buffer = 0.05 * atr
    stop = float(sweep_row["low"] - buffer) if bullish_reversal else float(sweep_row["high"] + buffer)
    targets = external_levels(row, side, close)
    if not targets:
        return None
    target = targets[0]
    protective = side * (entry - stop)
    reward = side * (target - entry)
    if protective <= 0 or reward <= 0:
        return None
    raw_rr = reward / protective
    minimum_rr = 1.45 if variant == "BPR" else 1.65 if variant == "IFVG" else 2.0
    if raw_rr < minimum_rr:
        return None
    zone_distance = side * (close - entry) / atr
    if zone_distance < -0.25 or zone_distance > 2.5:
        return None

    features_row = numeric_features(row)
    features_row.update(
        {
            "alpha_cisd_bpr_ifvg": 1.0,
            "variant_bpr": float(variant == "BPR"),
            "variant_ifvg": float(variant == "IFVG"),
            "variant_cisd_fvg": float(variant == "CISD_FVG"),
            "variant_code": VARIANT_CODE[variant],
            "side": float(side),
            "sweep_depth_atr": float(sweep_depth),
            "sweep_age_bars": float(position - sweep_position),
            "cisd_break_atr": side * (close - origin) / atr,
            "zone_width_atr": (zone_upper - zone_lower) / atr,
            "zone_distance_atr": zone_distance,
            "opposite_fvg_age_bars": opposite_age,
            "raw_reward_risk": raw_rr,
            "stop_distance_fraction": protective / max(entry, 1e-12),
            "target_distance_fraction": reward / max(entry, 1e-12),
            "symbol_btc": float(symbol == "BTCUSDT"),
            "symbol_eth": float(symbol == "ETHUSDT"),
            "decision_position": float(position),
        }
    )
    last_key[(side, variant)] = position
    return EventCandidate(
        timestamp=pd.Timestamp(features.index[position]),
        symbol=symbol,
        family=AlphaFamily.CISD_BPR_IFVG_REVERSAL,  # type: ignore[arg-type]
        side=side,
        decision_price=close,
        entry_reference=entry,
        stop_reference=stop,
        target_reference=target,
        structural_level=swept_level,
        feature_row=features_row,
    )


def generate_candidates(frame: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, list[EventCandidate]]:
    feature_config = FeatureConfig(
        atr_window=14,
        rsi_window=14,
        fast_ema=20,
        slow_ema=50,
        long_ema=200,
        volume_window=50,
        pivot_left=3,
        pivot_right=3,
        equal_tolerance_atr=0.12,
        displacement_body_atr=0.70,
        sweep_buffer_atr=0.025,
        retest_tolerance_atr=0.15,
    )
    features = build_causal_features(frame, feature_config)
    candidates: list[EventCandidate] = []
    last_key: dict[tuple[int, str], int] = {}
    for position in range(205, len(features)):
        for bullish_reversal in (True, False):
            candidate = make_candidate(features, symbol, position, bullish_reversal, last_key)
            if candidate is not None:
                candidates.append(candidate)
    candidates.sort(key=lambda row: (row.timestamp, row.symbol, row.side, row.entry_reference))
    return features, candidates


def candidate_vector(candidate: EventCandidate) -> dict[str, float]:
    row = {
        key: float(value)
        for key, value in candidate.feature_row.items()
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)
    }
    row.update(
        {
            "side": float(candidate.side),
            "raw_reward_risk": candidate.target_distance / max(candidate.stop_distance, 1e-12),
            "symbol_btc": float(candidate.symbol == "BTCUSDT"),
            "symbol_eth": float(candidate.symbol == "ETHUSDT"),
        }
    )
    return row


def build_action_labels(
    candidates: Sequence[EventCandidate],
    execution_frames: Mapping[str, pd.DataFrame],
    config: CoarseExecutionConfig,
) -> pd.DataFrame:
    labelers = {symbol: CoarseLabeler(frame, config) for symbol, frame in execution_frames.items()}
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        labeler = labelers[candidate.symbol]
        base = candidate_vector(candidate)
        variant = "BPR" if base.get("variant_bpr") else "IFVG" if base.get("variant_ifvg") else "CISD_FVG"
        for action_name, passive in (("MARKET", False), ("PASSIVE", True)):
            outcome = labeler.label(candidate, passive=passive)
            if passive and outcome.status == "CANCELLED_BEFORE_FILL" and outcome.event_end is not None:
                net_r = 0.0
            elif outcome.net_r is not None and outcome.event_end is not None and outcome.status in {"TARGET", "STOP"}:
                net_r = float(outcome.net_r)
            else:
                continue
            row: dict[str, Any] = {
                "event_start": candidate.timestamp,
                "event_end": outcome.event_end,
                "symbol": candidate.symbol,
                "variant": variant,
                "action_name": action_name,
                "action_passive": float(passive),
                "net_r": net_r,
                "positive": int(net_r > 0),
                "filled": int(outcome.entry_time is not None),
                "outcome_status": outcome.status,
            }
            row.update(base)
            rows.append(row)
        if index % 1000 == 0:
            print(json.dumps({"stage": "labels", "candidates": index, "rows": len(rows)}), flush=True)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["event_end", "event_start", "symbol", "action_name"], kind="stable").reset_index(drop=True)


class FittedActionModel:
    def __init__(self, action: PolicyDecision, spec: ModelSpec) -> None:
        self.action = action
        self.spec = spec
        self.feature_names: list[str] = []
        self.mean_model: HistGradientBoostingRegressor | None = None
        self.q25_model: HistGradientBoostingRegressor | None = None
        self.probability_model: HistGradientBoostingClassifier | None = None
        self.calibrator: IsotonicRegression | None = None
        self.constant_probability = 0.0
        self.residual_scale = 1.0
        self.median_win = 1.0
        self.median_nonwin = -1.0

    def fit(self, rows: pd.DataFrame) -> "FittedActionModel":
        ordered = rows.sort_values("event_end", kind="stable").reset_index(drop=True)
        minimum = max(120, self.spec.min_samples_leaf * 4)
        if len(ordered) < minimum:
            raise ValueError(f"insufficient action rows: {len(ordered)} < {minimum}")
        split = min(max(int(len(ordered) * 0.80), 1), len(ordered) - 1)
        calibration = ordered.iloc[split:].copy()
        calibration_start = pd.to_datetime(calibration["event_start"], utc=True).min()
        base = ordered.iloc[:split].copy()
        base = base[pd.to_datetime(base["event_end"], utc=True) < calibration_start]
        if len(base) < max(80, self.spec.min_samples_leaf * 2):
            raise ValueError("insufficient purged base rows")
        excluded = {
            "event_start", "event_end", "symbol", "variant", "action_name", "net_r",
            "positive", "filled", "outcome_status", "decision_position",
        }
        self.feature_names = [
            name for name in ordered.columns
            if name not in excluded and pd.api.types.is_numeric_dtype(ordered[name])
        ]
        if not self.feature_names:
            raise ValueError("no numeric action features")
        x_base = base[self.feature_names].replace([np.inf, -np.inf], np.nan)
        x_cal = calibration[self.feature_names].replace([np.inf, -np.inf], np.nan)
        kwargs = dict(
            learning_rate=0.05,
            max_leaf_nodes=self.spec.max_leaf_nodes,
            max_iter=260,
            min_samples_leaf=self.spec.min_samples_leaf,
            l2_regularization=self.spec.l2_regularization,
            random_state=20260727,
        )
        self.mean_model = HistGradientBoostingRegressor(loss="squared_error", **kwargs).fit(x_base, base["net_r"].astype(float))
        self.q25_model = HistGradientBoostingRegressor(loss="quantile", quantile=0.25, **kwargs).fit(x_base, base["net_r"].astype(float))
        positives = base["positive"].astype(int)
        self.constant_probability = float(positives.mean())
        if positives.nunique() >= 2:
            self.probability_model = HistGradientBoostingClassifier(**kwargs).fit(x_base, positives)
            raw = self.probability_model.predict_proba(x_cal)
            classes = np.asarray(self.probability_model.classes_)
            positive_index = np.flatnonzero(classes == 1)
            raw_positive = raw[:, int(positive_index[0])] if positive_index.size else np.zeros(len(x_cal))
            if calibration["positive"].nunique() >= 2 and np.unique(raw_positive).size >= 2:
                self.calibrator = IsotonicRegression(out_of_bounds="clip").fit(raw_positive, calibration["positive"].astype(int))
        calibration_prediction = self.mean_model.predict(x_cal)
        residual = calibration["net_r"].astype(float).to_numpy() - calibration_prediction
        self.residual_scale = max(0.05, float(np.sqrt(np.mean(np.square(residual)))))
        wins = ordered.loc[ordered["net_r"] > 0, "net_r"].astype(float)
        nonwins = ordered.loc[ordered["net_r"] <= 0, "net_r"].astype(float)
        self.median_win = float(wins.median()) if not wins.empty else 1.0
        self.median_nonwin = float(nonwins.median()) if not nonwins.empty else -1.0
        return self

    def predict(self, candidate: EventCandidate) -> ActionEstimate:
        assert self.mean_model is not None and self.q25_model is not None
        values = candidate_vector(candidate)
        values["action_passive"] = float(self.action == PolicyDecision.PASSIVE_RETEST)
        vector = pd.DataFrame([{name: values.get(name, np.nan) for name in self.feature_names}]).replace([np.inf, -np.inf], np.nan)
        mean_net_r = float(self.mean_model.predict(vector)[0])
        q25_net_r = float(self.q25_model.predict(vector)[0])
        probability = self.constant_probability
        if self.probability_model is not None:
            raw = self.probability_model.predict_proba(vector)
            classes = np.asarray(self.probability_model.classes_)
            positive_index = np.flatnonzero(classes == 1)
            probability = float(raw[0, int(positive_index[0])]) if positive_index.size else 0.0
            if self.calibrator is not None:
                probability = float(self.calibrator.predict([probability])[0])
        probability = float(np.clip(probability, 0.0, 1.0))
        distribution_net_r = probability * self.median_win + (1 - probability) * self.median_nonwin
        return ActionEstimate(
            action=self.action,
            mean_net_r=mean_net_r,
            q25_net_r=q25_net_r,
            positive_probability=probability,
            distribution_net_r=distribution_net_r,
            residual_scale=self.residual_scale,
        )


@dataclass(frozen=True)
class ModelBundle:
    market: FittedActionModel | None
    passive: FittedActionModel | None
    training_rows: int
    latest_label_end: pd.Timestamp


def fit_bundle(rows: pd.DataFrame, asof: pd.Timestamp, spec: ModelSpec) -> ModelBundle | None:
    eligible = rows[pd.to_datetime(rows["event_end"], utc=True) <= asof].copy()
    if eligible.empty:
        return None
    models: dict[str, FittedActionModel | None] = {"MARKET": None, "PASSIVE": None}
    for action_name, action in (("MARKET", PolicyDecision.MARKETABLE), ("PASSIVE", PolicyDecision.PASSIVE_RETEST)):
        action_rows = eligible[eligible["action_name"] == action_name].copy()
        try:
            models[action_name] = FittedActionModel(action, spec).fit(action_rows)
        except ValueError:
            models[action_name] = None
    if models["MARKET"] is None and models["PASSIVE"] is None:
        return None
    return ModelBundle(
        market=models["MARKET"],
        passive=models["PASSIVE"],
        training_rows=len(eligible),
        latest_label_end=pd.Timestamp(eligible["event_end"].max()),
    )


def walk_forward_predictions(
    candidates: Sequence[EventCandidate],
    labels: pd.DataFrame,
    evaluation_start: pd.Timestamp,
    evaluation_end: pd.Timestamp,
    spec: ModelSpec,
    allowed_variants: frozenset[str],
) -> tuple[list[PredictionRecord], list[dict[str, Any]]]:
    ordered = [
        candidate for candidate in candidates
        if evaluation_start <= candidate.timestamp < evaluation_end
        and (
            "BPR" if candidate.feature_row.get("variant_bpr") else
            "IFVG" if candidate.feature_row.get("variant_ifvg") else "CISD_FVG"
        ) in allowed_variants
    ]
    ordered.sort(key=lambda row: (row.timestamp, row.symbol, row.side, row.entry_reference))
    if not ordered:
        return [], []
    lag = pd.Timedelta(minutes=spec.activation_lag_minutes)
    schedule = list(pd.date_range(evaluation_start.floor("D"), evaluation_end, freq=f"{spec.update_cadence_days}D", tz="UTC"))
    schedule_index = 0
    active = fit_bundle(labels, evaluation_start - lag, spec)
    ledger: list[dict[str, Any]] = []
    if active is not None:
        ledger.append({
            "update_started_at": (evaluation_start - lag).isoformat(),
            "model_activated_at": evaluation_start.isoformat(),
            "training_rows": active.training_rows,
            "latest_label_end": active.latest_label_end.isoformat(),
        })
    pending: tuple[pd.Timestamp, ModelBundle, pd.Timestamp] | None = None
    predictions: list[PredictionRecord] = []
    for candidate in ordered:
        while schedule_index < len(schedule) and schedule[schedule_index] <= candidate.timestamp:
            update_start = schedule[schedule_index]
            bundle = fit_bundle(labels, update_start, spec)
            if bundle is not None:
                pending = (update_start + lag, bundle, update_start)
            schedule_index += 1
        if pending is not None and pending[0] <= candidate.timestamp:
            activated, active, update_start = pending
            ledger.append({
                "update_started_at": update_start.isoformat(),
                "model_activated_at": activated.isoformat(),
                "training_rows": active.training_rows,
                "latest_label_end": active.latest_label_end.isoformat(),
            })
            pending = None
        if active is None:
            continue
        estimates: list[ActionEstimate] = []
        if active.market is not None:
            estimates.append(active.market.predict(candidate))
        if active.passive is not None:
            estimates.append(active.passive.predict(candidate))
        if estimates:
            predictions.append(PredictionRecord(candidate, tuple(estimates)))
    return predictions, ledger


def score_predictions(
    predictions: Sequence[PredictionRecord],
    risk_fraction: float,
    confidence_penalty: float,
) -> list[ActionScored]:
    result: list[ActionScored] = []
    for record in predictions:
        alternatives: list[ActionScored] = []
        for estimate in record.estimates:
            blended = 0.65 * estimate.mean_net_r + 0.35 * estimate.distribution_net_r
            residual_lower = blended - confidence_penalty * estimate.residual_scale
            lower_net_r = 0.55 * residual_lower + 0.45 * estimate.q25_net_r
            expected_return = risk_fraction * blended
            lower_return = risk_fraction * lower_net_r
            expected_log = math.log1p(expected_return) if expected_return > -1 else -math.inf
            lower_log = math.log1p(lower_return) if lower_return > -1 else -math.inf
            alternatives.append(
                ActionScored(
                    candidate=record.candidate,
                    win_probability=estimate.positive_probability,
                    expected_net_r=blended,
                    passive_fill_probability=1.0 if estimate.action == PolicyDecision.PASSIVE_RETEST else 0.0,
                    expected_log_growth=expected_log,
                    lower_confidence_score=lower_log,
                    chosen_action=estimate.action,
                )
            )
        if alternatives:
            result.append(max(alternatives, key=lambda row: (row.lower_confidence_score, row.expected_log_growth)))
    return result


def replay_predictions(
    predictions: Sequence[PredictionRecord],
    execution_frames: Mapping[str, pd.DataFrame],
    funding: Mapping[tuple[str, pd.Timestamp], float],
    evaluation_start: pd.Timestamp,
    evaluation_end: pd.Timestamp,
    risk_fraction: float,
    maximum_leverage: float,
    confidence_penalty: float,
) -> tuple[dict[str, Any], Any]:
    scored = score_predictions(predictions, risk_fraction, confidence_penalty)
    instrument_rules = {"BTCUSDT": (0.001, 0.001), "ETHUSDT": (0.01, 0.01)}
    risk = RiskConfig(
        risk_fraction=risk_fraction,
        maximum_leverage=maximum_leverage,
        quantity_step=0.001,
        minimum_quantity=0.0,
        maintenance_margin_fraction=0.005,
        liquidation_buffer_fraction=0.0025,
    )
    replay = CoarseEventReplay(execution_frames, DEFAULT_EXECUTION)
    account = replay.run(
        scored,
        FixedActionPolicy(),
        risk,
        evaluation_start,
        evaluation_end,
        initial_nav=10_000.0,
        funding=funding,
        instrument_rules=instrument_rules,
    )
    final_mark = 0.0
    if account.position is not None:
        symbol = account.position.candidate.symbol
        eligible = execution_frames[symbol].loc[execution_frames[symbol]["bar_start"] < evaluation_end]
        if not eligible.empty:
            final_mark = float(eligible.iloc[-1].get("mark_close", eligible.iloc[-1]["close"]))
    else:
        for symbol in SYMBOLS:
            eligible = execution_frames[symbol].loc[execution_frames[symbol]["bar_start"] < evaluation_end]
            if not eligible.empty:
                final_mark = float(eligible.iloc[-1].get("mark_close", eligible.iloc[-1]["close"]))
                break
    metrics = summarize_account(account, evaluation_start, evaluation_end, final_mark)
    payload = metrics.as_dict() if hasattr(metrics, "as_dict") else dataclasses.asdict(metrics)
    payload.update(
        {
            "scored_candidate_count": len(scored),
            "positive_lower_score_count": sum(row.lower_confidence_score > 0 for row in scored),
            "risk_fraction": risk_fraction,
            "maximum_leverage": maximum_leverage,
            "confidence_penalty": confidence_penalty,
        }
    )
    return payload, account


def result_key(result: Mapping[str, Any]) -> tuple[float, float, float]:
    growth = float(result.get("geometric_daily_growth") or -math.inf)
    multiple = float(result.get("account_multiple") or 0.0)
    drawdown = float(result.get("maximum_drawdown") or 1.0)
    invalid = bool(result.get("liquidated_or_invalid"))
    if invalid:
        return (-math.inf, -math.inf, -math.inf)
    return growth, multiple, -drawdown


def run(args: argparse.Namespace) -> dict[str, Any]:
    data_start = utc_timestamp(args.data_start)
    pre2024_start = utc_timestamp(args.pre2024_start)
    official_start = utc_timestamp(args.official_start)
    official_end = utc_timestamp(args.official_end_exclusive)
    if not data_start < pre2024_start < official_start < official_end:
        raise ValueError("date ordering must be data_start < pre2024_start < official_start < official_end")
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SYMBOLS)) as pool:
        future_frames = {
            symbol: pool.submit(fetch_minute_klines, symbol, data_start, official_end, args.cache_dir)
            for symbol in SYMBOLS
        }
        execution_frames = {symbol: future.result() for symbol, future in future_frames.items()}
    funding: dict[tuple[str, pd.Timestamp], float] = {}
    for symbol in SYMBOLS:
        funding.update(fetch_funding(symbol, data_start, official_end, args.cache_dir))

    decision_frames = {symbol: resample_decision(frame) for symbol, frame in execution_frames.items()}
    all_candidates: list[EventCandidate] = []
    feature_counts: dict[str, int] = {}
    for symbol in SYMBOLS:
        features, candidates = generate_candidates(decision_frames[symbol], symbol)
        feature_counts[symbol] = len(features)
        all_candidates.extend(candidates)
    all_candidates.sort(key=lambda row: (row.timestamp, row.symbol, row.side, row.entry_reference))
    labels = build_action_labels(all_candidates, execution_frames, DEFAULT_EXECUTION)
    label_path = args.output / "CISD_BPR_IFVG_ACTION_LABELS.parquet"
    labels.to_parquet(label_path, index=False)

    basic_results: list[dict[str, Any]] = []
    prediction_cache: dict[tuple[str, str, str], tuple[list[PredictionRecord], list[dict[str, Any]]]] = {}
    for variant_name, variants in VARIANT_SETS.items():
        for spec in MODEL_SPECS:
            predictions, ledger = walk_forward_predictions(
                all_candidates,
                labels,
                pre2024_start,
                official_start,
                spec,
                variants,
            )
            prediction_cache[("PRE2024", variant_name, spec.name)] = (predictions, ledger)
            metrics, _ = replay_predictions(
                predictions,
                execution_frames,
                funding,
                pre2024_start,
                official_start,
                risk_fraction=0.01,
                maximum_leverage=5.0,
                confidence_penalty=spec.confidence_penalty,
            )
            basic_results.append(
                {
                    "identifier": f"{variant_name}_{spec.name}",
                    "variant_set": variant_name,
                    "model_spec": dataclasses.asdict(spec),
                    "prediction_count": len(predictions),
                    "update_records": ledger,
                    "metrics": metrics,
                }
            )
            print(json.dumps({"stage": "basic", "id": basic_results[-1]["identifier"], "metrics": metrics}, ensure_ascii=False), flush=True)

    selected_basic = max(basic_results, key=lambda row: result_key(row["metrics"])) if basic_results else None
    positive_basic = bool(selected_basic and float(selected_basic["metrics"].get("geometric_daily_growth") or 0.0) > 0)
    risk_results: list[dict[str, Any]] = []
    selected_risk: dict[str, Any] | None = None
    official_result: dict[str, Any] | None = None
    official_ledger: list[dict[str, Any]] = []

    if positive_basic and selected_basic is not None:
        variant_name = str(selected_basic["variant_set"])
        spec_name = str(selected_basic["model_spec"]["name"])
        spec = next(row for row in MODEL_SPECS if row.name == spec_name)
        predictions, _ = prediction_cache[("PRE2024", variant_name, spec_name)]
        for risk_fraction in (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.20):
            for leverage in (2.0, 5.0, 10.0, 20.0, 50.0, 100.0):
                metrics, _ = replay_predictions(
                    predictions,
                    execution_frames,
                    funding,
                    pre2024_start,
                    official_start,
                    risk_fraction=risk_fraction,
                    maximum_leverage=leverage,
                    confidence_penalty=spec.confidence_penalty,
                )
                risk_results.append(
                    {
                        "identifier": f"RISK_{risk_fraction:.4f}_LEV_{leverage:.0f}",
                        "risk_fraction": risk_fraction,
                        "maximum_leverage": leverage,
                        "metrics": metrics,
                    }
                )
        selected_risk = max(risk_results, key=lambda row: result_key(row["metrics"]))
        official_predictions, official_ledger = walk_forward_predictions(
            all_candidates,
            labels,
            official_start,
            official_end,
            spec,
            VARIANT_SETS[variant_name],
        )
        official_metrics, official_account = replay_predictions(
            official_predictions,
            execution_frames,
            funding,
            official_start,
            official_end,
            risk_fraction=float(selected_risk["risk_fraction"]),
            maximum_leverage=float(selected_risk["maximum_leverage"]),
            confidence_penalty=spec.confidence_penalty,
        )
        official_result = {
            "stage": "OFFICIAL_2024H1_COARSE_PENDING_EVENT_TAPE",
            "configuration": {
                "variant_set": variant_name,
                "model_spec": dataclasses.asdict(spec),
                "risk_fraction": selected_risk["risk_fraction"],
                "maximum_leverage": selected_risk["maximum_leverage"],
            },
            "prediction_count": len(official_predictions),
            "update_records": official_ledger,
            "metrics": official_metrics,
            "closed_trade_count": len(official_account.closed_trades),
        }

    summary = {
        "schema_version": 1,
        "strategy_id": "YT_TRINITY_CISD_BPR_IFVG_ACTION_VALUE_V1",
        "stage": "PRE2024_CAUSAL_COARSE_SCREEN_NOT_RANKABLE",
        "economic_hypothesis": "external liquidity execution followed by CISD delivery reversal and BPR/IFVG causal repricing",
        "data": {
            "venue": "Bybit",
            "category": "linear",
            "symbols": list(SYMBOLS),
            "data_start": data_start.isoformat(),
            "pre2024_start": pre2024_start.isoformat(),
            "official_start": official_start.isoformat(),
            "official_end_exclusive": official_end.isoformat(),
            "decision_timeframe": "5m completed bars",
            "execution_timeframe": "1m conservative stop-first",
            "feature_row_counts": feature_counts,
            "minute_row_counts": {symbol: len(frame) for symbol, frame in execution_frames.items()},
            "funding_event_count": len(funding),
        },
        "execution_contract": dataclasses.asdict(DEFAULT_EXECUTION),
        "candidate_count": len(all_candidates),
        "variant_candidate_counts": {
            name: sum(
                ("BPR" if row.feature_row.get("variant_bpr") else "IFVG" if row.feature_row.get("variant_ifvg") else "CISD_FVG") == name
                for row in all_candidates
            )
            for name in ("BPR", "IFVG", "CISD_FVG")
        },
        "action_label_count": len(labels),
        "action_label_sha256": sha256_file(label_path),
        "basic_results": basic_results,
        "selected_basic": selected_basic,
        "pre2024_positive_basic_alpha": positive_basic,
        "risk_results": risk_results,
        "selected_risk": selected_risk,
        "official_2024h1": official_result,
        "official_open_authority": bool(positive_basic),
        "rankable": False,
        "rankability_blockers": [
            "complete three-channel content corpus and audited ontology are not yet bound",
            "one-minute stop-first replay must be replaced by event-tape execution for a survivor",
            "historical observed bid/ask and depth are not present in this coarse screen",
        ],
        "decision": (
            "POSITIVE_PRE2024_OPENED_2024H1_COARSE"
            if positive_basic
            else "ECONOMIC_FAIL_SWITCH_ALPHA"
        ),
    }
    summary_path = args.output / "RUN_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "RUN_SUMMARY.sha256").write_text(f"{sha256_file(summary_path)}  RUN_SUMMARY.json\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-start", default="2022-01-01T00:00:00Z")
    parser.add_argument("--pre2024-start", default="2023-01-01T00:00:00Z")
    parser.add_argument("--official-start", default="2024-01-01T00:00:00Z")
    parser.add_argument("--official-end-exclusive", default="2024-07-01T00:00:00Z")
    args = parser.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
