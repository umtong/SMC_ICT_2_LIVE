#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
QTY_STEP = {"BTCUSDT": 0.001, "ETHUSDT": 0.001, "SOLUSDT": 0.1, "XRPUSDT": 1.0}
MIN_NOTIONAL = {symbol: 5.0 for symbol in SYMBOLS}
START = pd.Timestamp("2022-04-03T00:00:00Z")
END = pd.Timestamp("2024-01-01T00:00:00Z")


@dataclass(frozen=True)
class Cost:
    name: str
    fee_rate: float
    slippage_rate: float


COSTS = (
    Cost("15bp", 0.00055, 0.00020),
    Cost("18bp", 0.00055, 0.00035),
    Cost("24bp", 0.00055, 0.00065),
    Cost("30bp", 0.00110, 0.00040),
)


@dataclass(frozen=True)
class Engine:
    initial_nav: float = 10_000.0
    risk_fraction: float = 0.005
    leverage_cap: float = 5.0
    next_observable_delay_minutes: int = 1


@dataclass
class Trade:
    mode: str
    cost: str
    event_key: str
    symbol: str
    side: int
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    quantity: float
    nav_before: float
    net_pnl: float
    funding_pnl: float
    fees: float
    r_multiple: float
    exit_reason: str
    holding_minutes: int
    leverage: float
    score: float
    protected_promotions: int


def import_original(path: Path):
    spec = importlib.util.spec_from_file_location("registered_absorption_flow", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def round_down(value: float, step: float) -> float:
    return math.floor(value / step + 1e-12) * step if step > 0 else value


def target_trigger(entry_exec: float, unit_loss: float, side: int, reward_risk: float, cost: Cost) -> float:
    target_net = reward_risk * unit_loss
    if side > 0:
        target_exec = (entry_exec * (1 + cost.fee_rate) + target_net) / (1 - cost.fee_rate)
        return target_exec / (1 - cost.slippage_rate)
    target_exec = (entry_exec * (1 - cost.fee_rate) - target_net) / (1 + cost.fee_rate)
    return target_exec / (1 + cost.slippage_rate)


def funding_pnl(symbol: str, side: int, quantity: float, start: pd.Timestamp, end: pd.Timestamp,
                funding: dict[str, pd.DataFrame], minute: dict[str, pd.DataFrame]) -> float:
    settlements = funding[symbol]
    rows = settlements[(settlements.index > start) & (settlements.index <= end)]
    if rows.empty:
        return 0.0
    prices = minute[symbol]
    total = 0.0
    for timestamp, row in rows.iterrows():
        minute_time = timestamp.floor("min")
        position = prices.index.searchsorted(minute_time, side="left")
        if position >= len(prices) or prices.index[position] - minute_time > pd.Timedelta(minutes=2):
            continue
        total += -side * quantity * float(prices.open.iloc[position]) * float(row.funding_rate)
    return float(total)


def strict_15m(minute: pd.DataFrame) -> pd.DataFrame:
    grouped = minute.resample("15min", label="left", closed="left", origin="epoch")
    out = grouped.agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), count=("close", "count"),
    )
    stamps = pd.Series(minute.index, index=minute.index)
    first = stamps.resample("15min", label="left", closed="left", origin="epoch").first()
    last = stamps.resample("15min", label="left", closed="left", origin="epoch").last()
    exact = out["count"].eq(15) & first.eq(first.index) & last.eq(last.index + pd.Timedelta(minutes=14))
    out = out.loc[exact].drop(columns="count")
    out["available_at"] = out.index + pd.Timedelta(minutes=15)
    return out


def confirmed_pivots(fifteen: pd.DataFrame, left: int = 2, right: int = 2):
    highs = fifteen.high.to_numpy(float)
    lows = fifteen.low.to_numpy(float)
    available = pd.DatetimeIndex(fifteen.available_at)
    high_rows: list[tuple[int, pd.Timestamp, float]] = []
    low_rows: list[tuple[int, pd.Timestamp, float]] = []
    for index in range(left, len(fifteen) - right):
        if highs[index] > np.max(highs[index-left:index]) and highs[index] >= np.max(highs[index+1:index+right+1]):
            high_rows.append((index, available[index + right], float(highs[index])))
        if lows[index] < np.min(lows[index-left:index]) and lows[index] <= np.min(lows[index+1:index+right+1]):
            low_rows.append((index, available[index + right], float(lows[index])))
    return high_rows, low_rows


