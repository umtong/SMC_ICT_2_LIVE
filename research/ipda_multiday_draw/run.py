from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

DAY_MS = 86_400_000
MINUTE_MS = 60_000
FIVE_MS = 300_000
START_MS = int(pd.Timestamp("2021-01-01", tz="UTC").value // 1_000_000)
END_MS = int(pd.Timestamp("2024-01-01", tz="UTC").value // 1_000_000)
COST_SIDE = 0.0012  # 12 bp per side; 24 bp round trip near a flat price.


def profit_factor(values: Iterable[float]) -> float:
    x = np.asarray(list(values), dtype=float)
    x = x[np.isfinite(x)]
    positive = x[x > 0].sum()
    negative = -x[x < 0].sum()
    return float(positive / negative) if negative > 0 else float("nan")


def load_table(root: Path, symbol: str, name: str) -> pd.DataFrame:
    path = root / symbol / f"{name}.pkl.gz"
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_pickle(path)


def causal_pivots(frame: pd.DataFrame, left: int = 2, right: int = 2) -> tuple[np.ndarray, np.ndarray]:
    high = frame.high.to_numpy(float)
    low = frame.low.to_numpy(float)
    detected_high = np.full(len(frame), np.nan)
    detected_low = np.full(len(frame), np.nan)
    for origin in range(left, len(frame) - right):
        detect = origin + right
        if high[origin] >= np.nanmax(high[origin - left : origin + right + 1]):
            detected_high[detect] = high[origin]
        if low[origin] <= np.nanmin(low[origin - left : origin + right + 1]):
            detected_low[detect] = low[origin]
    return (
        pd.Series(detected_high).ffill().to_numpy(),
        pd.Series(detected_low).ffill().to_numpy(),
    )


def prepare_five(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame[frame.is_complete & frame.open.notna()].copy().reset_index(drop=True)
    prior_close = out.close.shift(1)
    true_range = pd.concat(
        [(out.high - out.low), (out.high - prior_close).abs(), (out.low - prior_close).abs()], axis=1
    ).max(axis=1)
    out["atr"] = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["body"] = out.close - out.open
    out["body_atr"] = out.body.abs() / out.atr
    out["range_atr"] = (out.high - out.low) / out.atr
    out["close_loc"] = (out.close - out.low) / (out.high - out.low).replace(0, np.nan)
    out["internal_high"] = out.high.shift(1).rolling(12, min_periods=12).max()
    out["internal_low"] = out.low.shift(1).rolling(12, min_periods=12).min()
    out["prior_close"] = out.close.shift(1)
    pivot_high, pivot_low = causal_pivots(out)
    out["last_pivot_high"] = pivot_high
    out["last_pivot_low"] = pivot_low
    out["day_start_ms"] = (out.start_time_ms // DAY_MS) * DAY_MS
    return out


def prepare_daily(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame[frame.is_complete & frame.open.notna()].copy().reset_index(drop=True)
    for column in ("open", "high", "low", "close"):
        out[f"prev_{column}"] = out[column].shift(1)
    out["prev_range"] = out.prev_high - out.prev_low
    out["prev_close_loc"] = (out.prev_close - out.prev_low) / out.prev_range.replace(0, np.nan)
    for horizon in (20, 40, 60):
        out[f"high{horizon}"] = out.high.shift(1).rolling(horizon, min_periods=horizon).max()
        out[f"low{horizon}"] = out.low.shift(1).rolling(horizon, min_periods=horizon).min()
        out[f"old_high{horizon}"] = out.high.shift(2).rolling(horizon, min_periods=horizon).max()
        out[f"old_low{horizon}"] = out.low.shift(2).rolling(horizon, min_periods=horizon).min()
        out[f"pos{horizon}"] = (out.prev_close - out[f"low{horizon}"]) / (
            out[f"high{horizon}"] - out[f"low{horizon}"]
        )
    return out[(out.start_time_ms >= START_MS) & (out.start_time_ms < END_MS)].copy()


def build_day_states(symbol: str, daily: pd.DataFrame) -> pd.DataFrame:
    records: list[dict] = []
    for row in daily.itertuples(index=False):
        day = int(row.start_time_ms)
        positions = [getattr(row, f"pos{x}") for x in (20, 40, 60)]
        if all(np.isfinite(positions)):
            if min(positions) >= 0.58:
                records.append(
                    dict(symbol=symbol, day_start_ms=day, family="nested_position", horizon=20,
                         direction=1, target=float(row.high20), source_boundary=np.nan,
                         state_strength=float(min(positions)), prior_close=float(row.prev_close),
                         range_low=float(row.low20), range_high=float(row.high20))
                )
            elif max(positions) <= 0.42:
                records.append(
                    dict(symbol=symbol, day_start_ms=day, family="nested_position", horizon=20,
                         direction=-1, target=float(row.low20), source_boundary=np.nan,
                         state_strength=float(1 - max(positions)), prior_close=float(row.prev_close),
                         range_low=float(row.low20), range_high=float(row.high20))
                )

        for shorter, longer in ((20, 40), (40, 60)):
            old_high = getattr(row, f"old_high{shorter}")
            old_low = getattr(row, f"old_low{shorter}")
            next_high = getattr(row, f"old_high{longer}")
            next_low = getattr(row, f"old_low{longer}")
            prior_close = float(row.prev_close)
            if not all(np.isfinite([old_high, old_low, next_high, next_low, prior_close])):
                continue
            width = max(old_high - old_low, 1e-12)
            if prior_close > old_high and next_high > prior_close:
                records.append(
                    dict(symbol=symbol, day_start_ms=day, family="accepted_expansion", horizon=longer,
                         direction=1, target=float(next_high), source_boundary=float(old_high),
                         state_strength=float((prior_close - old_high) / width), prior_close=prior_close,
                         range_low=float(old_low), range_high=float(next_high))
                )
            if prior_close < old_low and next_low < prior_close:
                records.append(
                    dict(symbol=symbol, day_start_ms=day, family="accepted_expansion", horizon=longer,
                         direction=-1, target=float(next_low), source_boundary=float(old_low),
                         state_strength=float((old_low - prior_close) / width), prior_close=prior_close,
                         range_low=float(next_low), range_high=float(old_high))
                )

        for horizon in (20, 40):
            old_high = getattr(row, f"old_high{horizon}")
            old_low = getattr(row, f"old_low{horizon}")
            if not all(np.isfinite([old_high, old_low, row.prev_high, row.prev_low, row.prev_close])):
                continue
            width = max(old_high - old_low, 1e-12)
            bull = (
                row.prev_low < old_low and row.prev_close > old_low and row.prev_close_loc >= 0.55
                and not row.prev_high > old_high
            )
            bear = (
                row.prev_high > old_high and row.prev_close < old_high and row.prev_close_loc <= 0.45
                and not row.prev_low < old_low
            )
            if bull:
                records.append(
                    dict(symbol=symbol, day_start_ms=day, family="opposite_after_reclaim", horizon=horizon,
                         direction=1, target=float(old_high), source_boundary=float(old_low),
                         state_strength=float((old_low - row.prev_low) / width), prior_close=float(row.prev_close),
                         range_low=float(old_low), range_high=float(old_high))
                )
            if bear:
                records.append(
                    dict(symbol=symbol, day_start_ms=day, family="opposite_after_reclaim", horizon=horizon,
                         direction=-1, target=float(old_low), source_boundary=float(old_high),
                         state_strength=float((row.prev_high - old_high) / width), prior_close=float(row.prev_close),
                         range_low=float(old_low), range_high=float(old_high))
                )
    return pd.DataFrame(records)


def displacement(row: object, direction: int) -> bool:
    if direction > 0:
        crossed = float(row.close) > float(row.internal_high) and float(row.prior_close) <= float(row.internal_high)
        location = float(row.close_loc) >= 0.68
    else:
        crossed = float(row.close) < float(row.internal_low) and float(row.prior_close) >= float(row.internal_low)
        location = float(row.close_loc) <= 0.32
    return bool(
        crossed and float(row.body) * direction > 0 and location
        and float(row.body_atr) >= 0.55 and float(row.range_atr) >= 0.75
    )


def build_signals(states: pd.DataFrame, five: pd.DataFrame, boundary_retest: bool) -> pd.DataFrame:
    groups = {int(day): group.reset_index(drop=True) for day, group in five.groupby("day_start_ms", sort=False)}
    records: list[dict] = []
    selected = states[states.family == "accepted_expansion"] if boundary_retest else states
    for state in selected.itertuples(index=False):
        group = groups.get(int(state.day_start_ms))
        if group is None or group.empty:
            continue
        direction = int(state.direction)
        target = float(state.target)
        touch_index: int | None = None
        for index, row in enumerate(group.itertuples(index=False)):
            if not np.isfinite(row.atr):
                continue
            if (direction > 0 and row.high >= target) or (direction < 0 and row.low <= target):
                break
            if boundary_retest:
                boundary = float(state.source_boundary)
                touched = row.low <= boundary and row.close > boundary if direction > 0 else row.high >= boundary and row.close < boundary
                if touch_index is None and touched:
                    touch_index = index
                if touch_index is None:
                    continue
                accepted = row.close > boundary if direction > 0 else row.close < boundary
                if not accepted:
                    continue
            if not displacement(row, direction):
                continue

            if boundary_retest:
                segment = group.iloc[touch_index : index + 1]
                stop_anchor = float(segment.low.min()) if direction > 0 else float(segment.high.max())
                family = "accepted_boundary_retest"
            else:
                pivot = float(row.last_pivot_low if direction > 0 else row.last_pivot_high)
                internal = float(row.internal_low if direction > 0 else row.internal_high)
                stop_anchor = pivot if np.isfinite(pivot) and (float(row.close) - pivot) * direction > 0 else internal
                family = str(state.family)
            stop = stop_anchor - direction * 0.05 * float(row.atr)
            risk = (float(row.close) - stop) * direction
            reward = (target - float(row.close)) * direction
            if risk <= 0 or reward <= 0:
                continue
            records.append(
                dict(symbol=state.symbol, day_start_ms=int(state.day_start_ms), family=family,
                     horizon=int(state.horizon), direction=direction, target=target,
                     source_boundary=float(state.source_boundary), state_strength=float(state.state_strength),
                     decision_time_ms=int(row.available_at_ms), signal_start_ms=int(row.start_time_ms),
                     signal_close=float(row.close), stop=stop, atr=float(row.atr),
                     body_atr=float(row.body_atr), range_atr=float(row.range_atr), close_loc=float(row.close_loc),
                     rr_at_signal=reward / risk, prior_close=float(state.prior_close),
                     range_low=float(state.range_low), range_high=float(state.range_high))
            )
            break
    return pd.DataFrame(records)


def simulate_one(event: object, minute: pd.DataFrame, end_ms: int) -> dict:
    starts = minute.start_time_ms.to_numpy(np.int64)
    opens = minute.open.to_numpy(float)
    highs = minute.high.to_numpy(float)
    lows = minute.low.to_numpy(float)
    closes = minute.close.to_numpy(float)
    direction = int(event.direction)
    stop = float(event.stop)
    target = float(event.target)
    active = int(event.decision_time_ms) + 500
    entry_index = int(np.searchsorted(starts, active, side="left"))
    base = event._asdict()
    base.update(filled=False, resolved=True, outcome=0, entry_time_ms=np.nan, exit_time_ms=np.nan,
                entry_price=np.nan, exit_price=np.nan, net_r=np.nan, risk_unit=np.nan)
    if entry_index >= len(starts) or starts[entry_index] >= end_ms:
        return base

    prior = entry_index - 1
    if prior >= 0 and starts[prior] >= int(event.decision_time_ms):
        invalid = lows[prior] <= stop if direction > 0 else highs[prior] >= stop
        delivered = highs[prior] >= target if direction > 0 else lows[prior] <= target
        if invalid or delivered:
            return base

    entry = float(opens[entry_index])
    if (direction > 0 and (entry <= stop or entry >= target)) or (direction < 0 and (entry >= stop or entry <= target)):
        return base
    quote_risk = (entry - stop) * direction
    expected_loss = quote_risk + (entry + stop) * COST_SIDE
    reward = (target - entry) * direction
    if quote_risk <= 0 or reward <= 0 or reward / expected_loss < 1.25:
        return base

    stop_hits = np.flatnonzero(lows[entry_index:] <= stop) if direction > 0 else np.flatnonzero(highs[entry_index:] >= stop)
    target_hits = np.flatnonzero(highs[entry_index:] >= target) if direction > 0 else np.flatnonzero(lows[entry_index:] <= target)
    stop_index = entry_index + int(stop_hits[0]) if len(stop_hits) else len(starts)
    target_index = entry_index + int(target_hits[0]) if len(target_hits) else len(starts)
    exit_index = min(stop_index, target_index)
    resolved = exit_index < len(starts) and starts[exit_index] < end_ms
    if resolved and stop_index <= target_index:
        outcome = -1
        exit_price = stop
    elif resolved:
        outcome = 1
        exit_price = target
    else:
        outcome = 0
        exit_index = min(len(starts) - 1, int(np.searchsorted(starts, end_ms, side="left")) - 1)
        exit_price = float(closes[exit_index])

    gross = (exit_price - entry) * direction
    net = gross - (entry + exit_price) * COST_SIDE
    base.update(
        filled=True, resolved=bool(resolved), outcome=outcome,
        entry_time_ms=int(starts[entry_index]), exit_time_ms=int(starts[exit_index] + MINUTE_MS),
        entry_price=entry, exit_price=exit_price, net_r=net / expected_loss, risk_unit=expected_loss,
    )
    return base


def simulate(symbol: str, signals: pd.DataFrame, minute: pd.DataFrame) -> pd.DataFrame:
    selected = signals[signals.symbol == symbol].sort_values("decision_time_ms")
    return pd.DataFrame([simulate_one(row, minute, END_MS) for row in selected.itertuples(index=False)])


def route_account(events: pd.DataFrame, policy: str) -> dict:
    chosen = events[(events.filled == True) & events.net_r.notna()].sort_values(["decision_time_ms", "symbol"])  # noqa: E712
    nav = 10_000.0
    slot_free = START_MS
    trades: list[dict] = []
    skips = 0
    for row in chosen.itertuples(index=False):
        if int(row.decision_time_ms) < slot_free:
            skips += 1
            continue
        quantity = min(nav * 0.005 / float(row.risk_unit), nav * 3.0 / float(row.entry_price))
        pnl = quantity * float(row.net_r) * float(row.risk_unit)
        before = nav
        nav += pnl
        trades.append(
            dict(policy=policy, symbol=row.symbol, direction=int(row.direction), family=row.family,
                 horizon=int(row.horizon), decision_time_ms=int(row.decision_time_ms),
                 entry_time_ms=int(row.entry_time_ms), exit_time_ms=int(row.exit_time_ms),
                 entry_price=float(row.entry_price), exit_price=float(row.exit_price), quantity=quantity,
                 net_r=float(row.net_r), net_pnl=pnl, nav_before=before, nav_after=nav)
        )
        slot_free = int(row.exit_time_ms)
    pnl = np.asarray([x["net_pnl"] for x in trades], dtype=float)
    multiple = nav / 10_000.0
    growth = multiple ** (1 / 1095) - 1 if nav > 0 else -1.0
    positive = np.maximum(pnl, 0)
    top_share = float(np.sort(positive)[-5:].sum() / positive.sum()) if positive.sum() > 0 else float("nan")
    return dict(policy=policy, final_nav=nav, account_multiple=multiple, geometric_daily_growth=growth,
                trades=len(trades), skips=skips, win_rate=float(np.mean(pnl > 0)) if len(pnl) else float("nan"),
                profit_factor=profit_factor(pnl), top5_positive_share=top_share)


def summarize_events(events: pd.DataFrame) -> pd.DataFrame:
    out = events[events.filled == True].copy()  # noqa: E712
    out["year"] = pd.to_datetime(out.decision_time_ms, unit="ms", utc=True).dt.year
    out["variant"] = out.family + "_" + out.horizon.astype(int).astype(str)
    records: list[dict] = []
    for (year, variant), group in out.groupby(["year", "variant"]):
        net = group.net_r.dropna()
        positive = net.clip(lower=0)
        records.append(
            dict(year=int(year), variant=variant, candidates=len(group), resolved=int(group.resolved.sum()),
                 mean_r=float(net.mean()), median_r=float(net.median()),
                 win_rate=float((group.loc[net.index, "outcome"] == 1).mean()),
                 profit_factor=profit_factor(net),
                 top5_share=float(positive.nlargest(5).sum() / positive.sum()) if positive.sum() > 0 else np.nan)
        )
    return pd.DataFrame(records).sort_values(["variant", "year"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    all_signals: list[pd.DataFrame] = []
    minute_by_symbol: dict[str, pd.DataFrame] = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        daily = prepare_daily(load_table(args.root, symbol, "bars_1d"))
        five = prepare_five(load_table(args.root, symbol, "bars_5m"))
        five = five[(five.start_time_ms >= START_MS) & (five.start_time_ms < END_MS)]
        states = build_day_states(symbol, daily)
        regular = build_signals(states, five, boundary_retest=False)
        retest = build_signals(states, five, boundary_retest=True)
        all_signals.extend([regular, retest])
        minute = load_table(args.root, symbol, "bars_1m")
        minute_by_symbol[symbol] = minute[
            (minute.start_time_ms >= START_MS) & (minute.start_time_ms < END_MS) & minute.observed
        ].reset_index(drop=True)

    signals = pd.concat(all_signals, ignore_index=True).sort_values("decision_time_ms")
    simulated = pd.concat(
        [simulate(symbol, signals, minute_by_symbol[symbol]) for symbol in ("BTCUSDT", "ETHUSDT")],
        ignore_index=True,
    ).sort_values("decision_time_ms")
    simulated.to_pickle(args.out / "events.pkl.gz", compression="gzip")
    summarize_events(simulated).to_csv(args.out / "event_economics.csv", index=False)

    account_rows: list[dict] = []
    policies = [
        ("nested_position", 20),
        ("accepted_expansion", 40),
        ("accepted_expansion", 60),
        ("opposite_after_reclaim", 20),
        ("opposite_after_reclaim", 40),
        ("accepted_boundary_retest", 40),
        ("accepted_boundary_retest", 60),
    ]
    for family, horizon in policies:
        subset = simulated[(simulated.family == family) & (simulated.horizon == horizon)]
        account_rows.append(route_account(subset, f"{family}_{horizon}"))
    accounts = pd.DataFrame(account_rows).sort_values("geometric_daily_growth", ascending=False)
    accounts.to_csv(args.out / "account_summary.csv", index=False)
    print(accounts.to_string(index=False))


if __name__ == "__main__":
    main()
