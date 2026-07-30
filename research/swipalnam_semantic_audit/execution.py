from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

try:
    from .audit import DAY_MS, enrich_15m
except ImportError:
    from audit import DAY_MS, enrich_15m


def next_session_refresh_ms(decision_ms: int) -> int:
    ts = pd.Timestamp(decision_ms, unit="ms", tz="UTC")
    day = ts.floor("D")
    bounds = [day + pd.Timedelta(hours=h) for h in (7, 13, 21, 24, 31, 37, 45, 48)]
    future = [int(x.value // 1_000_000) for x in bounds if int(x.value // 1_000_000) > decision_ms]
    return future[1] if len(future) >= 2 else decision_ms + 24 * DAY_MS


def simulate_one(cand, minute: pd.DataFrame, setup: pd.DataFrame, hard_end_ms: int) -> dict:
    direction = int(cand.direction)
    decision = int(cand.decision_time_ms)
    active = decision + 500
    limit = (float(cand.zone_low) + float(cand.zone_high)) / 2
    stop = float(cand.stop_anchor) - direction * 0.1 * float(cand.atr)
    target = float(cand.target_price)
    starts = minute.start_time_ms.to_numpy(np.int64)
    available = minute.available_at_ms.to_numpy(np.int64)
    opens = minute.open.to_numpy(float)
    highs = minute.high.to_numpy(float)
    lows = minute.low.to_numpy(float)
    closes = minute.close.to_numpy(float)
    setup_times = setup.available_at_ms.to_numpy(np.int64)

    expiry = min(next_session_refresh_ms(decision), hard_end_ms)
    setup_start = int(np.searchsorted(setup_times, decision, side="right"))
    setup_end = int(np.searchsorted(setup_times, expiry, side="left"))
    for j in range(setup_start, setup_end):
        state = setup.iloc[j]
        opposite = (
            float(state.close) < float(state.internal_low)
            and float(state.body_signed) < 0
            and float(state.body_atr) >= 0.65
            if direction > 0
            else float(state.close) > float(state.internal_high)
            and float(state.body_signed) > 0
            and float(state.body_atr) >= 0.65
        )
        if float(state.range_atr) >= 0.9 and opposite:
            expiry = min(int(state.available_at_ms) + 500, hard_end_ms)
            break

    begin = int(np.searchsorted(starts, active, side="left"))
    pending_end = int(np.searchsorted(starts, expiry, side="left"))
    hard_end = int(np.searchsorted(starts, hard_end_ms, side="left"))
    base = {
        "candidate_id": cand.candidate_id,
        "symbol": cand.symbol,
        "direction": direction,
        "decision_time_ms": decision,
        "order_end_time_ms": expiry,
        "filled": False,
        "resolved": True,
        "entry_time_ms": np.nan,
        "exit_time_ms": np.nan,
        "entry_price": np.nan,
        "exit_price": np.nan,
        "stop_price": stop,
        "target_price": target,
        "gross_pnl_per_unit": 0.0,
        "net_r_13bp": np.nan,
        "net_r_24bp": np.nan,
        "exit_reason": "unfilled",
    }
    if begin >= pending_end or (limit - stop) * direction <= 0 or (target - limit) * direction <= 0:
        return base

    fill_i = None
    for i in range(begin, pending_end):
        opening = opens[i]
        if opening <= stop if direction > 0 else opening >= stop:
            base["order_end_time_ms"] = int(starts[i])
            base["exit_reason"] = "gap_invalidated_before_fill"
            return base
        if opening >= target if direction > 0 else opening <= target:
            base["order_end_time_ms"] = int(starts[i])
            base["exit_reason"] = "gap_delivered_before_fill"
            return base
        if opening <= limit if direction > 0 else opening >= limit:
            fill_i = i
            break
        invalid = lows[i] <= stop if direction > 0 else highs[i] >= stop
        delivered = highs[i] >= target if direction > 0 else lows[i] <= target
        if invalid or delivered:
            base["order_end_time_ms"] = int(available[i])
            base["exit_reason"] = "invalidated_before_fill" if invalid else "target_before_fill"
            return base
        if lows[i] <= limit <= highs[i] and i + 1 < hard_end:
            fill_i = i + 1
            break
    if fill_i is None:
        base["exit_reason"] = "liquidity_context_refreshed"
        return base

    entry = float(opens[fill_i]) * (1 + direction / 10_000)
    risk = (entry - stop) * direction
    reward_risk = (target - entry) * direction / risk if risk > 0 else -1
    base["order_end_time_ms"] = int(starts[fill_i])
    if risk <= 0 or reward_risk < 1.25:
        base["exit_reason"] = "gap_or_rr_invalid"
        return base

    tp1 = entry + direction * min(risk, 0.45 * abs(target - entry))
    remaining = 1.0
    gross = 0.0
    tp1_hit = False
    current_stop = stop
    last_setup = int(np.searchsorted(setup_times, int(available[fill_i]), side="right") - 1)
    exit_time = None
    exit_price = None
    reason = "open_at_end"

    for i in range(fill_i, hard_end):
        stop_hit = lows[i] <= current_stop if direction > 0 else highs[i] >= current_stop
        target_hit = highs[i] >= target if direction > 0 else lows[i] <= target
        tp1_now = ((highs[i] >= tp1) if direction > 0 else (lows[i] <= tp1)) and not tp1_hit
        if stop_hit:
            exit_price = current_stop * (1 - direction / 10_000)
            exit_time = int(available[i])
            reason = "stop"
            gross += remaining * (exit_price - entry) * direction
            remaining = 0
            break
        if target_hit:
            if tp1_now:
                gross += 0.4 * (tp1 - entry) * direction
                remaining = 0.6
                tp1_hit = True
            exit_price = target * (1 - direction / 10_000)
            exit_time = int(available[i])
            reason = "opposing_liquidity"
            gross += remaining * (exit_price - entry) * direction
            remaining = 0
            break
        if tp1_now:
            gross += 0.4 * (tp1 - entry) * direction
            remaining = 0.6
            tp1_hit = True

        new_setup = int(np.searchsorted(setup_times, int(available[i]), side="right") - 1)
        if new_setup > last_setup:
            for position in range(last_setup + 1, new_setup + 1):
                state = setup.iloc[position]
                if tp1_hit and direction > 0 and bool(state.new_swing_low) and entry < float(state.last_swing_low) < float(state.close):
                    current_stop = max(current_stop, float(state.last_swing_low))
                if tp1_hit and direction < 0 and bool(state.new_swing_high) and float(state.close) < float(state.last_swing_high) < entry:
                    current_stop = min(current_stop, float(state.last_swing_high))
                reversal = (
                    float(state.close) < float(state.internal_low) and float(state.body_atr) >= 0.8
                    if direction > 0
                    else float(state.close) > float(state.internal_high) and float(state.body_atr) >= 0.8
                )
                if reversal:
                    executable = int(np.searchsorted(starts, int(state.available_at_ms) + 500, side="left"))
                    if executable <= i:
                        exit_price = float(closes[i]) * (1 - direction / 10_000)
                        exit_time = int(available[i])
                        reason = "opposite_mss"
                        gross += remaining * (exit_price - entry) * direction
                        remaining = 0
                        break
            last_setup = new_setup
            if remaining <= 0:
                break

    resolved = exit_time is not None
    if not resolved:
        i = hard_end - 1
        exit_time = int(available[i])
        exit_price = float(closes[i])
        gross += remaining * (exit_price - entry) * direction

    cost13 = entry * 6.5 / 10_000 + float(exit_price) * 6.5 / 10_000
    cost24 = entry * 12 / 10_000 + float(exit_price) * 12 / 10_000
    base.update(
        filled=True,
        resolved=resolved,
        entry_time_ms=int(starts[fill_i]),
        exit_time_ms=exit_time,
        entry_price=entry,
        exit_price=float(exit_price),
        gross_pnl_per_unit=gross,
        net_r_13bp=(gross - cost13) / risk,
        net_r_24bp=(gross - cost24) / risk,
        exit_reason=reason,
    )
    return base


def run_simulation(
    root: str,
    candidates_path: str,
    out: str,
    start: str = "2023-01-01",
    end: str = "2024-07-01",
) -> pd.DataFrame:
    candidates = pd.read_pickle(candidates_path)
    lower = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    upper = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    results = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        minute = pd.read_pickle(Path(root) / symbol / "bars_1m.pkl.gz")
        minute = minute[(minute.start_time_ms >= lower) & (minute.start_time_ms < upper) & minute.observed].reset_index(drop=True)
        setup_frame = pd.read_pickle(Path(root) / symbol / "bars_15m.pkl.gz")
        setup_frame = setup_frame[(setup_frame.start_time_ms >= lower) & (setup_frame.start_time_ms < upper)]
        setup = enrich_15m(setup_frame)
        selected = candidates[(candidates.symbol == symbol) & candidates.selected_config].sort_values("decision_time_ms")
        for row in selected.itertuples(index=False):
            results.append(simulate_one(row, minute, setup, upper))
    frame = pd.DataFrame(results)
    frame.to_pickle(out, compression="gzip")
    return frame