def first_later_close(closes: np.ndarray, available_ns: np.ndarray, confirmation: pd.Timestamp,
                      reference: float, direction: int) -> pd.Timestamp | None:
    start = int(np.searchsorted(available_ns, confirmation.value, side="right"))
    for index in range(start, len(closes)):
        if (direction > 0 and closes[index] > reference) or (direction < 0 and closes[index] < reference):
            return pd.Timestamp(available_ns[index], tz="UTC")
    return None


def protected_promotions(fifteen: pd.DataFrame) -> dict[int, list[tuple[pd.Timestamp, float]]]:
    highs, lows = confirmed_pivots(fifteen)
    closes = fifteen.close.to_numpy(float)
    available_ns = pd.DatetimeIndex(fifteen.available_at).asi8
    output: dict[int, list[tuple[pd.Timestamp, float]]] = {1: [], -1: []}

    prior_high_index = -1
    for pivot_index, confirmation, level in lows:
        while prior_high_index + 1 < len(highs) and highs[prior_high_index + 1][0] < pivot_index and highs[prior_high_index + 1][1] <= confirmation:
            prior_high_index += 1
        if prior_high_index < 0:
            continue
        promotion = first_later_close(closes, available_ns, confirmation, highs[prior_high_index][2], 1)
        if promotion is not None:
            output[1].append((promotion, level))

    prior_low_index = -1
    for pivot_index, confirmation, level in highs:
        while prior_low_index + 1 < len(lows) and lows[prior_low_index + 1][0] < pivot_index and lows[prior_low_index + 1][1] <= confirmation:
            prior_low_index += 1
        if prior_low_index < 0:
            continue
        promotion = first_later_close(closes, available_ns, confirmation, lows[prior_low_index][2], -1)
        if promotion is not None:
            output[-1].append((promotion, level))

    output[1].sort(key=lambda row: row[0])
    output[-1].sort(key=lambda row: row[0])
    return output


