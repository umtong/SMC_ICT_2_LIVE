#!/usr/bin/env python3
"""V8: align causal ML labels with the audited execution-cost semantics."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

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
import liquidity_delivery_ml_v7_confidence_risk as v7  # noqa: E402
v6 = v7.v6
v5 = v7.v5
v3 = v7.v3
v1 = v7.v1
_BASE_SIMULATE = v1.simulate


def simulate_aligned_labels(
    candidate: Mapping[str, Any],
    minute: pd.DataFrame,
    setup: pd.DataFrame,
    config: Any,
    end_ms: int,
) -> dict[str, Any]:
    result = _BASE_SIMULATE(candidate, minute, setup, config, end_ms)
    if not bool(result.get("filled")):
        result["label_cost_model"] = "unfilled"
        return result
    direction = int(result["direction"])
    entry = float(result["entry_price"])
    stop = float(result["stop_price"])
    exit_price = float(result["exit_price"])
    risk = (entry - stop) * direction
    if risk <= 0:
        result["net_r"] = np.nan
        result["label_cost_model"] = "invalid_risk"
        return result

    event = SimpleNamespace(
        candidate_id=result["candidate_id"],
        entry_time_ms=int(result["entry_time_ms"]),
        exit_time_ms=int(result["exit_time_ms"]),
        direction=direction,
        entry_price=entry,
        stop_price=stop,
        target_price=float(candidate["target_price"]),
        exit_reason=result["exit_reason"],
    )
    partial_time, tp1 = v5._partial_event(event, minute)
    partial_fraction = 0.40 if partial_time is not None else 0.0
    remaining_fraction = 1.0 - partial_fraction
    # Entry/final prices already contain the fixed 1 bp adverse execution
    # movement.  Do not charge that slippage a second time.  Labels include
    # taker fee plus a fixed 1 bp per-side baseline impact; account replay later
    # replaces the latter with participation-sensitive impact.
    rate = (5.5 + 1.0) / 10_000
    transaction_cost = (
        entry * rate
        + partial_fraction * tp1 * rate
        + remaining_fraction * exit_price * rate
    )
    funding_rate = float(candidate.get("funding", np.nan))
    if not np.isfinite(funding_rate):
        funding_rate = 0.0
    holding_days = max(0.0, (int(result["exit_time_ms"]) - int(result["entry_time_ms"])) / v1.DAY_MS)
    funding_cost = direction * entry * funding_rate * holding_days * 3.0
    result["net_r"] = (float(result["gross_pnl_per_unit"]) - transaction_cost - funding_cost) / risk
    result["label_transaction_cost_per_unit"] = transaction_cost
    result["label_funding_cost_per_unit"] = funding_cost
    result["label_partial_time_ms"] = partial_time
    result["label_cost_model"] = "embedded_1bp_slippage_plus_5.5bp_taker_plus_1bp_baseline_impact_and_funding"
    return result


v1.simulate = simulate_aligned_labels

if __name__ == "__main__":
    raise SystemExit(v3.main_v3())
