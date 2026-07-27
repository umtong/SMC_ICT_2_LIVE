#!/usr/bin/env python3
"""V9: causally known opposing-liquidity target ladder."""
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
import liquidity_delivery_ml_v8_aligned_labels as v8  # noqa: E402
v3 = v8.v3
v1 = v8.v1
_BASE_RAW = v1.raw_candidates


def _known_targets(row: pd.Series, direction: int) -> list[tuple[str, float]]:
    names = (
        ["last_swing_high", "equal_high_level", "opening_range_high", "prev_4h_high", "prev_session_high", "prev_day_high", "prev_week_high"]
        if direction > 0
        else ["last_swing_low", "equal_low_level", "opening_range_low", "prev_4h_low", "prev_session_low", "prev_day_low", "prev_week_low"]
    )
    found: list[tuple[str, float]] = []
    for name in names:
        value = float(row.get(name, np.nan))
        if np.isfinite(value):
            found.append((name, value))
    return found


def raw_with_target_ladder(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    base = _BASE_RAW(symbol, frame)
    if base.empty:
        return base
    availability = frame["available_at_ms"].to_numpy(np.int64)
    expanded: list[dict] = []
    for candidate in base.to_dict("records"):
        direction = int(candidate["direction"])
        decision = int(candidate["decision_time_ms"])
        pos = int(np.searchsorted(availability, decision, side="right") - 1)
        if pos < 0:
            continue
        context = frame.iloc[pos]
        reference = (float(candidate["zone_low"]) + float(candidate["zone_high"])) / 2
        risk = abs(reference - float(candidate["stop_anchor"]))
        if risk <= 0:
            continue
        targets = [(str(candidate.get("swept_level_name", "existing_target")), float(candidate["target_price"]))]
        targets.extend(_known_targets(context, direction))
        valid: list[tuple[str, float, float]] = []
        for name, value in targets:
            distance = (value - reference) * direction
            if not np.isfinite(value) or distance <= 0:
                continue
            rr = distance / risk
            if rr < 1.0:
                continue
            valid.append((name, value, rr))
        valid.sort(key=lambda item: item[1], reverse=direction < 0)
        if direction > 0:
            valid.sort(key=lambda item: item[1])
        else:
            valid.sort(key=lambda item: item[1], reverse=True)
        deduped: list[tuple[str, float, float]] = []
        tolerance = max(float(candidate["atr"]) * 0.10, reference * 0.00025)
        for item in valid:
            if all(abs(item[1] - prior[1]) > tolerance for prior in deduped):
                deduped.append(item)
        if not deduped:
            fallback = reference + direction * 2.5 * max(risk, float(candidate["atr"]))
            deduped = [("measured_delivery", fallback, abs(fallback - reference) / risk)]
        # Keep near, intermediate and far known liquidity rather than every
        # correlated level.
        selected = []
        for index in (0, len(deduped) // 2, len(deduped) - 1):
            item = deduped[index]
            if item not in selected:
                selected.append(item)
        for variant, (name, target, rr) in enumerate(selected[:3]):
            item = dict(candidate)
            item["candidate_id"] = f"{candidate['candidate_id']}-T{variant}"
            item["target_price"] = target
            item["structural_rr"] = rr
            item["target_variant"] = float(variant)
            item["target_reference_code"] = float(abs(hash(name)) % 997)
            item["target_distance_atr"] = abs(target - reference) / max(float(candidate["atr"]), v1.EPS)
            expanded.append(item)
    return pd.DataFrame(expanded).sort_values("decision_time_ms", kind="stable").reset_index(drop=True) if expanded else pd.DataFrame()


v1.raw_candidates = raw_with_target_ladder
for feature in ("target_variant", "target_reference_code", "target_distance_atr"):
    if feature not in v1.FEATURES:
        v1.FEATURES.append(feature)

if __name__ == "__main__":
    raise SystemExit(v3.main_v3())
