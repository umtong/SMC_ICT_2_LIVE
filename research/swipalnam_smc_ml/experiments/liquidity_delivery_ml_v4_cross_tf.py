#!/usr/bin/env python3
"""Cross-timeframe liquidity-delivery candidate family.

Adds the canonical top-down SMC/ICT sequence to V3:
  5m/15m external liquidity raid -> 1m/3m displacement/MSS -> LTF FVG/OB
  mitigation -> HTF opposing liquidity.
The same causal ML, latency, global slot, costs and account engine remain.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

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
import liquidity_delivery_ml_v3_fast_runner as fast  # noqa: E402
v3 = fast.v3
v1 = fast.v1

_ORIGINAL_ADD_SMT = v1.add_smt
_ORIGINAL_RAW = v1.raw_candidates
_FRAME_REGISTRY: dict[tuple[str, int], pd.DataFrame] = {}


def add_smt_and_register(frames: dict[str, pd.DataFrame]) -> None:
    _ORIGINAL_ADD_SMT(frames)
    for symbol, frame in frames.items():
        if frame.empty:
            continue
        timeframe = int(frame["timeframe_min"].iloc[0])
        _FRAME_REGISTRY[(symbol, timeframe)] = frame


def _target_from_known_liquidity(row: pd.Series, ltf: pd.Series, direction: int, reference: float, risk: float) -> float:
    names = (
        ["last_swing_high", "equal_high_level", "opening_range_high", "prev_4h_high", "prev_session_high", "prev_day_high", "prev_week_high"]
        if direction > 0
        else ["last_swing_low", "equal_low_level", "opening_range_low", "prev_4h_low", "prev_session_low", "prev_day_low", "prev_week_low"]
    )
    values: list[float] = []
    for source in (row, ltf):
        for name in names:
            value = float(source.get(name, np.nan))
            if np.isfinite(value) and (value - reference) * direction > 0:
                values.append(value)
    unique = sorted(set(values), reverse=direction < 0)
    if direction > 0:
        unique = sorted(unique)
    else:
        unique = sorted(unique, reverse=True)
    for value in unique:
        if (value - reference) * direction >= 1.35 * risk:
            return value
    return reference + direction * 3.0 * max(risk, float(ltf.get("atr", risk)))


def cross_timeframe_candidates(symbol: str, ltf: pd.DataFrame, htf: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if ltf.empty or htf.empty:
        return pd.DataFrame()
    ltf_times = ltf["available_at_ms"].to_numpy(np.int64)
    ltf_tf = int(ltf["timeframe_min"].iloc[0])
    htf_tf = int(htf["timeframe_min"].iloc[0])
    search_window_ms = (75 if htf_tf == 15 else 45) * v1.MINUTE_MS
    seen: set[tuple[int, int, int]] = set()

    for h_i in range(60, len(htf) - 1):
        hrow = htf.iloc[h_i]
        if not np.isfinite(float(hrow.get("atr", np.nan))):
            continue
        for direction in (1, -1):
            event = v3.swept_level_v3(hrow, direction)
            if event is None:
                continue
            level_name, level, sweep_atr, confluence = event
            start = int(np.searchsorted(ltf_times, int(hrow["available_at_ms"]), side="left"))
            end = int(np.searchsorted(ltf_times, int(hrow["available_at_ms"]) + search_window_ms, side="right"))
            start = max(start, 2)
            displacement_i: int | None = None
            fvg_low = fvg_high = fvg_atr = np.nan
            for i in range(start, min(end, len(ltf))):
                bar = ltf.iloc[i]
                if float(bar["body_signed"]) * direction <= 0:
                    continue
                break_level = float(bar["internal_high"] if direction > 0 else bar["internal_low"])
                broke = float(bar["close"]) > break_level if direction > 0 else float(bar["close"]) < break_level
                location_ok = float(bar["close_location"]) >= 0.58 if direction > 0 else float(bar["close_location"]) <= 0.42
                if not (broke and location_ok and float(bar["body_atr"]) >= 0.35 and float(bar["range_atr"]) >= 0.65):
                    continue
                if direction > 0:
                    gap_low = float(ltf.at[i - 2, "high"])
                    gap_high = float(bar["low"])
                else:
                    gap_low = float(bar["high"])
                    gap_high = float(ltf.at[i - 2, "low"])
                gap = gap_high - gap_low
                if gap <= 0:
                    gap_low, gap_high = sorted((float(bar["open"]), float(bar["close"])))
                    gap = 0.0
                displacement_i = i
                fvg_atr = gap / max(float(bar["atr"]), v1.EPS)
                fvg_low, fvg_high = sorted((gap_low, gap_high))
                break
            if displacement_i is None:
                continue
            key = (htf_tf, displacement_i, direction)
            if key in seen:
                continue
            seen.add(key)
            disp = ltf.iloc[displacement_i]

            ob_i = max(start - 1, displacement_i - 1)
            for i in range(displacement_i - 1, max(start - 1, displacement_i - 10), -1):
                opposite = float(ltf.at[i, "close"]) < float(ltf.at[i, "open"]) if direction > 0 else float(ltf.at[i, "close"]) > float(ltf.at[i, "open"])
                if opposite:
                    ob_i = i
                    break
            ob = ltf.iloc[ob_i]
            if direction > 0:
                ob_low, ob_high = float(ob["low"]), float(max(ob["open"], ob["close"]))
            else:
                ob_low, ob_high = float(min(ob["open"], ob["close"])), float(ob["high"])
            overlap_low, overlap_high = max(ob_low, fvg_low), min(ob_high, fvg_high)
            overlap = overlap_high > overlap_low
            zone_low, zone_high = (overlap_low, overlap_high) if overlap else (min(ob_low, fvg_low), max(ob_high, fvg_high))
            if not (np.isfinite(zone_low) and np.isfinite(zone_high) and zone_high > zone_low > 0):
                continue
            reference = (zone_low + zone_high) / 2
            ltf_slice = ltf.iloc[start:displacement_i + 1]
            if direction > 0:
                stop_anchor = min(float(hrow["low"]), float(ltf_slice["low"].min()))
            else:
                stop_anchor = max(float(hrow["high"]), float(ltf_slice["high"].max()))
            risk = abs(reference - stop_anchor)
            if risk <= 0:
                continue
            target = _target_from_known_liquidity(hrow, disp, direction, reference, risk)
            rr = (target - reference) * direction / risk
            if not np.isfinite(rr) or rr <= 0:
                continue
            pd4 = float(disp.get("pd_4h", np.nan))
            pd_ok = bool((direction > 0 and pd4 <= 0.58) or (direction < 0 and pd4 >= 0.42)) if np.isfinite(pd4) else False
            rows.append({
                "candidate_id": f"{symbol}-XTF{htf_tf}x{ltf_tf}-{int(disp['start_time_ms'])}-{direction:+d}-{h_i}",
                "symbol": symbol,
                "direction": direction,
                "timeframe_min": ltf_tf,
                "decision_time_ms": int(disp["available_at_ms"]),
                "swept_level_name": f"htf{htf_tf}_{level_name}",
                "swept_level": level,
                "sweep_depth_atr": sweep_atr,
                "sweep_wick_atr": float((hrow["lower_wick"] if direction > 0 else hrow["upper_wick"]) / max(float(hrow["atr"]), v1.EPS)),
                "liquidity_confluence": confluence,
                "displacement_body_atr": float(disp["body_atr"]),
                "displacement_range_atr": float(disp["range_atr"]),
                "close_location": float(disp["close_location"]),
                "fvg_low": fvg_low,
                "fvg_high": fvg_high,
                "fvg_atr": fvg_atr,
                "ob_low": ob_low,
                "ob_high": ob_high,
                "zone_low": zone_low,
                "zone_high": zone_high,
                "fvg_ob_overlap": float(overlap),
                "stop_anchor": stop_anchor,
                "target_price": target,
                "structural_rr": rr,
                "atr": float(disp["atr"]),
                "atr_pct": float(disp["atr_pct"]),
                "volume_z": float(disp.get("volume_z", np.nan)),
                "turnover_z": float(disp.get("turnover_z", np.nan)),
                "trend_1h": float(disp.get("trend_1h", np.nan)),
                "trend_4h": float(disp.get("trend_4h", np.nan)),
                "pd_1h": float(disp.get("pd_1h", np.nan)),
                "pd_4h": pd4,
                "pd_aligned": float(pd_ok),
                "oi_change_z": float(disp.get("oi_change_z", np.nan)),
                "account_ratio_z": float(disp.get("account_ratio_z", np.nan)),
                "basis_bps": float(disp.get("basis_bps", np.nan)),
                "funding": float(disp.get("funding", np.nan)),
                "smt_bull": float(disp.get("smt_bull", 0)),
                "smt_bear": float(disp.get("smt_bear", 0)),
                "session_bucket": float(disp.get("session_bucket", np.nan)),
                "hour_sin": float(disp.get("hour_sin", np.nan)),
                "hour_cos": float(disp.get("hour_cos", np.nan)),
                "dow_sin": float(disp.get("dow_sin", np.nan)),
                "dow_cos": float(disp.get("dow_cos", np.nan)),
                "model_family": 1.0,
                "context_timeframe": float(htf_tf),
                "sweep_to_mss_bars": float(displacement_i - start),
                "htf_sweep_age_min": float((int(disp["available_at_ms"]) - int(hrow["available_at_ms"])) / v1.MINUTE_MS),
            })
    return pd.DataFrame(rows).sort_values("decision_time_ms", kind="stable").reset_index(drop=True) if rows else pd.DataFrame()


def raw_with_cross_timeframe(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    base = _ORIGINAL_RAW(symbol, frame)
    if not base.empty:
        base = base.copy()
        base["model_family"] = 0.0
        base["context_timeframe"] = base["timeframe_min"].astype(float)
        base["sweep_to_mss_bars"] = np.nan
        base["htf_sweep_age_min"] = 0.0
    timeframe = int(frame["timeframe_min"].iloc[0]) if not frame.empty else 0
    extras: list[pd.DataFrame] = []
    if timeframe in (1, 3):
        for htf in (5, 15):
            context = _FRAME_REGISTRY.get((symbol, htf))
            if context is not None:
                extra = cross_timeframe_candidates(symbol, frame, context)
                if not extra.empty:
                    extras.append(extra)
    parts = [part for part in [base, *extras] if part is not None and not part.empty]
    return pd.concat(parts, ignore_index=True).sort_values("decision_time_ms", kind="stable").reset_index(drop=True) if parts else pd.DataFrame()


v1.add_smt = add_smt_and_register
v1.raw_candidates = raw_with_cross_timeframe
for feature in ("model_family", "context_timeframe", "sweep_to_mss_bars", "htf_sweep_age_min"):
    if feature not in v1.FEATURES:
        v1.FEATURES.append(feature)

if __name__ == "__main__":
    raise SystemExit(v3.main_v3())
