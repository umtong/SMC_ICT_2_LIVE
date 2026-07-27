#!/usr/bin/env python3
"""Executable V2 entry point with exact next-minute confirmed fill delegation."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("swipalnam_liquidity_v2", HERE / "liquidity_delivery_ml_v2.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load V2 module")
v2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v2)
v1 = v2.v1


def simulate_fixed(candidate: Mapping[str, Any], minute: pd.DataFrame, setup: pd.DataFrame, config: Any, end_ms: int) -> dict[str, Any]:
    direction = int(candidate["direction"])
    decision = int(candidate["decision_time_ms"])
    active = decision + v1.LATENCY_MS
    pending_end = v2.structural_pending_end(candidate, setup, end_ms)
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

    touch_i: int | None = None
    for i in range(begin, pending_end_i):
        row = minute.iloc[i]
        invalid = float(row["low"]) <= stop if direction > 0 else float(row["high"]) >= stop
        delivered = float(row["high"]) >= target if direction > 0 else float(row["low"]) <= target
        if invalid or delivered:
            return unfilled("invalidated_before_fill" if invalid else "target_before_fill", int(row["available_at_ms"]))
        if float(row["low"]) <= limit <= float(row["high"]) and i + 1 < hard_end_i:
            touch_i = i
            break
    if touch_i is None:
        return unfilled("liquidity_context_refreshed", pending_end)

    fill_i = touch_i + 1
    synthetic = dict(candidate)
    touch_price = float(minute.iloc[touch_i]["close"])
    synthetic["zone_low"] = touch_price * (1 - 1e-12)
    synthetic["zone_high"] = touch_price * (1 + 1e-12)
    # Internal-only timestamp makes V1 inspect touch_i and enter fill_i.  The
    # externally visible decision/activation timestamps are restored below.
    synthetic["decision_time_ms"] = int(minute.iloc[touch_i]["start_time_ms"]) - v1.LATENCY_MS - 1
    delegated = v2.v1_original_simulate(synthetic, minute, setup, config, end_ms)
    delegated.update({
        "candidate_id": candidate["candidate_id"],
        "symbol": candidate["symbol"],
        "direction": direction,
        "decision_time_ms": decision,
        "order_active_time_ms": active,
        "order_end_time_ms": int(minute.iloc[fill_i]["start_time_ms"]),
    })
    return delegated


v1.simulate = simulate_fixed

if __name__ == "__main__":
    raise SystemExit(v1.main())