def execute(event, candidate, nav: float, minute: dict[str, pd.DataFrame], funding: dict[str, pd.DataFrame],
            cost: Cost, engine: Engine, mode: str, fifteen: dict[str, pd.DataFrame],
            promotions: dict[str, dict[int, list[tuple[pd.Timestamp, float]]]]) -> Trade | None:
    bars = minute[event.symbol]
    corrected_latency = mode != "registered_horizon"
    activation = event.decision_time + (pd.Timedelta(minutes=engine.next_observable_delay_minutes) if corrected_latency else pd.Timedelta(0))
    entry_index = bars.index.searchsorted(activation, side="left")
    if entry_index >= len(bars) or bars.index[entry_index] - activation > pd.Timedelta(minutes=2):
        return None
    entry_time = bars.index[entry_index]
    raw_entry = float(bars.open.iloc[entry_index])
    entry_exec = raw_entry * (1 + cost.slippage_rate * event.side)
    stop = event.stop_reference - candidate.stop_buffer_atr * event.atr if event.side > 0 else event.stop_reference + candidate.stop_buffer_atr * event.atr
    if event.side > 0 and not (0 < stop < raw_entry):
        return None
    if event.side < 0 and not (stop > raw_entry > 0):
        return None
    stop_exec = stop * (1 - cost.slippage_rate * event.side)
    unit_loss = event.side * (entry_exec - stop_exec) + cost.fee_rate * (entry_exec + stop_exec)
    if not np.isfinite(unit_loss) or unit_loss <= 0:
        return None
    target = target_trigger(entry_exec, unit_loss, event.side, candidate.reward_risk, cost)
    risk_cash = nav * engine.risk_fraction
    quantity = min(risk_cash / unit_loss, nav * engine.leverage_cap / entry_exec)
    quantity = round_down(quantity, QTY_STEP[event.symbol])
    if quantity <= 0 or quantity * raw_entry < MIN_NOTIONAL[event.symbol]:
        return None
    leverage = quantity * raw_entry / nav

    horizon_mode = mode in {"registered_horizon", "corrected_horizon"}
    last_time = entry_time + pd.Timedelta(minutes=candidate.maximum_holding_minutes) if horizon_mode else END - pd.Timedelta(minutes=1)
    end_index = min(bars.index.searchsorted(last_time, side="left"), len(bars) - 1)
    segment = bars.iloc[entry_index:end_index + 1]
    if segment.empty or (segment.index.to_series().diff().dropna() > pd.Timedelta(minutes=1)).any():
        return None

    current_protected = float(event.stop_reference)
    promotion_count = 0
    promotion_rows = [(time, level) for time, level in promotions[event.symbol][event.side] if time > entry_time] if mode == "protected_flow" else []
    structure = fifteen[event.symbol]
    close_rows = list(zip(structure.loc[structure.available_at > entry_time, "available_at"], structure.loc[structure.available_at > entry_time, "close"].astype(float))) if mode == "protected_flow" else []
    promotion_index = 0
    close_index = 0
    pending_state_exit: pd.Timestamp | None = None
    exit_time: pd.Timestamp | None = None
    exit_raw: float | None = None
    reason = ""

    for bar_time, row in segment.iterrows():
        open_price, high, low = float(row.open), float(row.high), float(row.low)
        # The standing protective stop wins an adverse gap race at the minute open.
        if event.side > 0 and open_price <= stop:
            exit_time, exit_raw, reason = bar_time, open_price, "gap_stop"
            break
        if event.side < 0 and open_price >= stop:
            exit_time, exit_raw, reason = bar_time, open_price, "gap_stop"
            break
        if pending_state_exit is not None and bar_time >= pending_state_exit:
            exit_time, exit_raw, reason = bar_time, open_price, "protected_flow_loss"
            break
        if event.side > 0:
            if low <= stop:
                exit_time, exit_raw, reason = bar_time, stop, "stop"
                break
            if high >= target:
                exit_time, exit_raw, reason = bar_time, target, "target"
                break
        else:
            if high >= stop:
                exit_time, exit_raw, reason = bar_time, stop, "stop"
                break
            if low <= target:
                exit_time, exit_raw, reason = bar_time, target, "target"
                break

        if mode == "protected_flow":
            while promotion_index < len(promotion_rows) and promotion_rows[promotion_index][0] <= bar_time:
                _, level = promotion_rows[promotion_index]
                if (event.side > 0 and level > current_protected) or (event.side < 0 and level < current_protected):
                    current_protected = level
                    promotion_count += 1
                promotion_index += 1
            while close_index < len(close_rows) and close_rows[close_index][0] <= bar_time:
                available_at, close_price = close_rows[close_index]
                breached = close_price < current_protected if event.side > 0 else close_price > current_protected
                close_index += 1
                if breached:
                    pending_state_exit = available_at + pd.Timedelta(minutes=engine.next_observable_delay_minutes)
                    break

    if exit_time is None:
        if horizon_mode:
            scheduled = entry_time + pd.Timedelta(minutes=candidate.maximum_holding_minutes)
            position = bars.index.searchsorted(scheduled, side="left")
            if position >= len(bars) or bars.index[position] - scheduled > pd.Timedelta(minutes=2):
                return None
            exit_time = bars.index[position]
            exit_raw = float(bars.open.iloc[position])
            reason = "horizon"
        else:
            exit_time = segment.index[-1]
            exit_raw = float(segment.close.iloc[-1])
            reason = "boundary_mtm"

    exit_exec = float(exit_raw) * (1 - cost.slippage_rate * event.side)
    gross = event.side * quantity * (exit_exec - entry_exec)
    fees = quantity * cost.fee_rate * (entry_exec + exit_exec)
    funding_cash = funding_pnl(event.symbol, event.side, quantity, entry_time, exit_time, funding, minute)
    net = gross - fees + funding_cash
    planned_risk = quantity * unit_loss
    event_key = f"{event.symbol}|{event.decision_time.isoformat()}|{event.side}"
    return Trade(
        mode=mode, cost=cost.name, event_key=event_key, symbol=event.symbol, side=event.side,
        signal_time=event.decision_time, entry_time=entry_time, exit_time=exit_time,
        entry_price=entry_exec, exit_price=exit_exec, stop_price=stop, target_price=target,
        quantity=quantity, nav_before=nav, net_pnl=float(net), funding_pnl=float(funding_cash),
        fees=float(fees), r_multiple=float(net / planned_risk), exit_reason=reason,
        holding_minutes=int((exit_time - entry_time) / pd.Timedelta(minutes=1)),
        leverage=float(leverage), score=float(event.score), protected_promotions=promotion_count,
    )


