from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run as base


def simulate(
    events: pd.DataFrame,
    probabilities: np.ndarray,
    bars: pd.DataFrame,
    partition: str,
    cost_bps: float,
    risk_fraction: float,
    cap_multiple: float,
    excluded: set[str] | None = None,
) -> dict[str, Any]:
    chosen = base.event_actions(events, probabilities, excluded)
    chosen = chosen[(chosen["partition"] == partition) & (chosen["side"] != 0)].sort_values("entry_time")
    start, end = base.PARTITIONS[partition]
    nav = 10_000.0
    initial = nav
    next_available = start
    trades: list[dict[str, Any]] = []
    daily: dict[str, float] = {}
    nav_points: list[tuple[pd.Timestamp, float]] = [(start, initial)]
    cost_fraction = cost_bps / 10_000.0
    bar_time_ns = bars["timestamp"].astype("int64").to_numpy()

    for _, row in chosen.iterrows():
        entry_time = pd.Timestamp(row["entry_time"])
        if entry_time < next_available:
            continue
        entry = float(row["entry_price"])
        side = int(row["side"])
        stop_distance = float(row["lower_distance"] if side > 0 else row["upper_distance"])
        risk_per_notional = stop_distance + cost_fraction
        max_by_liquidation = 0.90 / max(stop_distance + base.MAINTENANCE_MARGIN_FRACTION, 1e-9)
        leverage = min(cap_multiple, max_by_liquidation, risk_fraction / max(risk_per_notional, 1e-9))
        if leverage <= 0:
            continue
        notional = nav * leverage
        quantity = notional / entry
        exit_index, exit_price, reason = base.trade_outcome(row, bars, end)
        exit_time = bars.at[exit_index, "timestamp"]
        entry_fee = 0.5 * cost_fraction * notional
        exit_notional = quantity * exit_price
        exit_fee = 0.5 * cost_fraction * exit_notional
        funding_count = base.next_funding_boundaries(entry_time, exit_time)
        funding = funding_count * (base.ADVERSE_FUNDING_BPS / 10_000.0) * notional
        gross = side * quantity * (exit_price - entry)
        pnl = gross - entry_fee - exit_fee - funding
        start_nav = nav

        current_day = entry_time.normalize() + pd.Timedelta(days=1)
        while current_day <= min(exit_time, end):
            mark_index = int(np.searchsorted(bar_time_ns, int(current_day.value), side="left") - 1)
            if mark_index >= int(row["entry_index"]):
                mark = float(bars.at[mark_index, "close"])
                accrued = base.next_funding_boundaries(entry_time, current_day) * (base.ADVERSE_FUNDING_BPS / 10_000.0) * notional
                marked = start_nav - entry_fee - accrued + side * quantity * (mark - entry)
                marked = max(marked, 1e-12)
                daily[current_day.strftime("%Y-%m-%d")] = marked
                nav_points.append((current_day, marked))
            current_day += pd.Timedelta(days=1)

        nav = nav + pnl
        trades.append({
            "event_id": row["event_id"],
            "entry_time": entry_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "side": side,
            "entry_price": entry,
            "exit_price": exit_price,
            "reason": reason,
            "leverage": leverage,
            "funding_events": funding_count,
            "pnl": pnl,
            "return_on_start_nav": pnl / start_nav,
            "nav_after": nav,
        })
        nav_points.append((exit_time, max(nav, 1e-12)))
        next_available = exit_time + pd.Timedelta(nanoseconds=1)
        if nav <= 0:
            break

    calendar_days = int((end - start) / pd.Timedelta(days=1))
    geometric = (nav / initial) ** (1.0 / calendar_days) - 1.0 if nav > 0 else -1.0
    pnl_values = np.array([trade["pnl"] for trade in trades], dtype=float)
    positive = float(pnl_values[pnl_values > 0].sum()) if len(pnl_values) else 0.0
    negative = float(-pnl_values[pnl_values < 0].sum()) if len(pnl_values) else 0.0
    profit_factor = positive / negative if negative > 0 else (math.inf if positive > 0 else 0.0)
    returns = np.array([trade["return_on_start_nav"] for trade in trades], dtype=float)
    ordered_nav = np.array([value for _, value in sorted(nav_points, key=lambda item: item[0])], dtype=float)
    peaks = np.maximum.accumulate(ordered_nav)
    maximum_drawdown = float(np.max(1.0 - ordered_nav / peaks)) if len(ordered_nav) else 0.0
    half = start + (end - start) / 2
    first_nav = initial
    for trade in trades:
        if pd.Timestamp(trade["exit_time"]) < half:
            first_nav = trade["nav_after"]
    half_returns = {
        "H1": first_nav / initial - 1.0,
        "H2": nav / first_nav - 1.0 if first_nav > 0 else -1.0,
    }
    return {
        "partition": partition,
        "cost_bps": cost_bps,
        "risk_fraction": risk_fraction,
        "cap_multiple": cap_multiple,
        "initial_nav": initial,
        "final_nav": nav,
        "total_return": nav / initial - 1.0,
        "geometric_daily_growth": geometric,
        "calendar_days": calendar_days,
        "trade_count": len(trades),
        "profit_factor": profit_factor,
        "maximum_drawdown": maximum_drawdown,
        "median_trade_return": float(np.median(returns)) if len(returns) else 0.0,
        "positive_trade_count": int(np.sum(returns > 0)) if len(returns) else 0,
        "negative_trade_count": int(np.sum(returns < 0)) if len(returns) else 0,
        "half_returns": half_returns,
        "bankrupt": nav <= 0,
        "daily_nav": daily,
        "trades": trades,
    }


def self_test() -> None:
    base.self_test()
    assert base.DECISION_COST_BPS == 18.0
    print("marked-NAV correction self-test passed")


def main() -> int:
    args = base.parse_args()
    base.simulate = simulate
    if args.command == "self-test":
        self_test()
        return 0
    result = base.run_screen(args.output, args.cache)
    print(json.dumps({
        "status": result["status"],
        "events": result["event_meta"]["event_count"],
        "development_24bps": result["development_accounts"].get("24.0"),
        "selected_path": result["selected_path"],
        "next_action": result["next_action"],
    }, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
