#!/usr/bin/env python3
"""Reproduce and correct candidate 021fbab613517a31ad98 without changing its market state."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

CANDIDATE_ID = "021fbab613517a31ad98"
COSTS = (12.0, 18.0, 24.0)


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_verified_modules(source_root: Path, work: Path):
    extension = work / "extension"
    shutil.rmtree(extension, ignore_errors=True)
    shutil.copytree(source_root / "extension", extension)
    shutil.copy2(source_root / "dynamic_factor_residual.py", extension / "dynamic_factor_residual.py")
    dynamic = import_file("dynamic_factor_residual", extension / "dynamic_factor_residual.py")
    rank = import_file("rank_rotation", extension / "rank_rotation.py")
    state = import_file("state_exit", extension / "state_exit.py")
    return dynamic, rank, state


@dataclass
class Trade:
    period: str
    variant: str
    cost_bps: float
    signal_time: str
    symbol: str
    side: int
    entry_time: str
    entry_price: float
    stop_price: float
    exit_time: str | None
    exit_price: float
    exit_reason: str
    completed: bool
    marked: bool
    duration_bars: int
    notional: float
    account_return: float
    pnl: float
    nav_before: float
    nav_after: float


def summarize(trades: list[Trade], start: pd.Timestamp, end: pd.Timestamp) -> dict:
    if not trades:
        return {"trades": 0, "end_nav": 10_000.0}
    returns = np.asarray([x.account_return for x in trades], dtype=float)
    pnl = np.asarray([x.pnl for x in trades], dtype=float)
    nav = np.asarray([10_000.0] + [x.nav_after for x in trades], dtype=float)
    peak = np.maximum.accumulate(nav)
    positive = pnl[pnl > 0]
    negative = -pnl[pnl < 0]
    ordered = np.sort(returns)
    remove = max(1, int(math.ceil(len(returns) * 0.1)))
    keep = len(returns) - remove
    reasons: dict[str, int] = {}
    symbols: dict[str, int] = {}
    for trade in trades:
        reasons[trade.exit_reason] = reasons.get(trade.exit_reason, 0) + 1
        symbols[trade.symbol] = symbols.get(trade.symbol, 0) + 1
    total_return = trades[-1].nav_after / 10_000.0 - 1.0
    days = (end - start).total_seconds() / 86_400.0
    return {
        "trades": len(trades),
        "completed": sum(x.completed for x in trades),
        "marked": sum(x.marked for x in trades),
        "return": total_return,
        "geometric_daily_growth": math.exp(math.log1p(total_return) / days) - 1.0,
        "end_nav": trades[-1].nav_after,
        "profit_factor": float(positive.sum() / negative.sum()) if len(negative) else None,
        "maximum_drawdown": float(np.max(1.0 - nav / peak)),
        "median_account_return_bps": float(np.median(returns) * 10_000.0),
        "mean_account_return_bps": float(np.mean(returns) * 10_000.0),
        "top_five_positive_share": float(np.sort(positive)[-5:].sum() / positive.sum()) if len(positive) else 1.0,
        "top_ten_percent_removed_return": float(np.prod(1.0 + ordered[:keep]) - 1.0) if keep > 0 else -1.0,
        "exit_reasons": reasons,
        "symbol_trades": symbols,
        "maximum_duration_bars": max(x.duration_bars for x in trades),
    }


def corrected_replay(
    D,
    candidate,
    market,
    block,
    bars,
    event_symbols,
    event_sides,
    *,
    period_name: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cost_bps: float,
    remove_timeout: bool,
    correct_entry: bool,
    correct_state_exit: bool,
) -> tuple[list[Trade], dict]:
    start_ms = int(start.value // 1_000_000)
    end_ms = int(end.value // 1_000_000)
    last_bar = int(np.searchsorted(market.times, end_ms, side="left") - 1)
    entry_lag = 2 if correct_entry else 1
    state_exit_lag = 2 if correct_state_exit else 1
    nav = 10_000.0
    busy_until_ms = -10**30
    source_free_signal_bar = -1
    trades: list[Trade] = []
    source_slot_semantics = not correct_entry and not correct_state_exit

    for raw_bar, raw_symbol, raw_side in zip(bars, event_symbols, event_sides):
        signal_bar = int(raw_bar)
        symbol = int(raw_symbol)
        side = int(raw_side)
        activation_ms = int(market.times[signal_bar] + D.BAR_MS + 500)
        if activation_ms < start_ms or activation_ms >= end_ms:
            continue
        if source_slot_semantics:
            if signal_bar < source_free_signal_bar:
                continue
        elif activation_ms <= busy_until_ms:
            continue
        entry_index = signal_bar + entry_lag
        if entry_index > last_bar or entry_index >= len(market.times):
            continue
        if market.times[entry_index] != market.times[signal_bar] + entry_lag * D.BAR_MS:
            continue
        entry_price = float(market.open[symbol, entry_index])
        atr = float(market.atr[symbol, signal_bar])
        if not (np.isfinite(entry_price) and np.isfinite(atr) and entry_price > 0 and atr > 0):
            continue
        distance = max(candidate.stop_atr * atr, entry_price * 0.0015)
        if distance > entry_price * 0.05:
            continue
        stop_price = entry_price - side * distance
        scan_last = last_bar
        if not remove_timeout:
            scan_last = min(scan_last, entry_index + candidate.maximum_hold_bars - 1)

        pending_state_exit: int | None = None
        exit_index: int | None = None
        exit_price = float("nan")
        exit_reason = ""
        completed = False
        for bar in range(entry_index, scan_last + 1):
            open_price = float(market.open[symbol, bar])
            high_price = float(market.high[symbol, bar])
            low_price = float(market.low[symbol, bar])
            if not (np.isfinite(open_price) and np.isfinite(high_price) and np.isfinite(low_price)):
                exit_reason = "invalid"
                break
            if pending_state_exit is not None and bar >= pending_state_exit:
                exit_index = bar
                exit_price = open_price
                exit_reason = "flow_decay"
                completed = True
                break
            if side > 0 and low_price <= stop_price:
                exit_index = bar
                exit_price = open_price if open_price < stop_price else stop_price
                exit_reason = "stop_gap" if open_price < stop_price else "protective_stop"
                completed = True
                break
            if side < 0 and high_price >= stop_price:
                exit_index = bar
                exit_price = open_price if open_price > stop_price else stop_price
                exit_reason = "stop_gap" if open_price > stop_price else "protective_stop"
                completed = True
                break
            held = bar - entry_index + 1
            if pending_state_exit is None and held >= candidate.minimum_hold_bars:
                signed_flow = side * float(block.flow_z[symbol, bar])
                if np.isfinite(signed_flow) and signed_flow < candidate.signed_flow_exit_threshold:
                    target = bar + state_exit_lag
                    if target <= last_bar:
                        pending_state_exit = target

        if exit_reason == "invalid":
            continue
        marked = False
        if exit_index is None:
            if not remove_timeout:
                timeout_index = entry_index + candidate.maximum_hold_bars
                if timeout_index > last_bar or timeout_index >= len(market.times):
                    continue
                exit_index = timeout_index
                exit_price = float(market.open[symbol, timeout_index])
                exit_reason = "maximum_hold"
                completed = True
            else:
                exit_price = float(market.close[symbol, last_bar])
                exit_reason = "boundary_mark"
                marked = True

        planned_loss = distance / entry_price + cost_bps / 10_000.0
        notional = min(
            nav * 0.005 / planned_loss,
            nav * 3.0,
            float(market.quote[symbol, signal_bar]) * 0.001,
        )
        if not (np.isfinite(notional) and notional > 0 and np.isfinite(exit_price)):
            continue
        net_fraction = side * (exit_price / entry_price - 1.0) - cost_bps / 10_000.0
        nav_before = nav
        pnl = net_fraction * notional
        nav = max(1e-12, nav + pnl)

        if completed and exit_index is not None:
            exit_time_ms = int(market.times[exit_index] + D.BAR_MS)
            if source_slot_semantics:
                source_free_signal_bar = exit_index + 1
            elif exit_reason == "flow_decay":
                busy_until_ms = int(market.times[exit_index] + 500)
            else:
                busy_until_ms = exit_time_ms
            exit_time = str(pd.Timestamp(exit_time_ms, unit="ms", tz="UTC"))
            duration_bars = exit_index - entry_index
        else:
            busy_until_ms = end_ms
            exit_time = None
            duration_bars = last_bar - entry_index + 1

        trades.append(Trade(
            period=period_name,
            variant="corrected" if remove_timeout and correct_entry and correct_state_exit else "diagnostic",
            cost_bps=cost_bps,
            signal_time=str(pd.Timestamp(market.times[signal_bar], unit="ms", tz="UTC")),
            symbol=D.SYMBOLS[symbol],
            side=side,
            entry_time=str(pd.Timestamp(market.times[entry_index], unit="ms", tz="UTC")),
            entry_price=entry_price,
            stop_price=stop_price,
            exit_time=exit_time,
            exit_price=exit_price,
            exit_reason=exit_reason,
            completed=completed,
            marked=marked,
            duration_bars=duration_bars,
            notional=notional,
            account_return=pnl / nav_before,
            pnl=pnl,
            nav_before=nav_before,
            nav_after=nav,
        ))
    return trades, summarize(trades, start, end)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    D, R, S = load_verified_modules(args.source_root, args.output / "_verified_source")
    candidate = next(x for x in S.candidates() if x.candidate_id == CANDIDATE_ID)
    entry = S.ENTRY_RULES[candidate.entry_index]

    result = {"schema_version": 1, "candidate": asdict(candidate), "entry": asdict(entry), "periods": {}}
    development = D.load_market(args.snapshot, "development")
    development_blocks = R.build_blocks(development)
    development_block = development_blocks[(entry.beta_window, entry.residual_horizon)]
    dev_bars, dev_symbols, dev_sides = R.events(development_block, entry, development, "development")
    dev_start, dev_end = D.PERIODS["development"]

    original_rows, _ = S.run_stage(args.snapshot, "development", [candidate])
    result["source_reproduction"] = original_rows[0]
    variants = {
        "remove_timeout_only": (True, False, False),
        "correct_activation_keep_timeout": (False, True, True),
        "fully_corrected": (True, True, True),
    }
    result["periods"]["2023"] = {}
    for name, (remove_timeout, correct_entry, correct_exit) in variants.items():
        result["periods"]["2023"][name] = {}
        for cost in COSTS:
            trades, metrics = corrected_replay(
                D, candidate, development, development_block, dev_bars, dev_symbols, dev_sides,
                period_name="2023", start=dev_start, end=dev_end, cost_bps=cost,
                remove_timeout=remove_timeout, correct_entry=correct_entry, correct_state_exit=correct_exit,
            )
            result["periods"]["2023"][name][str(int(cost))] = metrics
            pd.DataFrame([asdict(x) for x in trades]).to_csv(
                args.output / f"2023_{name}_{int(cost)}bps.csv", index=False
            )

    selection = D.load_market(args.snapshot, "selection")
    selection_blocks = R.build_blocks(selection)
    selection_block = selection_blocks[(entry.beta_window, entry.residual_horizon)]
    sel_bars, sel_symbols, sel_sides = R.events(selection_block, entry, selection, "selection")
    h1_start = pd.Timestamp("2024-01-01T00:00:00Z")
    h1_end = pd.Timestamp("2024-07-01T00:00:00Z")
    result["periods"]["2024H1"] = {}
    for cost in COSTS:
        trades, metrics = corrected_replay(
            D, candidate, selection, selection_block, sel_bars, sel_symbols, sel_sides,
            period_name="2024H1", start=h1_start, end=h1_end, cost_bps=cost,
            remove_timeout=True, correct_entry=True, correct_state_exit=True,
        )
        result["periods"]["2024H1"][str(int(cost))] = metrics
        pd.DataFrame([asdict(x) for x in trades]).to_csv(
            args.output / f"2024H1_corrected_{int(cost)}bps.csv", index=False
        )

    (args.output / "AUDIT_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["periods"]["2024H1"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