def simulate(events, candidate, minute, funding, cost: Cost, engine: Engine, mode: str,
             fifteen, promotions, removed: set[str] | None = None):
    removed = removed or set()
    events = [event for event in events if START <= event.entry_time < END]
    nav = engine.initial_nav
    free_time = START
    trades: list[Trade] = []
    index = 0
    while index < len(events):
        timestamp = events[index].entry_time
        group = []
        while index < len(events) and events[index].entry_time == timestamp:
            group.append(events[index])
            index += 1
        if timestamp < free_time:
            continue
        selected = max(group, key=lambda event: (event.score, -SYMBOLS.index(event.symbol)))
        event_key = f"{selected.symbol}|{selected.decision_time.isoformat()}|{selected.side}"
        if event_key in removed:
            continue
        trade = execute(selected, candidate, nav, minute, funding, cost, engine, mode, fifteen, promotions)
        if trade is None:
            continue
        nav += trade.net_pnl
        trades.append(trade)
        if nav <= 0:
            break
        free_time = trade.exit_time + pd.Timedelta(minutes=1)

    frame = pd.DataFrame([dataclasses.asdict(trade) for trade in trades])
    daily_index = pd.date_range(START.floor("D"), END, freq="1D", inclusive="left", tz="UTC")
    daily = pd.Series(engine.initial_nav, index=daily_index, dtype=float)
    if not frame.empty:
        frame["exit_time"] = pd.to_datetime(frame.exit_time, utc=True)
        cumulative = engine.initial_nav + frame.set_index("exit_time").net_pnl.cumsum()
        union = daily.index.union(cumulative.index).sort_values()
        daily = cumulative.reindex(union).ffill().fillna(engine.initial_nav).reindex(daily.index, method="ffill").fillna(engine.initial_nav)
    return frame, daily


def metrics(trades: pd.DataFrame, daily: pd.Series, initial_nav: float = 10_000.0) -> dict[str, Any]:
    if trades.empty:
        return {
            "trade_count": 0, "final_nav": initial_nav, "total_return": 0.0,
            "geometric_daily": 0.0, "maximum_drawdown": 0.0, "profit_factor": 0.0,
            "mean_r": None, "median_r": None, "top5_positive_share": 1.0,
            "median_holding_minutes": None, "max_holding_minutes": None,
            "exit_reasons": {}, "symbol_counts": {}, "fees": 0.0, "funding_pnl": 0.0,
        }
    final_nav = initial_nav + float(trades.net_pnl.sum())
    days = float((END - START) / pd.Timedelta(days=1))
    geometric_daily = (final_nav / initial_nav) ** (1 / days) - 1 if final_nav > 0 else -1.0
    curve = daily.to_numpy(float)
    maximum_drawdown = float(np.max(1 - curve / np.maximum.accumulate(curve)))
    positive = trades.loc[trades.net_pnl > 0, "net_pnl"].to_numpy(float)
    negative = -trades.loc[trades.net_pnl < 0, "net_pnl"].to_numpy(float)
    profit_factor = float(positive.sum() / negative.sum()) if negative.sum() > 0 else (999.0 if positive.sum() > 0 else 0.0)
    top5 = float(np.sort(positive)[-5:].sum() / positive.sum()) if len(positive) else 1.0
    return {
        "trade_count": int(len(trades)), "final_nav": final_nav,
        "total_return": final_nav / initial_nav - 1, "geometric_daily": float(geometric_daily),
        "maximum_drawdown": maximum_drawdown, "profit_factor": profit_factor,
        "mean_r": float(trades.r_multiple.mean()), "median_r": float(trades.r_multiple.median()),
        "top5_positive_share": top5,
        "median_holding_minutes": float(trades.holding_minutes.median()),
        "max_holding_minutes": int(trades.holding_minutes.max()),
        "exit_reasons": {str(key): int(value) for key, value in trades.exit_reason.value_counts().items()},
        "symbol_counts": {str(key): int(value) for key, value in trades.symbol.value_counts().items()},
        "fees": float(trades.fees.sum()), "funding_pnl": float(trades.funding_pnl.sum()),
        "protected_promotions": int(trades.protected_promotions.sum()),
    }


