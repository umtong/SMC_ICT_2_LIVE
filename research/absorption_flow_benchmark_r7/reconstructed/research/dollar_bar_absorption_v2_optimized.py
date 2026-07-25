#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import gc
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

BASE_PATH = Path(__file__).with_name("dollar_bar_absorption_v2.py")
spec = importlib.util.spec_from_file_location("dbar_v2", BASE_PATH)
m = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = m
spec.loader.exec_module(m)
base = m.base


def load_execution_minute(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path, columns=["timestamp", "open", "high", "low", "close"])
    frame = frame.copy()
    frame.index = base.normalize_timestamp(frame.pop("timestamp"))
    frame.index.name = "timestamp"
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{path}: timestamp order")
    for col in frame:
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    invalid = (
        (frame.high < frame[["open", "close"]].max(axis=1))
        | (frame.low > frame[["open", "close"]].min(axis=1))
        | (frame.high < frame.low)
        | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    if invalid.any():
        raise ValueError(f"{path}: invalid OHLC rows={int(invalid.sum())}")
    return frame


@dataclass(frozen=True)
class FastView:
    index: pd.DatetimeIndex
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    segment_id: np.ndarray


def make_fast_view(frame: pd.DataFrame) -> FastView:
    idx = frame.index
    if len(idx):
        gap = idx.to_series().diff().ne(pd.Timedelta(minutes=1)).to_numpy()
        gap[0] = True
        segment_id = np.cumsum(gap).astype(np.int64)
    else:
        segment_id = np.array([], dtype=np.int64)
    return FastView(
        index=idx,
        open=frame.open.to_numpy(float),
        high=frame.high.to_numpy(float),
        low=frame.low.to_numpy(float),
        close=frame.close.to_numpy(float),
        segment_id=segment_id,
    )


def execute_event_fast(
    event: base.Event,
    candidate: m.DollarCandidate,
    equity: float,
    minute: dict[str, pd.DataFrame],
    views: dict[str, FastView],
    funding: dict[str, pd.DataFrame],
    cost: base.CostProfile,
    engine: base.EngineConfig,
) -> base.Trade | None:
    bars = minute[event.symbol]
    view = views[event.symbol]
    pos = int(view.index.searchsorted(event.entry_time, side="left"))
    if pos >= len(view.index):
        return None
    actual_entry_time = view.index[pos]
    if actual_entry_time - event.entry_time > pd.Timedelta(minutes=engine.max_entry_delay_minutes):
        return None
    raw_entry = float(view.open[pos])
    entry_exec = raw_entry * (1 + cost.slippage_rate * event.side)
    stop_trigger = (
        event.stop_reference - candidate.stop_buffer_atr * event.atr
        if event.side > 0
        else event.stop_reference + candidate.stop_buffer_atr * event.atr
    )
    if event.side > 0 and not (0 < stop_trigger < raw_entry):
        return None
    if event.side < 0 and not (stop_trigger > raw_entry > 0):
        return None
    stop_exec_nominal = stop_trigger * (1 - cost.slippage_rate * event.side)
    unit_loss = event.side * (entry_exec - stop_exec_nominal) + cost.fee_rate * (
        entry_exec + stop_exec_nominal
    )
    if not np.isfinite(unit_loss) or unit_loss <= 0:
        return None
    target_trigger = base.trigger_for_net_reward(
        entry_exec, unit_loss, event.side, candidate.reward_risk, cost
    )
    if event.side > 0 and target_trigger <= raw_entry:
        return None
    if event.side < 0 and target_trigger >= raw_entry:
        return None
    risk_cash = equity * engine.risk_fraction
    quantity = min(risk_cash / unit_loss, equity * engine.max_leverage / entry_exec)
    quantity = base.round_down(quantity, base.QTY_STEP[event.symbol])
    if quantity <= 0 or quantity * raw_entry < base.MIN_NOTIONAL[event.symbol]:
        return None
    leverage = quantity * raw_entry / equity

    scheduled = actual_entry_time + pd.Timedelta(minutes=candidate.maximum_holding_minutes)
    raw_horizon_pos = int(view.index.searchsorted(scheduled, side="left"))
    end_pos = min(raw_horizon_pos, len(view.index) - 1)
    if end_pos < pos:
        return None
    # Preserve the original fail-closed rule: any gap anywhere in the full planned path invalidates the event.
    if view.segment_id[pos] != view.segment_id[end_pos]:
        return None

    op = view.open[pos : end_pos + 1]
    hi = view.high[pos : end_pos + 1]
    lo = view.low[pos : end_pos + 1]
    if event.side > 0:
        gap_hit = op <= stop_trigger
        stop_hit = lo <= stop_trigger
        target_hit = hi >= target_trigger
    else:
        gap_hit = op >= stop_trigger
        stop_hit = hi >= stop_trigger
        target_hit = lo <= target_trigger
    any_hit = gap_hit | stop_hit | target_hit
    hit_idx = np.flatnonzero(any_hit)

    if len(hit_idx):
        rel = int(hit_idx[0])
        absolute = pos + rel
        exit_time = view.index[absolute]
        if bool(gap_hit[rel]):
            exit_raw = float(op[rel])
            reason = "gap_stop"
        elif bool(stop_hit[rel]):
            exit_raw = float(stop_trigger)
            reason = "stop"
        else:
            exit_raw = float(target_trigger)
            reason = "target"
    else:
        if raw_horizon_pos >= len(view.index):
            return None
        if view.index[raw_horizon_pos] - scheduled > pd.Timedelta(
            minutes=engine.max_entry_delay_minutes
        ):
            return None
        exit_time = view.index[raw_horizon_pos]
        exit_raw = float(view.open[raw_horizon_pos])
        reason = "horizon"

    exit_exec = exit_raw * (1 - cost.slippage_rate * event.side)
    gross = event.side * quantity * (exit_exec - entry_exec)
    fees = quantity * cost.fee_rate * (entry_exec + exit_exec)
    funding_pnl = base.funding_for_trade(
        event.symbol, event.side, quantity, actual_entry_time, exit_time, funding, minute
    )
    net = gross - fees + funding_pnl
    planned_risk = quantity * unit_loss
    r_multiple = net / planned_risk if planned_risk > 0 else np.nan
    return base.Trade(
        candidate_id=candidate.candidate_id,
        cost_profile=cost.name,
        symbol=event.symbol,
        side=event.side,
        signal_time=event.decision_time,
        entry_time=actual_entry_time,
        exit_time=exit_time,
        entry_price=entry_exec,
        stop_trigger=stop_trigger,
        target_trigger=target_trigger,
        exit_price=exit_exec,
        quantity=quantity,
        equity_before=equity,
        net_pnl=net,
        funding_pnl=funding_pnl,
        fees=fees,
        r_multiple=r_multiple,
        exit_reason=reason,
        bars_held=int((exit_time - actual_entry_time) / pd.Timedelta(minutes=1)),
        leverage=leverage,
        signal_score=event.score,
    )


def fast_simulate(
    events: list[base.Event],
    candidate: m.DollarCandidate,
    minute: dict[str, pd.DataFrame],
    views: dict[str, FastView],
    funding: dict[str, pd.DataFrame],
    cost: base.CostProfile,
    start: pd.Timestamp,
    end: pd.Timestamp,
    engine: base.EngineConfig,
) -> tuple[pd.DataFrame, pd.Series]:
    filtered = [event for event in events if start <= event.entry_time < end]
    equity = engine.initial_equity
    free_time = start
    trades: list[base.Trade] = []
    i = 0
    while i < len(filtered):
        timestamp = filtered[i].entry_time
        group: list[base.Event] = []
        while i < len(filtered) and filtered[i].entry_time == timestamp:
            group.append(filtered[i])
            i += 1
        if timestamp < free_time:
            continue
        selected = max(
            group, key=lambda event: (event.score, -base.SYMBOLS.index(event.symbol))
        )
        trade = execute_event_fast(
            selected, candidate, equity, minute, views, funding, cost, engine
        )
        if trade is None:
            continue
        equity += trade.net_pnl
        trades.append(trade)
        if equity <= 0:
            break
        free_time = trade.exit_time + pd.Timedelta(minutes=1)
    frame = pd.DataFrame([dataclasses.asdict(trade) for trade in trades])
    daily_index = pd.date_range(
        start.floor("D"), end.ceil("D"), freq="1D", inclusive="left", tz="UTC"
    )
    daily = pd.Series(engine.initial_equity, index=daily_index, dtype=float)
    if not frame.empty:
        frame["exit_time"] = pd.to_datetime(frame.exit_time, utc=True)
        cumulative = engine.initial_equity + frame.set_index("exit_time").net_pnl.cumsum()
        union = daily.index.union(cumulative.index).sort_values()
        series = cumulative.reindex(union).ffill().fillna(engine.initial_equity)
        daily = series.reindex(daily.index, method="ffill").fillna(engine.initial_equity)
    return frame, daily


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    paths = {
        "BTCUSDT": args.data_root / "btc_eth/BTCUSDT_preholdout.parquet",
        "ETHUSDT": args.data_root / "btc_eth/ETHUSDT_preholdout.parquet",
        "SOLUSDT": args.data_root / "sol_xrp_flow/SOLUSDT_official_preholdout.parquet",
        "XRPUSDT": args.data_root / "sol_xrp_flow/XRPUSDT_official_preholdout.parquet",
    }
    fpaths = {
        "BTCUSDT": args.data_root / "btc_eth/BTCUSDT_funding_preholdout.parquet",
        "ETHUSDT": args.data_root / "btc_eth/ETHUSDT_funding_preholdout.parquet",
        "SOLUSDT": args.data_root / "sol_xrp_funding/SOLUSDT_funding_preholdout.parquet",
        "XRPUSDT": args.data_root / "sol_xrp_funding/XRPUSDT_funding_preholdout.parquet",
    }

    candidates = m.candidate_grid()
    candidates_by_bpd: dict[int, list[m.DollarCandidate]] = {}
    for c in candidates:
        candidates_by_bpd.setdefault(c.target_bars_per_day, []).append(c)

    # Build the causal event set one clock at a time, then discard feature frames.
    event_cache: dict[str, list[base.Event]] = {}
    for bpd in m.TARGET_BARS:
        features: dict[str, pd.DataFrame] = {}
        for symbol in base.SYMBOLS:
            cache = args.output / f"bars_{symbol}_{bpd}.parquet"
            if not cache.exists():
                raise FileNotFoundError(f"required clock cache missing: {cache}")
            bars = pd.read_parquet(cache)
            if not isinstance(bars.index, pd.DatetimeIndex):
                bars.index = pd.to_datetime(bars.index, utc=True)
            features[symbol] = m.prepare_clock_features(bars, bpd)
        representatives: dict[str, m.DollarCandidate] = {}
        for c in candidates_by_bpd[bpd]:
            representatives.setdefault(c.signal_key, c)
        for n, (signal_key, c) in enumerate(representatives.items(), 1):
            events: list[base.Event] = []
            for symbol in base.SYMBOLS:
                events.extend(
                    m.generate_events(
                        features[symbol],
                        c,
                        symbol,
                        m.DEVELOPMENT_START,
                        m.CONFIRMATION_END,
                    )
                )
            event_cache[signal_key] = sorted(events, key=lambda e: (e.entry_time, -e.score, e.symbol))
            if n % 12 == 0:
                print(f"events bpd={bpd} {n}/{len(representatives)}", flush=True)
        del features
        gc.collect()
        print(f"events ready {bpd}", flush=True)

    # Execution path needs only OHLC, materially lowering memory versus full feature input.
    minute = {symbol: load_execution_minute(path) for symbol, path in paths.items()}
    views = {symbol: make_fast_view(frame) for symbol, frame in minute.items()}
    funding = {symbol: base.load_funding(path) for symbol, path in fpaths.items()}
    engine = base.EngineConfig()
    periods = {
        "dev_2022": (m.DEVELOPMENT_START, pd.Timestamp("2023-01-01T00:00:00Z")),
        "dev_2023": (pd.Timestamp("2023-01-01T00:00:00Z"), m.DEVELOPMENT_END),
    }

    rows: list[dict] = []
    for n, c in enumerate(candidates, 1):
        events = [dataclasses.replace(e, candidate_id=c.candidate_id) for e in event_cache[c.signal_key]]
        for pname, (start, end) in periods.items():
            for cost in base.COST_PROFILES:
                trades, daily = fast_simulate(events, c, minute, views, funding, cost, start, end, engine)
                rows.append(
                    {
                        "candidate_id": c.candidate_id,
                        "family": c.family,
                        "target_bars_per_day": c.target_bars_per_day,
                        "period": pname,
                        "cost_profile": cost.name,
                        **base.metrics(trades, daily, engine.initial_equity),
                    }
                )
        if n % 12 == 0:
            pd.DataFrame(rows).to_parquet(args.output / "development_screen_checkpoint.parquet", index=False)
            print(f"development {n}/{len(candidates)}", flush=True)

    screen = pd.DataFrame(rows)
    screen.to_parquet(args.output / "development_screen.parquet", index=False)
    ranking = m.dev_gate(screen)
    ranking.to_csv(args.output / "development_ranking.csv", index=False)
    survivors = ranking.loc[ranking.eligible_development].head(12)
    cmap = {c.candidate_id: c for c in candidates}

    selection_rows: list[dict] = []
    selection_logs: list[pd.DataFrame] = []
    for cid in survivors.candidate_id:
        c = cmap[cid]
        events = [dataclasses.replace(e, candidate_id=cid) for e in event_cache[c.signal_key]]
        for cost in base.COST_PROFILES:
            trades, daily = fast_simulate(
                events, c, minute, views, funding, cost, m.SELECTION_START, m.SELECTION_END, engine
            )
            selection_rows.append(
                {"candidate_id": cid, "period": "oos_2024", "cost_profile": cost.name,
                 **base.metrics(trades, daily, engine.initial_equity)}
            )
            if len(trades):
                copy = trades.copy()
                copy["period"] = "oos_2024"
                copy["cost_profile"] = cost.name
                selection_logs.append(copy)
    selection = pd.DataFrame(selection_rows)
    selection.to_csv(args.output / "selection_2024.csv", index=False)

    selection_pass: list[str] = []
    if len(selection):
        for cid, group in selection.groupby("candidate_id"):
            if m.single_period_gate(group, "oos_2024"):
                selection_pass.append(cid)

    confirmation_rows: list[dict] = []
    confirmation_logs: list[pd.DataFrame] = []
    for cid in selection_pass[:6]:
        c = cmap[cid]
        events = [dataclasses.replace(e, candidate_id=cid) for e in event_cache[c.signal_key]]
        for cost in base.COST_PROFILES:
            trades, daily = fast_simulate(
                events, c, minute, views, funding, cost, m.CONFIRMATION_START, m.CONFIRMATION_END, engine
            )
            confirmation_rows.append(
                {"candidate_id": cid, "period": "oos_2025H1", "cost_profile": cost.name,
                 **base.metrics(trades, daily, engine.initial_equity)}
            )
            if len(trades):
                copy = trades.copy()
                copy["period"] = "oos_2025H1"
                copy["cost_profile"] = cost.name
                confirmation_logs.append(copy)
    confirmation = pd.DataFrame(confirmation_rows)
    confirmation.to_csv(args.output / "confirmation_2025H1.csv", index=False)

    logs = selection_logs + confirmation_logs
    if logs:
        pd.concat(logs, ignore_index=True).to_parquet(args.output / "oos_trades.parquet", index=False)
    else:
        pd.DataFrame().to_parquet(args.output / "oos_trades.parquet")

    robust_rows: list[dict] = []
    for cid in selection_pass:
        cg = confirmation[confirmation.candidate_id == cid] if len(confirmation) else pd.DataFrame()
        ok = m.single_period_gate(cg, "oos_2025H1") if len(cg) else False
        sel2 = selection[(selection.candidate_id == cid) & (selection.cost_profile == "stress_2x")]
        con2 = cg[cg.cost_profile == "stress_2x"] if len(cg) else pd.DataFrame()
        min_g = min(
            float(sel2.geometric_daily.iloc[0]) if len(sel2) else -1.0,
            float(con2.geometric_daily.iloc[0]) if len(con2) else -1.0,
        )
        robust_rows.append(
            {"candidate_id": cid, "robust_oos": ok, "min_oos_2x_geometric_daily": min_g}
        )
    robust = pd.DataFrame(robust_rows)
    robust.to_csv(args.output / "robust_oos.csv", index=False)

    best = (
        robust.sort_values(
            ["robust_oos", "min_oos_2x_geometric_daily"], ascending=[False, False]
        ).iloc[0].to_dict()
        if len(robust)
        else None
    )
    target = bool(
        best and best["robust_oos"] and best["min_oos_2x_geometric_daily"] >= 0.01
    )
    summary = {
        "status": "COMPLETE",
        "study_id": "DOLLAR_BAR_ABSORPTION_V2",
        "candidate_count": len(candidates),
        "development_survivors": int(ranking.eligible_development.sum()),
        "selection_candidates": len(survivors),
        "selection_survivors": len(selection_pass),
        "confirmation_candidates": min(len(selection_pass), 6),
        "robust_oos_count": int(robust.robust_oos.sum()) if len(robust) else 0,
        "best": best,
        "target_passed": target,
        "champion_eligible": target,
        "terminal_holdout_opened": False,
        "orders_submitted": False,
        "implementation": "memory_bounded_clock_then_vectorized_exact_execution",
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
