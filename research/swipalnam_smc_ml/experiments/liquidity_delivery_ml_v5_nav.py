#!/usr/bin/env python3
"""V5: exact UTC daily liquidation-value NAV for the V4 candidate system.

The signal/model logic is unchanged.  This revision fixes the account metric:
open positions are marked at every UTC midnight at an executable liquidation
price after fee/slippage/impact, partial exits are recognized, and accrued
funding is deducted.  Embedded 1 bp execution slippage in the path simulator is
not charged twice.
"""
from __future__ import annotations

import importlib.util
import math
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
import liquidity_delivery_ml_v4_cross_tf as v4  # noqa: E402
v3 = v4.v3
v1 = v4.v1

_PARTIAL_CACHE: dict[tuple[str, int, int], tuple[int | None, float]] = {}


def _minute_index(frame: pd.DataFrame, timestamp_ms: int, side: str = "left") -> int:
    return int(np.searchsorted(frame["start_time_ms"].to_numpy(np.int64), timestamp_ms, side=side))


def _partial_event(row: Any, minute: pd.DataFrame) -> tuple[int | None, float]:
    key = (str(row.candidate_id), int(row.entry_time_ms), int(row.exit_time_ms))
    cached = _PARTIAL_CACHE.get(key)
    if cached is not None:
        return cached
    direction = int(row.direction)
    entry = float(row.entry_price)
    stop = float(row.stop_price)
    target = float(row.target_price)
    risk = (entry - stop) * direction
    tp1 = entry + direction * min(risk, 0.45 * abs(target - entry))
    start = _minute_index(minute, int(row.entry_time_ms), "left")
    end = min(len(minute), _minute_index(minute, int(row.exit_time_ms), "right") + 1)
    partial_time: int | None = None
    for i in range(start, end):
        bar = minute.iloc[i]
        available = int(bar["available_at_ms"])
        if available > int(row.exit_time_ms):
            break
        tp_hit = float(bar["high"]) >= tp1 if direction > 0 else float(bar["low"]) <= tp1
        exit_here = available == int(row.exit_time_ms)
        if exit_here and str(row.exit_reason) == "stop" and partial_time is None:
            # Position engine resolves stop before TP on an ambiguous bar.
            break
        if tp_hit:
            partial_time = available
            break
    result = (partial_time, tp1)
    _PARTIAL_CACHE[key] = result
    return result


def _turnover_window(minute: pd.DataFrame, timestamp_ms: int, bars: int = 60) -> float:
    pos = _minute_index(minute, timestamp_ms, "left")
    return float(minute["turnover"].iloc[max(0, pos - bars):pos + 1].sum())


def _impact_rate(notional: float, local_turnover: float, impact_bps: float) -> float:
    participation = notional / max(local_turnover, notional, v1.EPS)
    return impact_bps * math.sqrt(max(participation, 0.0)) / 10_000


def _mark_close(minute: pd.DataFrame, boundary_ms: int) -> float:
    pos = int(np.searchsorted(minute["available_at_ms"].to_numpy(np.int64), boundary_ms, side="right") - 1)
    if pos < 0:
        return float(minute["open"].iloc[0])
    return float(minute["close"].iloc[min(pos, len(minute) - 1)])