def exact_winner_deletion(events, candidate, minute, funding, cost, engine, mode, fifteen, promotions, trades):
    if trades.empty:
        return set(), trades, pd.Series(dtype=float)
    count = min(max(1, math.ceil(len(trades) * 0.10)), len(trades))
    removed = set(trades.nlargest(count, "net_pnl").event_key)
    rerouted, daily = simulate(events, candidate, minute, funding, cost, engine, mode, fifteen, promotions, removed)
    return removed, rerouted, daily


def annual_summary(trades: pd.DataFrame) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    copy = trades.copy()
    copy["year"] = pd.to_datetime(copy.exit_time, utc=True).dt.year
    output = []
    for year, group in copy.groupby("year"):
        positive = group.loc[group.net_pnl > 0, "net_pnl"].sum()
        negative = -group.loc[group.net_pnl < 0, "net_pnl"].sum()
        output.append({
            "year": int(year), "trades": int(len(group)), "net_pnl": float(group.net_pnl.sum()),
            "mean_r": float(group.r_multiple.mean()), "median_r": float(group.r_multiple.median()),
            "profit_factor": float(positive / negative) if negative > 0 else (999.0 if positive > 0 else 0.0),
            "exit_reasons": {str(key): int(value) for key, value in group.exit_reason.value_counts().items()},
        })
    return output


