#!/usr/bin/env python3
"""Quality-gated partial-profit and causal structural-runner research.

The entry gate is frozen from pre-2024 H1/H2 stability.  Exit variants are selected
on 2023H1, validated unchanged on 2023H2, and only a positive H2 survivor may be
applied to the already-frozen 2024H1 candidate/action list.  Runner stops use only
pivots whose right-hand bars have closed; no elapsed-time strategy exit is used.
Evaluation-end liquidation is NAV marking, not a strategy rule.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


MAKER_FEE = 0.0002
TAKER_FEE = 0.00055
ENTRY_SLIPPAGE = 0.0002
STOP_SLIPPAGE = 0.0004
MIN_SPREAD_BPS = 0.5
LATENCY_MS = 500


GATE = {
    "reversal_target_distance_atr_min": 5.5,
    "reversal_sweep_depth_atr_min": 1.0,
    "reversal_external_rr_min": 1.0,
    "continuation_stop_distance_atr_min": 3.5,
    "continuation_path_excursion_atr_min": 5.0,
    "continuation_external_rr_min": 2.0,
}


@dataclass(frozen=True)
class Candidate:
    timestamp: pd.Timestamp
    symbol: str
    family: str
    side: int
    entry: float
    stop: float
    target: float
    atr: float
    action: str = "PASSIVE_RETEST"
    priority_score: float = 0.0


@dataclass(frozen=True)
class Variant:
    name: str
    partial_fraction: float = 0.0
    partial_mode: str = "TARGET"
    partial_r: float = 0.0
    break_even_after_partial: bool = False
    pivot_left: int = 2
    pivot_right: int = 2
    pivot_buffer_atr: float = 0.10


@dataclass(frozen=True)
class Outcome:
    decision_time: pd.Timestamp
    symbol: str
    family: str
    side: int
    action: str
    status: str
    entry_time: pd.Timestamp | None
    exit_time: pd.Timestamp
    entry_price: float | None
    stop_distance: float
    per_unit_pnl: float
    partial_time: pd.Timestamp | None
    partial_price: float | None
    final_exit_price: float | None
    funding_per_unit: float
    hold_hours: float
    priority_score: float


@dataclass(frozen=True)
class AccountResult:
    start_nav: float
    end_nav: float
    account_multiple: float
    geometric_daily_growth: float
    maximum_drawdown: float
    completed_trades: int
    filled_trades: int
    win_rate: float | None
    mean_budget_r: float | None
    median_budget_r: float | None
    profit_factor: float | None
    top_five_positive_pnl_share: float | None
    winner_removal_return: float | None
    average_hold_hours: float | None
    trades: tuple[dict[str, Any], ...]


def gate_mask(rows: pd.DataFrame) -> pd.Series:
    family = rows["family"].astype(str)
    rr = pd.to_numeric(rows["raw_reward_risk"], errors="coerce")
    reversal = (
        family.eq("LIQUIDITY_SWEEP_REVERSAL")
        & pd.to_numeric(rows["target_distance_atr"], errors="coerce").ge(GATE["reversal_target_distance_atr_min"])
        & pd.to_numeric(rows["sweep_depth_atr"], errors="coerce").ge(GATE["reversal_sweep_depth_atr_min"])
        & rr.ge(GATE["reversal_external_rr_min"])
    )
    continuation = (
        family.eq("DISPLACEMENT_BREAK_RETEST_CONTINUATION")
        & pd.to_numeric(rows["stop_distance_atr"], errors="coerce").ge(GATE["continuation_stop_distance_atr_min"])
        & pd.to_numeric(rows["path_excursion_atr"], errors="coerce").ge(GATE["continuation_path_excursion_atr_min"])
        & rr.ge(GATE["continuation_external_rr_min"])
    )
    return reversal | continuation


def reconstruct(row: pd.Series) -> Candidate:
    atr = float(row["atr"])
    stop_distance = atr * float(row["stop_distance_atr"])
    target_distance = atr * float(row["target_distance_atr"])
    target_fraction = float(row["target_distance_fraction"])
    stop_fraction = float(row["stop_distance_fraction"])
    if target_fraction > 0:
        entry = target_distance / target_fraction
    elif stop_fraction > 0:
        entry = stop_distance / stop_fraction
    else:
        raise ValueError("cannot reconstruct entry")
    side = int(row["side"])
    return Candidate(
        timestamp=pd.Timestamp(row["event_start"]),
        symbol=str(row["symbol"]),
        family=str(row["family"]),
        side=side,
        entry=float(entry),
        stop=float(entry - side * stop_distance),
        target=float(entry + side * target_distance),
        atr=atr,
        action="PASSIVE_RETEST",
    )


def candidates_from_labels(path: Path) -> list[Candidate]:
    rows = pd.read_pickle(path, compression="gzip")
    rows["event_start"] = pd.to_datetime(rows["event_start"], utc=True)
    rows = rows.loc[gate_mask(rows)].copy()
    result = [reconstruct(row) for _, row in rows.iterrows()]
    result.sort(key=lambda item: (item.timestamp, item.symbol, item.family, item.side))
    return result


def candidates_from_frozen_pointer(path: Path) -> list[Candidate]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: list[Candidate] = []
    for row in payload.get("result", {}).get("candidate_scores", []):
        if not row.get("passes_threshold"):
            continue
        action = str(row.get("preferred_action") or "PASSIVE_RETEST")
        score = float(
            row.get("predicted_passive_budget_r")
            if action == "PASSIVE_RETEST"
            else row.get("predicted_market_budget_r")
        )
        entry = float(row["entry_reference"])
        stop = float(row["stop_reference"])
        target = float(row["target_reference"])
        stop_distance = abs(entry - stop)
        result.append(
            Candidate(
                timestamp=pd.Timestamp(row["timestamp"]),
                symbol=str(row["symbol"]),
                family=str(row["family"]),
                side=int(row["side"]),
                entry=entry,
                stop=stop,
                target=target,
                atr=max(stop_distance, 1e-12),
                action=action,
                priority_score=score,
            )
        )
    result.sort(key=lambda item: (item.timestamp, -item.priority_score, item.symbol))
    return result


def normalize_bars(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    mapping = {
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
    }
    for source, target in mapping.items():
        if source in frame.columns and target not in frame.columns:
            frame[target] = frame[source]
    if "start_time_ms" in frame.columns:
        index = pd.to_datetime(frame["start_time_ms"], unit="ms", utc=True)
    elif "timestamp_ms" in frame.columns:
        index = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
    elif isinstance(frame.index, pd.DatetimeIndex):
        index = pd.to_datetime(frame.index, utc=True)
    else:
        raise ValueError(f"no time axis in {path}")
    result = frame.copy()
    result.index = index
    for column in ("open", "high", "low", "close"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if "spread_bps" in result.columns:
        result["spread_bps"] = pd.to_numeric(result["spread_bps"], errors="coerce").fillna(MIN_SPREAD_BPS)
    else:
        result["spread_bps"] = MIN_SPREAD_BPS
    return result[["open", "high", "low", "close", "spread_bps"]].dropna().sort_index()


def normalize_marks(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    if "start_time_ms" in frame.columns:
        index = pd.to_datetime(frame["start_time_ms"], unit="ms", utc=True)
    elif "timestamp_ms" in frame.columns:
        index = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
    else:
        index = pd.to_datetime(frame.index, utc=True)
    value_column = next((name for name in ("close", "close_price", "mark_price") if name in frame.columns), None)
    if value_column is None:
        raise ValueError(f"mark column missing: {path}")
    values = pd.to_numeric(frame[value_column], errors="coerce")
    values.index = index
    return values.dropna().sort_index()


def normalize_funding(path: Path) -> list[tuple[pd.Timestamp, float]]:
    frame = pd.read_parquet(path)
    if "timestamp_ms" in frame.columns:
        index = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
    elif "start_time_ms" in frame.columns:
        index = pd.to_datetime(frame["start_time_ms"], unit="ms", utc=True)
    else:
        index = pd.to_datetime(frame.index, utc=True)
    column = next((name for name in ("funding_rate", "fundingRate") if name in frame.columns), None)
    if column is None:
        return []
    values = pd.to_numeric(frame[column], errors="coerce")
    return sorted((pd.Timestamp(timestamp), float(rate)) for timestamp, rate in zip(index, values) if pd.notna(rate))


def mark_asof(marks: pd.Series, timestamp: pd.Timestamp) -> float:
    position = int(np.searchsorted(marks.index.as_unit("ns").asi8, timestamp.value, side="right")) - 1
    position = max(0, min(position, len(marks) - 1))
    return float(marks.iloc[position])


def funding_pnl(
    events: Sequence[tuple[pd.Timestamp, float]],
    marks: pd.Series,
    candidate: Candidate,
    entry_time: pd.Timestamp,
    exit_time: pd.Timestamp,
) -> float:
    total = 0.0
    for timestamp, rate in events:
        if entry_time <= timestamp < exit_time:
            total += -candidate.side * mark_asof(marks, timestamp) * rate
    return total


def strict_cross(row: pd.Series, side: int, level: float) -> bool:
    return float(row["high"]) > level if side > 0 else float(row["low"]) < level


def stop_touch(row: pd.Series, side: int, level: float) -> bool:
    return float(row["low"]) <= level if side > 0 else float(row["high"]) >= level


def adverse_market_fill(open_price: float, side: int, spread_bps: float) -> float:
    fraction = max(float(spread_bps), MIN_SPREAD_BPS) / 20000 + ENTRY_SLIPPAGE
    return open_price * (1 + side * fraction)


def adverse_stop_fill(stop: float, side: int) -> float:
    return stop * (1 - STOP_SLIPPAGE if side > 0 else 1 + STOP_SLIPPAGE)


def partial_level(candidate: Candidate, variant: Variant, entry_price: float) -> float:
    if variant.partial_mode == "TARGET":
        return candidate.target
    distance = abs(entry_price - candidate.stop)
    return entry_price + candidate.side * variant.partial_r * distance


def pivot_update(
    bars: pd.DataFrame,
    position: int,
    candidate: Candidate,
    variant: Variant,
    current_stop: float,
) -> float:
    left, right = variant.pivot_left, variant.pivot_right
    if position < left + right:
        return current_stop
    pivot = position - right
    start = pivot - left
    end = pivot + right + 1
    if start < 0:
        return current_stop
    window = bars.iloc[start:end]
    close_now = float(bars.iloc[position]["close"])
    if candidate.side > 0:
        value = float(bars.iloc[pivot]["low"])
        if value != float(window["low"].min()):
            return current_stop
        proposed = value - variant.pivot_buffer_atr * candidate.atr
        return max(current_stop, proposed) if proposed < close_now else current_stop
    value = float(bars.iloc[pivot]["high"])
    if value != float(window["high"].max()):
        return current_stop
    proposed = value + variant.pivot_buffer_atr * candidate.atr
    return min(current_stop, proposed) if proposed > close_now else current_stop


def simulate_one(
    candidate: Candidate,
    bars: pd.DataFrame,
    marks: pd.Series,
    funding_events: Sequence[tuple[pd.Timestamp, float]],
    variant: Variant,
    period_end: pd.Timestamp,
) -> Outcome:
    times = bars.index.as_unit("ns").asi8
    activation = candidate.timestamp + pd.Timedelta(milliseconds=LATENCY_MS)
    start = int(np.searchsorted(times, activation.value, side="right"))
    end_position = int(np.searchsorted(times, period_end.value, side="left"))
    end_position = min(end_position, len(bars))
    if start >= end_position:
        return Outcome(candidate.timestamp, candidate.symbol, candidate.family, candidate.side, candidate.action, "NO_EXECUTION_BAR", None, period_end, None, abs(candidate.entry-candidate.stop), 0.0, None, None, None, 0.0, 0.0, candidate.priority_score)

    entry_time: pd.Timestamp | None = None
    entry_price: float | None = None
    entry_position: int | None = None
    entry_fee_rate = TAKER_FEE
    if candidate.action == "PASSIVE_RETEST":
        for position in range(start, end_position):
            row = bars.iloc[position]
            if stop_touch(row, candidate.side, candidate.stop) or strict_cross(row, candidate.side, candidate.target):
                return Outcome(candidate.timestamp, candidate.symbol, candidate.family, candidate.side, candidate.action, "CANCELLED_BEFORE_FILL", None, pd.Timestamp(bars.index[position]), None, abs(candidate.entry-candidate.stop), 0.0, None, None, None, 0.0, 0.0, candidate.priority_score)
            crossed = float(row["low"]) < candidate.entry if candidate.side > 0 else float(row["high"]) > candidate.entry
            if crossed:
                entry_time = pd.Timestamp(bars.index[position])
                entry_price = candidate.entry
                entry_position = position
                entry_fee_rate = MAKER_FEE
                break
    else:
        entry_position = start
        row = bars.iloc[entry_position]
        entry_time = pd.Timestamp(bars.index[entry_position])
        entry_price = adverse_market_fill(float(row["open"]), candidate.side, float(row["spread_bps"]))
        protective = candidate.side * (entry_price - candidate.stop)
        reward = candidate.side * (candidate.target - entry_price)
        if protective <= 0 or reward <= 0:
            return Outcome(candidate.timestamp, candidate.symbol, candidate.family, candidate.side, candidate.action, "CANCELLED_BAD_LATENCY_GEOMETRY", None, entry_time, None, abs(candidate.entry-candidate.stop), 0.0, None, None, None, 0.0, 0.0, candidate.priority_score)

    if entry_time is None or entry_price is None or entry_position is None:
        return Outcome(candidate.timestamp, candidate.symbol, candidate.family, candidate.side, candidate.action, "UNFILLED_AT_PERIOD_END", None, period_end, None, abs(candidate.entry-candidate.stop), 0.0, None, None, None, 0.0, 0.0, candidate.priority_score)

    stop_distance = abs(entry_price - candidate.stop)
    current_stop = candidate.stop
    remaining = 1.0
    gross = 0.0
    fees = entry_price * entry_fee_rate
    partial_time: pd.Timestamp | None = None
    partial_price: float | None = None
    final_price: float | None = None
    exit_time = period_end
    status = "EVALUATION_MARK"
    level = partial_level(candidate, variant, entry_price)

    for position in range(entry_position, end_position):
        row = bars.iloc[position]
        timestamp = pd.Timestamp(bars.index[position])
        if stop_touch(row, candidate.side, current_stop):
            final_price = adverse_stop_fill(current_stop, candidate.side)
            gross += remaining * candidate.side * (final_price - entry_price)
            fees += remaining * final_price * TAKER_FEE
            exit_time = timestamp
            status = "STOP" if partial_time is None else "RUNNER_STOP"
            remaining = 0.0
            break

        if variant.partial_fraction <= 0:
            if strict_cross(row, candidate.side, candidate.target):
                final_price = candidate.target
                gross += candidate.side * (final_price - entry_price)
                fees += final_price * MAKER_FEE
                exit_time = timestamp
                status = "TARGET"
                remaining = 0.0
                break
        elif partial_time is None and strict_cross(row, candidate.side, level):
            fraction = variant.partial_fraction
            partial_time = timestamp
            partial_price = level
            gross += fraction * candidate.side * (level - entry_price)
            fees += fraction * level * MAKER_FEE
            remaining -= fraction
            if variant.break_even_after_partial:
                current_stop = max(current_stop, entry_price) if candidate.side > 0 else min(current_stop, entry_price)

        if partial_time is not None and remaining > 0:
            current_stop = pivot_update(bars, position, candidate, variant, current_stop)

    if remaining > 0:
        last_position = max(entry_position, end_position - 1)
        row = bars.iloc[last_position]
        spread = max(float(row["spread_bps"]), MIN_SPREAD_BPS) / 20000 + ENTRY_SLIPPAGE
        close = float(row["close"])
        final_price = close * (1 - spread if candidate.side > 0 else 1 + spread)
        gross += remaining * candidate.side * (final_price - entry_price)
        fees += remaining * final_price * TAKER_FEE
        exit_time = period_end
        status = "EVALUATION_MARK" if partial_time is None else "RUNNER_EVALUATION_MARK"

    funding = funding_pnl(funding_events, marks, candidate, entry_time, exit_time)
    pnl = gross - fees + funding
    hold_hours = max(0.0, (exit_time - entry_time).total_seconds() / 3600)
    return Outcome(candidate.timestamp, candidate.symbol, candidate.family, candidate.side, candidate.action, status, entry_time, exit_time, entry_price, stop_distance, pnl, partial_time, partial_price, final_price, funding, hold_hours, candidate.priority_score)


def account_replay(
    outcomes: Sequence[Outcome],
    start: pd.Timestamp,
    end: pd.Timestamp,
    risk_fraction: float,
    maximum_leverage: float,
    initial_nav: float = 10000.0,
) -> AccountResult:
    grouped: dict[pd.Timestamp, list[Outcome]] = {}
    for outcome in outcomes:
        if start <= outcome.decision_time < end:
            grouped.setdefault(outcome.decision_time, []).append(outcome)
    nav = initial_nav
    peak = nav
    maximum_drawdown = 0.0
    release = start
    pnl_values: list[float] = []
    budget_rs: list[float] = []
    holds: list[float] = []
    trades: list[dict[str, Any]] = []
    filled = 0
    for decision_time in sorted(grouped):
        if decision_time < release:
            continue
        outcome = sorted(grouped[decision_time], key=lambda row: (-row.priority_score, row.symbol, row.family))[0]
        release = min(max(outcome.exit_time, decision_time), end)
        if outcome.entry_time is None or outcome.entry_price is None:
            trades.append({**asdict(outcome), "quantity": 0.0, "net_pnl": 0.0, "budget_r": 0.0, "nav_after": nav})
            continue
        filled += 1
        planned_per_unit = (
            outcome.stop_distance
            + outcome.entry_price * (MAKER_FEE if outcome.action == "PASSIVE_RETEST" else TAKER_FEE)
            + abs(outcome.entry_price - outcome.stop_distance) * (TAKER_FEE + STOP_SLIPPAGE)
        )
        risk_quantity = nav * risk_fraction / max(planned_per_unit, 1e-12)
        leverage_quantity = nav * maximum_leverage / outcome.entry_price
        maximum_safe_leverage = 1.0 / max(outcome.stop_distance / outcome.entry_price + 0.005 + 0.0025, 1e-12)
        liquidation_quantity = nav * min(maximum_leverage, maximum_safe_leverage) / outcome.entry_price
        quantity = max(0.0, min(risk_quantity, leverage_quantity, liquidation_quantity))
        pnl = quantity * outcome.per_unit_pnl
        entry_nav = nav
        nav += pnl
        if nav <= 0:
            nav = 0.0
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, 1.0 - nav / max(peak, 1e-12))
        budget_r = outcome.per_unit_pnl / max(planned_per_unit, 1e-12)
        pnl_values.append(pnl)
        budget_rs.append(budget_r)
        holds.append(outcome.hold_hours)
        trades.append({**asdict(outcome), "quantity": quantity, "net_pnl": pnl, "budget_r": budget_r, "entry_nav": entry_nav, "nav_after": nav})
        if nav <= 0:
            break

    days = max(1, int((end - start).total_seconds() // 86400))
    multiple = nav / initial_nav
    geometric = float(multiple ** (1.0 / days) - 1.0) if multiple > 0 else -1.0
    values = np.asarray(pnl_values, dtype=float)
    positives = values[values > 0]
    negatives = values[values < 0]
    top_share = float(np.sort(positives)[-5:].sum() / positives.sum()) if positives.size and positives.sum() > 0 else None
    winner_removal_nav = nav - float(positives.max()) if positives.size else nav
    return AccountResult(
        start_nav=initial_nav,
        end_nav=nav,
        account_multiple=multiple,
        geometric_daily_growth=geometric,
        maximum_drawdown=maximum_drawdown,
        completed_trades=len(trades),
        filled_trades=filled,
        win_rate=float((values > 0).mean()) if values.size else None,
        mean_budget_r=float(np.mean(budget_rs)) if budget_rs else None,
        median_budget_r=float(np.median(budget_rs)) if budget_rs else None,
        profit_factor=float(positives.sum() / abs(negatives.sum())) if positives.size and negatives.size and negatives.sum() != 0 else None,
        top_five_positive_pnl_share=top_share,
        winner_removal_return=winner_removal_nav / initial_nav - 1.0,
        average_hold_hours=float(np.mean(holds)) if holds else None,
        trades=tuple(trades),
    )


def variants() -> tuple[Variant, ...]:
    result = [Variant("BASELINE_FULL_TARGET")]
    for partial_fraction in (0.25, 0.50, 0.75):
        for mode, partial_r in (("TARGET", 0.0), ("R", 1.0), ("R", 2.0)):
            for right in (2, 3):
                name = f"P{int(partial_fraction*100)}_{'TARGET' if mode=='TARGET' else f'{partial_r:.0f}R'}_BE_SWING{right}"
                result.append(
                    Variant(
                        name=name,
                        partial_fraction=partial_fraction,
                        partial_mode=mode,
                        partial_r=partial_r,
                        break_even_after_partial=True,
                        pivot_left=right,
                        pivot_right=right,
                        pivot_buffer_atr=0.10,
                    )
                )
    return tuple(result)


def simulate_set(
    candidates: Sequence[Candidate],
    bars: Mapping[str, pd.DataFrame],
    marks: Mapping[str, pd.Series],
    funding: Mapping[str, Sequence[tuple[pd.Timestamp, float]]],
    variant: Variant,
    end: pd.Timestamp,
) -> list[Outcome]:
    return [simulate_one(candidate, bars[candidate.symbol], marks[candidate.symbol], funding[candidate.symbol], variant, end) for candidate in candidates]


def load_symbol_inputs(args: argparse.Namespace, prefix: str) -> tuple[dict[str, pd.DataFrame], dict[str, pd.Series], dict[str, list[tuple[pd.Timestamp, float]]]]:
    bars = {
        "BTCUSDT": normalize_bars(getattr(args, f"btc_{prefix}_bars")),
        "ETHUSDT": normalize_bars(getattr(args, f"eth_{prefix}_bars")),
    }
    marks = {
        "BTCUSDT": normalize_marks(getattr(args, f"btc_{prefix}_marks")),
        "ETHUSDT": normalize_marks(getattr(args, f"eth_{prefix}_marks")),
    }
    funding = {
        "BTCUSDT": normalize_funding(getattr(args, f"btc_{prefix}_funding")),
        "ETHUSDT": normalize_funding(getattr(args, f"eth_{prefix}_funding")),
    }
    return bars, marks, funding


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output.mkdir(parents=True, exist_ok=True)
    candidates_2023 = candidates_from_labels(args.labels)
    bars_2023, marks_2023, funding_2023 = load_symbol_inputs(args, "2023")
    h1_start = pd.Timestamp("2023-01-01T00:00:00Z")
    h1_end = pd.Timestamp("2023-07-01T00:00:00Z")
    h2_start = h1_end
    h2_end = pd.Timestamp("2024-01-01T00:00:00Z")

    discovery: list[dict[str, Any]] = []
    outcomes_by_variant: dict[str, list[Outcome]] = {}
    for variant in variants():
        outcomes = simulate_set(candidates_2023, bars_2023, marks_2023, funding_2023, variant, h2_end)
        outcomes_by_variant[variant.name] = outcomes
        basic_h1 = account_replay(outcomes, h1_start, h1_end, 0.01, 5.0)
        growth_h1 = account_replay(outcomes, h1_start, h1_end, 0.17, 20.0)
        discovery.append({"variant": asdict(variant), "basic_h1": asdict(basic_h1), "growth_h1": asdict(growth_h1)})

    eligible = [row for row in discovery if row["basic_h1"]["filled_trades"] >= 8]
    selected_row = max(
        eligible,
        key=lambda row: (
            row["basic_h1"]["geometric_daily_growth"],
            -row["basic_h1"]["maximum_drawdown"],
            row["basic_h1"]["filled_trades"],
            row["variant"]["name"],
        ),
    )
    selected = Variant(**selected_row["variant"])
    selected_outcomes = outcomes_by_variant[selected.name]
    basic_h2 = account_replay(selected_outcomes, h2_start, h2_end, 0.01, 5.0)
    growth_h2 = account_replay(selected_outcomes, h2_start, h2_end, 0.17, 20.0)

    frozen_2024: dict[str, Any] | None = None
    h2_pass = basic_h2.geometric_daily_growth > 0 and basic_h2.filled_trades >= 8
    if h2_pass:
        candidates_2024 = candidates_from_frozen_pointer(args.frozen_pointer)
        bars_2024, marks_2024, funding_2024 = load_symbol_inputs(args, "2024h1")
        start_2024 = pd.Timestamp("2024-01-01T00:00:00Z")
        end_2024 = pd.Timestamp("2024-07-01T00:00:00Z")
        outcomes_2024 = simulate_set(candidates_2024, bars_2024, marks_2024, funding_2024, selected, end_2024)
        frozen_2024 = {
            "candidate_count": len(candidates_2024),
            "basic": asdict(account_replay(outcomes_2024, start_2024, end_2024, 0.01, 5.0)),
            "growth": asdict(account_replay(outcomes_2024, start_2024, end_2024, 0.17, 20.0)),
        }

    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "stage": "QUALITY_GATED_STRUCTURAL_RUNNER_H1_DISCOVERY_H2_VALIDATION_CONDITIONAL_2024H1",
        "quality_gate": GATE,
        "entry_contract_2023": "PASSIVE_RETEST_ONLY_500MS_TRADE_THROUGH",
        "entry_contract_2024": "FROZEN_ACTIONS_FROM_FROZEN_2024H1_V2_POINTER",
        "candidate_count_2023": len(candidates_2023),
        "variant_count": len(discovery),
        "discovery": discovery,
        "selected_variant": asdict(selected),
        "validation_2023H2": {"basic": asdict(basic_h2), "growth": asdict(growth_h2), "passed": h2_pass},
        "frozen_2024H1": frozen_2024,
        "ranking_effect": "NONE_PROVISIONAL_1M_NOT_EVENT_TAPE_VALIDATED",
    }
    path = args.output / "QUALITY_STRUCTURAL_RUNNER_RESULT.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (args.output / "QUALITY_STRUCTURAL_RUNNER_RESULT.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--frozen-pointer", type=Path, required=True)
    parser.add_argument("--btc-2023-bars", type=Path, required=True)
    parser.add_argument("--btc-2023-marks", type=Path, required=True)
    parser.add_argument("--btc-2023-funding", type=Path, required=True)
    parser.add_argument("--eth-2023-bars", type=Path, required=True)
    parser.add_argument("--eth-2023-marks", type=Path, required=True)
    parser.add_argument("--eth-2023-funding", type=Path, required=True)
    parser.add_argument("--btc-2024h1-bars", type=Path, required=True)
    parser.add_argument("--btc-2024h1-marks", type=Path, required=True)
    parser.add_argument("--btc-2024h1-funding", type=Path, required=True)
    parser.add_argument("--eth-2024h1-bars", type=Path, required=True)
    parser.add_argument("--eth-2024h1-marks", type=Path, required=True)
    parser.add_argument("--eth-2024h1-funding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    result = run(parser.parse_args(argv))
    print(json.dumps({"selected_variant": result["selected_variant"], "validation_2023H2": result["validation_2023H2"], "frozen_2024H1": result["frozen_2024H1"]}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
