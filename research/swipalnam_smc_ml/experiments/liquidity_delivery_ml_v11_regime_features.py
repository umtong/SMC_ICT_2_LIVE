#!/usr/bin/env python3
"""V11: richer market-state gating while SMC/ICT remains the sole signal source."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_ORIGINAL_MODULE_FROM_SPEC = importlib.util.module_from_spec


def _registered(spec):
    module = _ORIGINAL_MODULE_FROM_SPEC(spec)
    if spec.name:
        sys.modules[spec.name] = module
    return module


importlib.util.module_from_spec = _registered
import liquidity_delivery_ml_v10_gap_entry as v10  # noqa: E402
v3 = v10.v3
v1 = v10.v1
_BASE_ENRICH = v3.enrich_v3
_BASE_RAW = v1.raw_candidates


def enrich_regime(frame: pd.DataFrame, minutes: int, streams, one_minute: pd.DataFrame) -> pd.DataFrame:
    out = _BASE_ENRICH(frame, minutes, streams, one_minute)
    log_return = np.log(out["close"]).diff()
    out["ret_1"] = log_return
    out["ret_3"] = np.log(out["close"] / out["close"].shift(3))
    out["ret_12"] = np.log(out["close"] / out["close"].shift(12))
    out["rv_12"] = log_return.rolling(12, min_periods=6).std(ddof=0)
    out["rv_48"] = log_return.rolling(48, min_periods=16).std(ddof=0)
    abs_move = out["close"].diff().abs()
    out["efficiency_12"] = out["close"].diff(12).abs() / abs_move.rolling(12, min_periods=6).sum().replace(0, np.nan)
    out["efficiency_48"] = out["close"].diff(48).abs() / abs_move.rolling(48, min_periods=16).sum().replace(0, np.nan)
    out["atr_z"] = v1.zscore(np.log(out["atr_pct"].replace(0, np.nan)), 288)
    signed_volume = np.sign(out["body_signed"]) * np.log1p(out["volume"].clip(lower=0))
    out["signed_volume_z"] = v1.zscore(signed_volume.rolling(6, min_periods=3).sum(), 288)

    dt = pd.to_datetime(out["start_time_ms"], unit="ms", utc=True)
    hour = dt.dt.hour.to_numpy()
    bucket = np.select([hour < 7, hour < 13, hour < 21], [0, 1, 2], default=3)
    day_no = (dt.dt.floor("D").astype("int64") // (v1.DAY_MS * 1_000_000)).to_numpy()
    session_id = day_no * 4 + bucket
    typical = (out["high"] + out["low"] + out["close"]) / 3
    notional = out["turnover"].clip(lower=0)
    cumulative_notional = notional.groupby(session_id).cumsum()
    cumulative_pv = (typical * notional).groupby(session_id).cumsum()
    session_vwap = cumulative_pv / cumulative_notional.replace(0, np.nan)
    out["session_vwap_deviation_atr"] = (out["close"] - session_vwap) / out["atr"].replace(0, np.nan)

    out["oi_price_interaction"] = out["ret_3"] * out.get("oi_change_z", np.nan)
    out["funding_basis_interaction"] = out.get("funding", np.nan) * out.get("basis_bps", np.nan)
    out["crowding_composite"] = (
        out.get("account_ratio_z", 0).fillna(0)
        + np.tanh(out.get("basis_bps", 0).fillna(0) / 10)
        + np.tanh(out.get("funding", 0).fillna(0) * 10_000)
    )
    return out


REGIME_FEATURES = [
    "ret_1", "ret_3", "ret_12", "rv_12", "rv_48", "efficiency_12", "efficiency_48",
    "atr_z", "signed_volume_z", "session_vwap_deviation_atr", "oi_price_interaction",
    "funding_basis_interaction", "crowding_composite", "directional_crowding",
    "directional_trend_alignment", "directional_smt",
]


def raw_with_regime(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    candidates = _BASE_RAW(symbol, frame)
    if candidates.empty:
        return candidates
    times = frame["available_at_ms"].to_numpy(np.int64)
    values = []
    for candidate in candidates.to_dict("records"):
        pos = int(np.searchsorted(times, int(candidate["decision_time_ms"]), side="right") - 1)
        row = frame.iloc[max(0, pos)]
        for feature in REGIME_FEATURES[:13]:
            candidate[feature] = float(row.get(feature, np.nan))
        direction = int(candidate["direction"])
        candidate["directional_crowding"] = direction * float(row.get("crowding_composite", np.nan))
        candidate["directional_trend_alignment"] = direction * (
            float(row.get("trend_1h", 0) if np.isfinite(float(row.get("trend_1h", np.nan))) else 0)
            + float(row.get("trend_4h", 0) if np.isfinite(float(row.get("trend_4h", np.nan))) else 0)
        )
        candidate["directional_smt"] = float(row.get("smt_bull", 0) if direction > 0 else row.get("smt_bear", 0))
        values.append(candidate)
    return pd.DataFrame(values).sort_values("decision_time_ms", kind="stable").reset_index(drop=True)


v3.enrich_v3 = enrich_regime
v1.enrich = enrich_regime
v1.raw_candidates = raw_with_regime
for feature in REGIME_FEATURES:
    if feature not in v1.FEATURES:
        v1.FEATURES.append(feature)

if __name__ == "__main__":
    raise SystemExit(v3.main_v3())
