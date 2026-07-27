#!/usr/bin/env python3
"""Indexed carrier for run_causal_action_v1 without changing its economics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

import run_causal_action_v1 as v1
from system.coarse import _RangeExtremaIndex
from system.core import EventCandidate


@dataclass(frozen=True)
class PreparedBars:
    data: pd.DataFrame
    starts_ns: np.ndarray
    high: np.ndarray
    low: np.ndarray
    opens: np.ndarray
    closes: np.ndarray
    available: pd.DatetimeIndex
    extrema: _RangeExtremaIndex


def _prepare(frame: pd.DataFrame) -> PreparedBars:
    out = frame.copy().sort_index()
    if "bar_start" not in out:
        out["bar_start"] = out.index
    if "available_at" not in out:
        out["available_at"] = out.index
    out["bar_start"] = pd.to_datetime(out["bar_start"], utc=True)
    out["available_at"] = pd.to_datetime(out["available_at"], utc=True)
    for name in ("open", "high", "low", "close"):
        out[name] = pd.to_numeric(out[name], errors="coerce")
    out = out.sort_values("bar_start", kind="stable").reset_index(drop=True)
    high = out["high"].to_numpy(float)
    low = out["low"].to_numpy(float)
    return PreparedBars(
        data=out,
        starts_ns=pd.DatetimeIndex(out["bar_start"]).as_unit("ns").asi8,
        high=high,
        low=low,
        opens=out["open"].to_numpy(float),
        closes=out["close"].to_numpy(float),
        available=pd.DatetimeIndex(out["available_at"]),
        extrema=_RangeExtremaIndex(low, high),
    )


def _cross(bars: PreparedBars, start: int, level: float, upward: bool,
           end: int, *, strict: bool = False) -> int | None:
    if upward:
        position = bars.extrema.first_high_gt(start, level) if strict else bars.extrema.first_high_ge(start, level)
    else:
        position = bars.extrema.first_low_lt(start, level) if strict else bars.extrema.first_low_le(start, level)
    return position if position is not None and position < end else None


def _label(candidate: EventCandidate, action: str, exit_variant: str, bars: PreparedBars,
           funding: Mapping[str, list[tuple[pd.Timestamp, float]]], evaluation_end: pd.Timestamp,
           config: v1.ScreenConfig, cancel_at: pd.Timestamp | None = None) -> v1.ActionLabel | None:
    side = int(candidate.side)
    evaluation_limit = int(np.searchsorted(bars.starts_ns, evaluation_end.value, side="left"))
    if action == "EARLY_PASSIVE":
        geometry = v1._early_geometry(candidate)
        if geometry is None:
            return None
        signal_time, entry_reference = geometry
        activation = signal_time + pd.Timedelta(milliseconds=config.activation_latency_ms)
    else:
        entry_reference = float(candidate.entry_reference)
        activation = candidate.timestamp + pd.Timedelta(milliseconds=config.activation_latency_ms)
    start = int(np.searchsorted(bars.starts_ns, activation.value, side="left"))
    if start >= evaluation_limit:
        return None
    stop = float(candidate.stop_reference)
    target = float(candidate.target_reference)
    if not (side * (entry_reference - stop) > 0 and side * (target - entry_reference) > 0):
        return None

    if action == "EARLY_PASSIVE":
        invalidation = _cross(bars, start, stop, side < 0, evaluation_limit)
        target_before_fill = _cross(bars, start, target, side > 0, evaluation_limit)
        fill = _cross(bars, start, entry_reference, side < 0, evaluation_limit, strict=True)
        transition_cancel = None
        if cancel_at is not None:
            transition_cancel = int(np.searchsorted(bars.starts_ns, pd.Timestamp(cancel_at).value, side="left"))
            if transition_cancel >= evaluation_limit:
                transition_cancel = None
        boundary_rows = [value for value in (invalidation, target_before_fill, transition_cancel) if value is not None]
        boundary = min(boundary_rows, default=None)
        if fill is None or (boundary is not None and boundary <= fill):
            end_position = boundary if boundary is not None else evaluation_limit - 1
            status = "CANCELLED_ON_CONFIRMED_TRANSITION" if transition_cancel is not None and boundary == transition_cancel else "CANCELLED_OR_UNFILLED"
            return v1.ActionLabel(
                activation, bars.available[end_position], candidate.symbol, action, exit_variant, 0,
                entry_reference, max(abs(entry_reference - stop), 1e-12), 0.0,
                v1._candidate_features(candidate, action, entry_reference), status,
            )
        entry_position = fill
        entry_price = entry_reference
        entry_fee = config.maker_fee_rate
    else:
        entry_position = start
        entry_price = v1._market_fill(bars.opens[entry_position], side, config)
        entry_fee = config.taker_fee_rate
        if not (side * (entry_price - stop) > 0 and side * (target - entry_price) > 0):
            return v1.ActionLabel(
                activation, bars.available[entry_position], candidate.symbol, action, exit_variant, 0,
                entry_price, max(abs(entry_price - stop), 1e-12), 0.0,
                v1._candidate_features(candidate, action, entry_price), "CANCELLED_INVALID_GEOMETRY",
            )

    estimated_stop = stop * (1.0 - side * (config.half_spread_bps + config.stop_slippage_bps) / 10000.0)
    loss_budget = abs(entry_price - estimated_stop) + entry_price * entry_fee + estimated_stop * config.taker_fee_rate
    risk_distance = abs(entry_price - stop)

    if exit_variant == "TP1_50_BE_STRUCT" and abs(target - entry_price) > risk_distance:
        tp1 = entry_price + side * risk_distance
        stop_position = _cross(bars, entry_position, stop, side < 0, evaluation_limit)
        tp1_position = _cross(bars, entry_position, tp1, side > 0, evaluation_limit)
        if stop_position is not None and (tp1_position is None or stop_position <= tp1_position):
            position = stop_position
            base_price = min(bars.opens[position], stop) if side > 0 else max(bars.opens[position], stop)
            exit_price = v1._market_fill(base_price, -side, config, stop=True)
            end = bars.available[position]
            pnl = side * (exit_price - entry_price) - entry_price * entry_fee - exit_price * config.taker_fee_rate
            pnl += v1._funding_pnl_per_unit(candidate.symbol, side, entry_price, bars.available[entry_position], end, funding)
            return v1.ActionLabel(
                activation, end, candidate.symbol, action, exit_variant, 1, entry_price,
                max(loss_budget, 1e-12), pnl, v1._candidate_features(candidate, action, entry_price),
                "STOP_PRE_TP1",
            )
        if tp1_position is None:
            position = max(entry_position, evaluation_limit - 1)
            exit_price = v1._market_fill(bars.closes[position], -side, config)
            end = bars.available[position]
            pnl = side * (exit_price - entry_price) - entry_price * entry_fee - exit_price * config.taker_fee_rate
            pnl += v1._funding_pnl_per_unit(candidate.symbol, side, entry_price, bars.available[entry_position], end, funding)
            return v1.ActionLabel(
                activation, end, candidate.symbol, action, exit_variant, 1, entry_price,
                max(loss_budget, 1e-12), pnl, v1._candidate_features(candidate, action, entry_price),
                "EVALUATION_MARK_PRE_TP1",
            )

        tp1_exit = v1._market_fill(tp1, -side, config)
        pnl = (
            0.5 * side * (tp1_exit - entry_price)
            - entry_price * entry_fee
            - 0.5 * tp1_exit * config.taker_fee_rate
        )
        tp1_time = bars.available[tp1_position]
        cursor = tp1_position + 1
        breakeven_position = _cross(bars, cursor, entry_price, side < 0, evaluation_limit)
        target_position = _cross(bars, cursor, target, side > 0, evaluation_limit)
        if breakeven_position is not None and (target_position is None or breakeven_position <= target_position):
            position = breakeven_position
            final_exit = v1._market_fill(entry_price, -side, config)
            status = "TP1_THEN_BE"
        elif target_position is not None:
            position = target_position
            final_exit = v1._market_fill(target, -side, config)
            status = "TP1_THEN_STRUCTURAL_TARGET"
        else:
            position = max(cursor, evaluation_limit - 1)
            final_exit = v1._market_fill(bars.closes[position], -side, config)
            status = "TP1_THEN_EVALUATION_MARK"
        end = bars.available[position]
        pnl += 0.5 * side * (final_exit - entry_price) - 0.5 * final_exit * config.taker_fee_rate
        pnl += v1._funding_pnl_per_unit(candidate.symbol, side, entry_price, bars.available[entry_position], tp1_time, funding)
        pnl += 0.5 * v1._funding_pnl_per_unit(candidate.symbol, side, entry_price, tp1_time, end, funding)
        return v1.ActionLabel(
            activation, end, candidate.symbol, action, exit_variant, 1, entry_price,
            max(loss_budget, 1e-12), pnl, v1._candidate_features(candidate, action, entry_price), status,
        )

    cap = target if abs(target - entry_price) <= 2.0 * risk_distance else entry_price + side * 2.0 * risk_distance
    effective_target = target if exit_variant == "FULL_STRUCTURAL" else cap
    stop_position = _cross(bars, entry_position, stop, side < 0, evaluation_limit)
    target_position = _cross(bars, entry_position, effective_target, side > 0, evaluation_limit)
    if stop_position is not None and (target_position is None or stop_position <= target_position):
        position = stop_position
        base = min(bars.opens[position], stop) if side > 0 else max(bars.opens[position], stop)
        exit_price = v1._market_fill(base, -side, config, stop=True)
        status = "STOP"
    elif target_position is not None:
        position = target_position
        exit_price = v1._market_fill(effective_target, -side, config)
        status = "STRUCTURAL_TARGET" if effective_target == target else "CAP_2R"
    else:
        position = max(entry_position, evaluation_limit - 1)
        exit_price = v1._market_fill(bars.closes[position], -side, config)
        status = "EVALUATION_MARK"
    end = bars.available[position]
    pnl = side * (exit_price - entry_price) - entry_price * entry_fee - exit_price * config.taker_fee_rate
    pnl += v1._funding_pnl_per_unit(candidate.symbol, side, entry_price, bars.available[entry_position], end, funding)
    return v1.ActionLabel(
        activation, end, candidate.symbol, action, exit_variant, 1, entry_price,
        max(loss_budget, 1e-12), pnl, v1._candidate_features(candidate, action, entry_price), status,
    )


def _rows_fast(candidates: Sequence[EventCandidate], execution: Mapping[str, pd.DataFrame],
               funding: Mapping[tuple[str, pd.Timestamp], float], evaluation_end: pd.Timestamp,
               variants: Sequence[str], config: v1.ScreenConfig) -> pd.DataFrame:
    indexed_funding = v1._funding_index(funding)
    prepared = {symbol: _prepare(frame) for symbol, frame in execution.items()}
    def narrative_key(candidate: EventCandidate) -> tuple[Any, ...]:
        return (
            candidate.symbol, candidate.family.value, candidate.side,
            round(float(candidate.stop_reference), 8),
            round(float(candidate.target_reference), 8),
            round(float(candidate.structural_level), 8),
        )
    market_times: dict[tuple[Any, ...], list[pd.Timestamp]] = {}
    passive_by_symbol: dict[str, list[EventCandidate]] = {}
    for candidate in candidates:
        if float(candidate.feature_row.get("action_candidate_confirmed_market", 0.0)) >= 0.5:
            market_times.setdefault(narrative_key(candidate), []).append(pd.Timestamp(candidate.timestamp))
        if float(candidate.feature_row.get("action_candidate_early_passive", 0.0)) >= 0.5:
            passive_by_symbol.setdefault(candidate.symbol, []).append(candidate)
    for values in market_times.values():
        values.sort()
    for values in passive_by_symbol.values():
        values.sort(key=lambda item: item.timestamp)

    def structural_cancel_at(candidate: EventCandidate) -> pd.Timestamp | None:
        times = [
            time for time in market_times.get(narrative_key(candidate), [])
            if time > candidate.timestamp
        ]
        target_tolerance = max(abs(float(candidate.target_reference)) * 1e-8, 1e-12)
        for later in passive_by_symbol.get(candidate.symbol, []):
            if later.timestamp <= candidate.timestamp:
                continue
            same_draw = abs(float(later.target_reference) - float(candidate.target_reference)) <= target_tolerance
            stronger_same_side = False
            if later.side == candidate.side and later.family == candidate.family and same_draw:
                if candidate.family.value == "LIQUIDITY_SWEEP_REVERSAL":
                    stronger_same_side = (
                        float(later.stop_reference) < float(candidate.stop_reference)
                        if candidate.side > 0
                        else float(later.stop_reference) > float(candidate.stop_reference)
                    )
                else:
                    stronger_same_side = True
            opposing_delivery = (
                later.side == -candidate.side
                and candidate.side * (float(later.decision_price) - float(candidate.entry_reference)) < 0
            )
            if stronger_same_side or opposing_delivery:
                times.append(pd.Timestamp(later.timestamp))
        return min(times) if times else None

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        frame = prepared.get(candidate.symbol)
        if frame is None:
            continue
        for action in ("EARLY_PASSIVE", "CONFIRMED_MARKET"):
            for variant in variants:
                cancel_at = structural_cancel_at(candidate) if action == "EARLY_PASSIVE" else None
                label = _label(
                    candidate, action, variant, frame, indexed_funding, evaluation_end, config, cancel_at
                )
                if label is None:
                    continue
                row = {
                    "activation": label.activation,
                    "event_end": label.event_end,
                    "symbol": label.symbol,
                    "action": label.action,
                    "exit_variant": label.exit_variant,
                    "filled": label.filled,
                    "entry_price": label.entry_price,
                    "loss_budget_per_unit": label.loss_budget_per_unit,
                    "net_pnl_per_unit": label.net_pnl_per_unit,
                    "net_budget_r": label.net_pnl_per_unit / max(label.loss_budget_per_unit, 1e-12),
                    "status": label.status,
                }
                row.update(label.features)
                rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["activation", "symbol", "action", "exit_variant"], kind="stable"
    ).reset_index(drop=True)


v1._rows = _rows_fast

if __name__ == "__main__":
    raise SystemExit(v1.main())