def account_sim_exact(
    frame: pd.DataFrame,
    minute_by_symbol: Mapping[str, pd.DataFrame],
    account: Any,
    start_ms: int,
    end_ms: int,
    threshold: float,
    initial_nav: float = 10_000.0,
) -> dict[str, Any]:
    selected = (
        frame[frame["ml_score"].notna() & (frame["ml_score"] >= threshold)]
        .sort_values(["decision_time_ms", "ml_score"], ascending=[True, False])
        .drop_duplicates("decision_time_ms")
    )
    nav = initial_nav
    slot_free = start_ms
    trades: list[dict[str, Any]] = []
    skips = 0
    liquidation_events = 0
    fee_rate = float(account.taker_fee_bps) / 10_000
    embedded_slippage = float(account.slippage_bps) / 10_000

    for row in selected.itertuples(index=False):
        decision = int(row.decision_time_ms)
        if not (start_ms <= decision < end_ms):
            continue
        if decision < slot_free:
            skips += 1
            continue
        if not bool(row.filled):
            slot_free = min(int(row.order_end_time_ms), end_ms)
            continue

        direction = int(row.direction)
        entry = float(row.entry_price)
        stop_quote = float(row.stop_price)
        stop_exec = stop_quote * (1 - direction * embedded_slippage)
        stop_distance = abs(entry - stop_exec)
        provisional_notional = nav * float(account.leverage)
        local_turnover = _turnover_window(minute_by_symbol[str(row.symbol)], int(row.entry_time_ms))
        provisional_impact = _impact_rate(provisional_notional, local_turnover, float(account.impact_bps))
        expected_loss_per_unit = stop_distance + entry * (2 * fee_rate + 2 * provisional_impact)
        planned_loss = nav * float(account.risk_fraction)
        quantity = min(
            planned_loss / max(expected_loss_per_unit, v1.EPS),
            nav * float(account.leverage) / entry,
        )
        if quantity <= 0:
            continue
        notional = quantity * entry
        entry_impact = _impact_rate(notional, local_turnover, float(account.impact_bps))
        stop_pct = stop_distance / entry
        liquidation_distance = max(0.0, 1 / float(account.leverage) - float(account.maintenance_margin_rate) - 2 * fee_rate)
        if stop_pct >= 0.90 * liquidation_distance:
            liquidation_events += 1
            continue

        partial_time, tp1 = _partial_event(row, minute_by_symbol[str(row.symbol)])
        partial_fraction = 0.40 if partial_time is not None else 0.0
        remaining_fraction = 1.0 - partial_fraction
        exit_price = float(row.exit_price)
        exit_turnover = _turnover_window(minute_by_symbol[str(row.symbol)], int(row.exit_time_ms))
        exit_impact = _impact_rate(quantity * remaining_fraction * exit_price, exit_turnover, float(account.impact_bps))
        partial_impact = (
            _impact_rate(quantity * partial_fraction * tp1, _turnover_window(minute_by_symbol[str(row.symbol)], int(partial_time)), float(account.impact_bps))
            if partial_time is not None
            else 0.0
        )

        gross = quantity * float(row.gross_pnl_per_unit)
        entry_cost = quantity * entry * (fee_rate + entry_impact)
        partial_cost = quantity * partial_fraction * tp1 * (fee_rate + partial_impact)
        final_cost = quantity * remaining_fraction * exit_price * (fee_rate + exit_impact)
        funding_rate = float(row.funding) if np.isfinite(float(row.funding)) else 0.0
        holding_days = max(0.0, (int(row.exit_time_ms) - int(row.entry_time_ms)) / v1.DAY_MS)
        funding_cost = direction * notional * funding_rate * holding_days * 3.0
        pnl = gross - entry_cost - partial_cost - final_cost - funding_cost
        before = nav
        nav += pnl
        trades.append({
            "candidate_id": row.candidate_id,
            "symbol": row.symbol,
            "direction": direction,
            "decision_time_ms": decision,
            "entry_time_ms": int(row.entry_time_ms),
            "exit_time_ms": int(row.exit_time_ms),
            "entry_time": v1.iso_ms(int(row.entry_time_ms)),
            "exit_time": v1.iso_ms(int(row.exit_time_ms)),
            "exit_reason": row.exit_reason,
            "entry_price": entry,
            "exit_price": exit_price,
            "stop_price": stop_quote,
            "target_price": float(row.target_price),
            "partial_time_ms": partial_time,
            "partial_time": v1.iso_ms(partial_time),
            "partial_price": tp1 if partial_time is not None else None,
            "partial_fraction": partial_fraction,
            "remaining_fraction": remaining_fraction,
            "quantity": quantity,
            "notional": notional,
            "planned_loss": planned_loss,
            "gross_pnl": gross,
            "entry_cost": entry_cost,
            "partial_cost": partial_cost,
            "final_cost": final_cost,
            "funding_cost": funding_cost,
            "net_pnl": pnl,
            "realized_r": pnl / max(planned_loss, v1.EPS),
            "nav_before": before,
            "nav_after": nav,
            "ml_score": float(row.ml_score),
            "funding_snapshot": funding_rate,
            "entry_impact_rate": entry_impact,
            "exit_impact_rate": exit_impact,
        })
        slot_free = min(int(row.exit_time_ms), end_ms)
        if nav <= 0:
            liquidation_events += 1
            nav = 0.0
            break

    day_starts = np.arange(start_ms, end_ms, v1.DAY_MS, dtype=np.int64)
    daily_values: list[float] = []
    trade_cursor = 0
    realized_nav = initial_nav
    for day_start in day_starts:
        boundary = int(day_start + v1.DAY_MS)
        while trade_cursor < len(trades) and int(trades[trade_cursor]["exit_time_ms"]) < boundary:
            realized_nav = float(trades[trade_cursor]["nav_after"])
            trade_cursor += 1
        equity = realized_nav
        if trade_cursor < len(trades):
            trade = trades[trade_cursor]
            if int(trade["entry_time_ms"]) < boundary <= int(trade["exit_time_ms"]):
                minute = minute_by_symbol[str(trade["symbol"])]
                mark = _mark_close(minute, boundary)
                direction = int(trade["direction"])
                partial_done = trade["partial_time_ms"] is not None and int(trade["partial_time_ms"]) < boundary
                partial_fraction = 0.40 if partial_done else 0.0
                remaining_fraction = 1.0 - partial_fraction
                quantity = float(trade["quantity"])
                notional_remaining = quantity * remaining_fraction * mark
                liquidation_impact = _impact_rate(
                    notional_remaining,
                    _turnover_window(minute, boundary),
                    float(account.impact_bps),
                )
                executable_mark = mark * (1 - direction * (embedded_slippage + liquidation_impact))
                unrealized = quantity * remaining_fraction * (executable_mark - float(trade["entry_price"])) * direction
                partial_realized = (
                    quantity * partial_fraction * (float(trade["partial_price"]) - float(trade["entry_price"])) * direction
                    if partial_done
                    else 0.0
                )
                partial_cost = float(trade["partial_cost"]) if partial_done else 0.0
                hypothetical_exit_cost = quantity * remaining_fraction * executable_mark * fee_rate
                elapsed_days = max(0.0, (boundary - int(trade["entry_time_ms"])) / v1.DAY_MS)
                accrued_funding = direction * float(trade["notional"]) * float(trade["funding_snapshot"]) * elapsed_days * 3.0
                equity = (
                    float(trade["nav_before"])
                    + partial_realized
                    + unrealized
                    - float(trade["entry_cost"])
                    - partial_cost
                    - hypothetical_exit_cost
                    - accrued_funding
                )
        daily_values.append(max(float(equity), 0.0))

    daily = pd.Series(daily_values, index=pd.to_datetime(day_starts, unit="ms", utc=True), dtype=float)
    if len(daily):
        path = pd.concat([pd.Series([initial_nav], index=[daily.index[0] - pd.Timedelta(days=1)]), daily])
    else:
        path = pd.Series([initial_nav], dtype=float)
    pnl_values = np.array([float(trade["net_pnl"]) for trade in trades], dtype=float)
    positive = float(pnl_values[pnl_values > 0].sum()) if len(pnl_values) else 0.0
    negative = float(-pnl_values[pnl_values < 0].sum()) if len(pnl_values) else 0.0
    positive_only = np.maximum(pnl_values, 0)
    top_share = float(np.sort(positive_only)[-5:].sum() / positive_only.sum()) if len(positive_only) and positive_only.sum() > 0 else None
    final_nav = float(daily.iloc[-1]) if len(daily) else nav
    return {
        "initial_nav": initial_nav,
        "final_nav": final_nav,
        "account_multiple": final_nav / initial_nav,
        "geometric_daily_growth": v1.geometric_growth(path),
        "max_drawdown": v1.drawdown(path),
        "completed_trades": len(trades),
        "win_rate": float(np.mean(pnl_values > 0)) if len(pnl_values) else None,
        "profit_factor": float(positive / negative) if negative > 0 else None,
        "top_5_pnl_share": top_share,
        "liquidation_events": liquidation_events,
        "slot_skips": skips,
        "daily_nav": [{"time": ts.isoformat(), "nav": float(value)} for ts, value in daily.items()],
        "trades": trades,
        "daily_nav_method": "UTC midnight executable liquidation value with partial exits, costs and accrued funding",
        "embedded_execution_slippage_bps_per_side": float(account.slippage_bps),
    }


v1.account_sim = account_sim_exact

if __name__ == "__main__":
    raise SystemExit(v3.main_v3())
