#!/usr/bin/env python3
"""Second causal pass: preserve the core SMC/ICT thesis and repair order staleness.

This wrapper intentionally reuses only the V1 implementation created in the
same claim.  It does not import prior project strategies.  V2 changes the
execution semantics so a resting entry order cannot monopolize the single
global slot after the liquidity map/session has objectively changed.
Positions themselves still have no elapsed-time forced exit.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("swipalnam_liquidity_v1", HERE / "liquidity_delivery_ml.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load V1 liquidity-delivery module")
v1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v1)


def next_session_refresh_ms(decision_ms: int) -> int:
    """Cancel unfilled orders after one complete *new* reference session.

    UTC reference sessions are 00-07, 07-13, 13-21 and 21-24.  The first
    boundary refreshes the liquidity map; the following boundary makes the old
    resting order stale.  This is an entry-order invalidation rule, never a
    position time stop.
    """
    ts = pd.Timestamp(decision_ms, unit="ms", tz="UTC")
    day = ts.floor("D")
    boundaries = [day + pd.Timedelta(hours=h) for h in (7, 13, 21, 24, 31, 37, 45, 48)]
    future = [int(item.value // 1_000_000) for item in boundaries if int(item.value // 1_000_000) > decision_ms]
    if len(future) < 2:
        return decision_ms + 24 * v1.DAY_MS
    return future[1]


def structural_pending_end(candidate: Mapping[str, Any], setup: pd.DataFrame, hard_end_ms: int) -> int:
    decision = int(candidate["decision_time_ms"])
    direction = int(candidate["direction"])
    expiry = min(next_session_refresh_ms(decision), hard_end_ms)
    times = setup["available_at_ms"].to_numpy(np.int64)
    start = int(np.searchsorted(times, decision, side="right"))
    end = int(np.searchsorted(times, expiry, side="left"))
    for i in range(start, end):
        row = setup.iloc[i]
        opposite_mss = (
            float(row["close"]) < float(row["internal_low"]) and float(row["body_signed"]) < 0 and float(row["body_atr"]) >= 0.65
            if direction > 0
            else float(row["close"]) > float(row["internal_high"]) and float(row["body_signed"]) > 0 and float(row["body_atr"]) >= 0.65
        )
        displacement_against = float(row["range_atr"]) >= 0.9 and opposite_mss
        if displacement_against:
            return min(int(row["available_at_ms"]) + v1.LATENCY_MS, hard_end_ms)
    return expiry


def simulate_v2(candidate: Mapping[str, Any], minute: pd.DataFrame, setup: pd.DataFrame, config: Any, end_ms: int) -> dict[str, Any]:
    direction = int(candidate["direction"])
    decision = int(candidate["decision_time_ms"])
    active = decision + v1.LATENCY_MS
    pending_end = structural_pending_end(candidate, setup, end_ms)
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
    if begin >= pending_end_i or (limit - stop) * direction <= 0 or (target - limit) * direction <= 0:
        return {
            **base,
            "order_end_time_ms": pending_end,
            "filled": False,
            "resolved": True,
            "entry_time_ms": np.nan,
            "entry_price": np.nan,
            "stop_price": stop,
            "exit_time_ms": np.nan,
            "exit_price": np.nan,
            "exit_reason": "stale_or_invalid_before_activation",
            "gross_pnl_per_unit": 0.0,
            "net_r": np.nan,
            "mfe_r": np.nan,
            "mae_r": np.nan,
        }

    fill_i: int | None = None
    for i in range(begin, pending_end_i):
        row = minute.iloc[i]
        invalid = float(row["low"]) <= stop if direction > 0 else float(row["high"]) >= stop
        delivered = float(row["high"]) >= target if direction > 0 else float(row["low"]) <= target
        if invalid or delivered:
            return {
                **base,
                "order_end_time_ms": int(row["available_at_ms"]),
                "filled": False,
                "resolved": True,
                "entry_time_ms": np.nan,
                "entry_price": np.nan,
                "stop_price": stop,
                "exit_time_ms": np.nan,
                "exit_price": np.nan,
                "exit_reason": "invalidated_before_fill" if invalid else "target_before_fill",
                "gross_pnl_per_unit": 0.0,
                "net_r": np.nan,
                "mfe_r": np.nan,
                "mae_r": np.nan,
            }
        if float(row["low"]) <= limit <= float(row["high"]) and i + 1 < hard_end_i:
            fill_i = i + 1
            break

    if fill_i is None:
        return {
            **base,
            "order_end_time_ms": pending_end,
            "filled": False,
            "resolved": True,
            "entry_time_ms": np.nan,
            "entry_price": np.nan,
            "stop_price": stop,
            "exit_time_ms": np.nan,
            "exit_price": np.nan,
            "exit_reason": "liquidity_context_refreshed",
            "gross_pnl_per_unit": 0.0,
            "net_r": np.nan,
            "mfe_r": np.nan,
            "mae_r": np.nan,
        }

    # Delegate the position-management path to V1 by creating a minute view in
    # which the already-confirmed next-open fill is the first possible touch.
    # We preserve the exact V1 structural exits and no-time-stop semantics.
    synthetic = dict(candidate)
    fill_open = float(minute.iloc[fill_i]["open"])
    synthetic["zone_low"] = fill_open
    synthetic["zone_high"] = fill_open * (1 + 1e-12)
    synthetic["decision_time_ms"] = int(minute.iloc[fill_i - 1]["available_at_ms"])
    delegated = v1_original_simulate(synthetic, minute, setup, config, end_ms)
    delegated.update({
        "candidate_id": candidate["candidate_id"],
        "decision_time_ms": decision,
        "order_active_time_ms": active,
        "order_end_time_ms": int(minute.iloc[fill_i]["start_time_ms"]),
    })
    return delegated


def setup_grid_v2() -> list[Any]:
    configs: list[Any] = []
    for tf in (5, 15):
        for sweep in (0.00, 0.04, 0.10, 0.18):
            for body in (0.35, 0.55, 0.80, 1.10):
                for fvg in (0.00, 0.03, 0.08):
                    for retrace in (0.50, 0.62, 0.705, 0.79):
                        for require_pd in (False, True):
                            configs.append(v1.SetupConfig(tf, sweep, body, fvg, retrace, require_pd, fvg > 0))
    return configs


def account_grid_v2() -> list[Any]:
    return [
        v1.AccountConfig(risk, leverage)
        for risk in (0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.16, 0.20, 0.25)
        for leverage in (3, 5, 10, 20, 30, 50, 75, 100)
    ]


v1_original_simulate = v1.simulate
v1.simulate = simulate_v2
v1.setup_grid = setup_grid_v2
v1.account_grid = account_grid_v2

if __name__ == "__main__":
    raise SystemExit(v1.main())
