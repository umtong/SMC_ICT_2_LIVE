#!/usr/bin/env python3
"""V10: first-observable-open entry after fixed 500 ms activation.

With 1m data the ongoing bar at activation cannot be ordered internally.  If
the first fully observable minute opens through a resting limit (without
crossing invalidation), execution occurs at that open.  A touch only discovered
inside a minute still waits for the next minute open.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
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
import liquidity_delivery_ml_v9_target_ladder as v9  # noqa: E402
v8 = v9.v8
v3 = v9.v3
v1 = v9.v1
_v2_module = v3.v2f.v2
_ORIGINAL_POSITION_SIMULATE = _v2_module.v1_original_simulate


def simulate_first_observable_open(
    candidate: Mapping[str, Any],
    minute: pd.DataFrame,
    setup: pd.DataFrame,
    config: Any,
    end_ms: int,
) -> dict[str, Any]:
    direction = int(candidate["direction"])
    decision = int(candidate["decision_time_ms"])
    active = decision + v1.LATENCY_MS
    pending_end = _v2_module.structural_pending_end(candidate, setup, end_ms)
    limit = v1.entry_price(candidate, config.retrace)
    stop = float(candidate["stop_anchor"]) - direction * config.stop_buffer_atr * float(candidate["atr"])
    target = float(candidate["target_price"])
    starts = minute["start_time_ms"].to_numpy(np.int64)
    begin = int(np.searchsorted(starts, active, side="left"))
    pending_end_i = int(np.searchsorted(starts, pending_end, side="left"))
    hard_end_i = int(np.searchsorted(starts, end_ms, side="left"))
    base = {
        "candidate_id": candidate["candidate_id"],
        "symbol": candidate["symbol"],
        "direction": direction,
        "decision_time_ms": decision,
        "order_active_time_ms": active,
    }

    def unfilled(reason: str, order_end: int) -> dict[str, Any]:
        return {
            **base,
            "order_end_time_ms": order_end,
            "filled": False,
            "resolved": True,
            "entry_time_ms": np.nan,
            "entry_price": np.nan,
            "stop_price": stop,
            "exit_time_ms": np.nan,
            "exit_price": np.nan,
            "exit_reason": reason,
            "gross_pnl_per_unit": 0.0,
            "net_r": np.nan,
            "mfe_r": np.nan,
            "mae_r": np.nan,
        }

    if begin >= pending_end_i or (limit - stop) * direction <= 0 or (target - limit) * direction <= 0:
        return unfilled("stale_or_invalid_before_activation", pending_end)

    fill_i: int | None = None
    touch_i: int | None = None
    fill_mode = ""
    for i in range(begin, pending_end_i):
        row = minute.iloc[i]
        opening = float(row["open"])
        invalid_open = opening <= stop if direction > 0 else opening >= stop
        delivered_open = opening >= target if direction > 0 else opening <= target
        if invalid_open or delivered_open:
            return unfilled("gap_invalidated_before_fill" if invalid_open else "gap_delivered_before_fill", int(row["start_time_ms"]))

        through_limit = opening <= limit if direction > 0 else opening >= limit
        if through_limit:
            fill_i = i
            touch_i = max(0, i - 1)
            fill_mode = "first_observable_open_through_limit"
            break

        invalid = float(row["low"]) <= stop if direction > 0 else float(row["high"]) >= stop
        delivered = float(row["high"]) >= target if direction > 0 else float(row["low"]) <= target
        if invalid or delivered:
            return unfilled("invalidated_before_fill" if invalid else "target_before_fill", int(row["available_at_ms"]))
        if float(row["low"]) <= limit <= float(row["high"]) and i + 1 < hard_end_i:
            touch_i = i
            fill_i = i + 1
            fill_mode = "confirmed_touch_next_open"
            break

    if fill_i is None or touch_i is None:
        return unfilled("liquidity_context_refreshed", pending_end)

    synthetic = dict(candidate)
    touch_price = float(minute.iloc[touch_i]["close"])
    synthetic["zone_low"] = touch_price * (1 - 1e-12)
    synthetic["zone_high"] = touch_price * (1 + 1e-12)
    synthetic["decision_time_ms"] = int(minute.iloc[touch_i]["start_time_ms"]) - v1.LATENCY_MS - 1
    delegated = _ORIGINAL_POSITION_SIMULATE(synthetic, minute, setup, config, end_ms)
    delegated.update({
        "candidate_id": candidate["candidate_id"],
        "symbol": candidate["symbol"],
        "direction": direction,
        "decision_time_ms": decision,
        "order_active_time_ms": active,
        "order_end_time_ms": int(minute.iloc[fill_i]["start_time_ms"]),
        "entry_fill_mode": fill_mode,
    })
    return delegated


# Reuse V8's single audited label-alignment wrapper, changing only its path
# source.  The wrapper resolves _BASE_SIMULATE dynamically from its module.
v8._BASE_SIMULATE = simulate_first_observable_open
v1.simulate = v8.simulate_aligned_labels

if __name__ == "__main__":
    raise SystemExit(v3.main_v3())