def decide(rows: list[dict[str, Any]], reproduction: dict[str, Any]) -> dict[str, Any]:
    current = [row for row in rows if row["mode"] in {"stop_target_only", "protected_flow"} and row["cost"] in {"18bp", "24bp"}]
    survivors = [
        row for row in current
        if row["trade_count"] >= 40 and row["total_return"] > 0 and row["profit_factor"] > 1
        and row["winner_deletion"]["total_return"] > 0
    ]
    if not reproduction["trade_count_match"] or reproduction["return_abs_error"] > 0.01:
        status = "SOURCE_REPRODUCTION_MISMATCH_FAIL_CLOSED"
    elif survivors:
        status = "CURRENT_CONTRACT_ALPHA_SURVIVOR_PRE2024"
    else:
        status = "RETIRED_ELAPSED_TIME_DEPENDENT_OR_CURRENT_CONTRACT_ECONOMIC_FAILURE"
    return {
        "status": status,
        "eligible_paths": [
            {"mode": row["mode"], "cost": row["cost"], "return": row["total_return"], "trades": row["trade_count"]}
            for row in survivors
        ],
        "official_2024_opened": False,
        "risk_leverage_search_opened": False,
        "ranking_changed": False,
    }


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# Aligned-continuation 33034b current-contract audit",
        "",
        f"- Result: `{result['result_id']}`",
        f"- Candidate: `{result['candidate_id']}`",
        f"- Decision: `{result['decision']['status']}`",
        f"- Events: {result['event_count']}",
        "",
        "## Registered reproduction",
        "",
        f"Expected/observed 15bp trades: {result['reproduction']['expected']['trades']} / {result['reproduction']['observed']['trades']}",
        f"Expected/observed 15bp return: {result['reproduction']['expected']['return']:.6%} / {result['reproduction']['observed']['return']:.6%}",
        "",
        "## Paths",
        "",
        "| mode | cost | trades | return | daily | PF | MDD | median R | median hold | exact winner-deletion | exits |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in result["paths"]:
        lines.append(
            f"| {row['mode']} | {row['cost']} | {row['trade_count']} | {row['total_return']:.4%} | "
            f"{row['geometric_daily']:.6%} | {row['profit_factor']:.3f} | {row['maximum_drawdown']:.3%} | "
            f"{row['median_r']} | {row['median_holding_minutes']} | {row['winner_deletion']['total_return']:.4%} | "
            f"`{json.dumps(row['exit_reasons'], sort_keys=True)}` |"
        )
    lines += [
        "",
        "## Meaning",
        "",
        "`registered_horizon` uses the already-started decision minute and the prohibited 720-minute exit. "
        "`corrected_horizon` changes only fixed-latency activation. `stop_target_only` removes elapsed-time liquidation. "
        "`protected_flow` also permits a causal 15-minute protected-origin state exit. Pivots require two complete right-side bars "
        "and become protected only after a later completed structure expansion; same-close promotion is impossible.",
        "",
        "No credentials or orders were used.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-source", type=Path, required=True)
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    original = import_original(args.original_source)
    minute = {
        symbol: original.load_minute(args.prepared_root / f"{symbol}_minute.parquet")
        for symbol in SYMBOLS
    }
    funding = {
        symbol: original.load_funding(args.prepared_root / f"{symbol}_funding.parquet")
        for symbol in SYMBOLS
    }
    five = {symbol: original.strict_resample_5m(frame) for symbol, frame in minute.items()}
    features = original.prepare_features(five)
    candidate = original.Candidate(
        family="aligned_continuation", horizon_bars=48, z_min=3.0, z_max=math.inf,
        terminal_bars=3, flow_threshold=0.10, efficiency_min=0.45, hold_min=0.70,
        stop_buffer_atr=0.50, reward_risk=4.0, maximum_holding_minutes=720,
        cross_state="idiosyncratic",
    )
    events = original.generate_events(features, candidate, START, END)
    pd.DataFrame([
        {
            "event_key": f"{event.symbol}|{event.decision_time.isoformat()}|{event.side}",
            "symbol": event.symbol, "signal_open_time": event.signal_open_time,
            "decision_time": event.decision_time, "side": event.side, "score": event.score,
            "atr": event.atr, "stop_reference": event.stop_reference,
        }
        for event in events
    ]).to_parquet(args.output / "EVENT_TAPE.parquet", index=False)

    fifteen = {symbol: strict_15m(frame) for symbol, frame in minute.items()}
    promotions = {symbol: protected_promotions(fifteen[symbol]) for symbol in SYMBOLS}
    engine = Engine()
    paths: list[dict[str, Any]] = []
    ledgers: list[pd.DataFrame] = []
    for cost in COSTS:
        for mode in ("registered_horizon", "corrected_horizon", "stop_target_only", "protected_flow"):
            trades, daily = simulate(events, candidate, minute, funding, cost, engine, mode, fifteen, promotions)
            summary = metrics(trades, daily)
            removed, rerouted, rerouted_daily = exact_winner_deletion(
                events, candidate, minute, funding, cost, engine, mode, fifteen, promotions, trades
            )
            winner_summary = metrics(rerouted, rerouted_daily) if not rerouted_daily.empty else metrics(rerouted, daily * 0 + engine.initial_nav)
            row = {
                "mode": mode, "cost": cost.name, **summary,
                "winner_deletion": {"removed_count": len(removed), **winner_summary},
                "annual_exit_summary": annual_summary(trades),
            }
            paths.append(row)
            if not trades.empty:
                copy = trades.copy()
                copy["reported_mode"] = mode
                ledgers.append(copy)
            print(mode, cost.name, summary["trade_count"], summary["total_return"], summary["exit_reasons"], flush=True)

    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_parquet(args.output / "TRADE_LEDGER.parquet", index=False)
    registered = next(row for row in paths if row["mode"] == "registered_horizon" and row["cost"] == "15bp")
    expected = {"trades": 184, "return": 0.15627618264978582, "profit_factor": 1.3064535362764598}
    reproduction = {
        "expected": expected,
        "observed": {
            "trades": registered["trade_count"], "return": registered["total_return"],
            "profit_factor": registered["profit_factor"],
        },
        "trade_count_match": registered["trade_count"] == expected["trades"],
        "return_abs_error": abs(registered["total_return"] - expected["return"]),
        "profit_factor_abs_error": abs(registered["profit_factor"] - expected["profit_factor"]),
    }
    decision = decide(paths, reproduction)
    result = {
        "schema_version": 1,
        "result_id": "RES-20260730-ALIGNED-CONTINUATION-CURRENT-CONTRACT-001",
        "claim_id": "CLM-20260730-ALIGNED-CONTINUATION-AUDIT-001",
        "candidate_id": candidate.candidate_id,
        "period": [START.isoformat(), END.isoformat()],
        "event_count": len(events),
        "reproduction": reproduction,
        "paths": paths,
        "decision": decision,
        "known_limitations": [
            "Maximum drawdown is based on realized daily NAV rather than full minute-by-minute unrealized NAV.",
            "The first pass uses the registered Binance signal and execution venue to isolate lifecycle and activation dependence; Bybit transport opens only for a current-contract survivor.",
        ],
        "orders_submitted": False,
    }
    (args.output / "RESULT.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (args.output / "REPORT.md").write_text(render_report(result), encoding="utf-8")
    print(json.dumps({"reproduction": reproduction, "decision": decision}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
