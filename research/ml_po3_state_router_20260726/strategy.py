from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from data import BAR_MS


TICK_SIZE = {
    "BTCUSDT": 0.1,
    "ETHUSDT": 0.01,
    "SOLUSDT": 0.001,
    "XRPUSDT": 0.0001,
}


@dataclass(frozen=True)
class Thresholds:
    accumulation: float
    manipulation: float
    distribution: float
    accumulation_state: int
    manipulation_state: int
    distribution_state: int
    accumulation_run_bars: int = 6
    minimum_reward_risk: float = 1.5


def _dominant(row: pd.Series, state: int) -> bool:
    probabilities = np.asarray([row["p_state_0"], row["p_state_1"], row["p_state_2"]], dtype=np.float64)
    return int(np.argmax(probabilities)) == int(state)


def _event_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def generate_symbol_events(symbol: str, frame: pd.DataFrame, thresholds: Thresholds) -> list[dict[str, object]]:
    if symbol not in TICK_SIZE:
        raise ValueError(f"unknown tick size for {symbol}")
    required = {
        "open_time",
        "bar_end",
        "open",
        "high",
        "low",
        "close",
        "body_efficiency",
        "flow_imbalance",
        "p_state_0",
        "p_state_1",
        "p_state_2",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing event columns: {missing}")

    ordered = frame.sort_values("open_time").reset_index(drop=True)
    events: list[dict[str, object]] = []
    accumulation_run: list[int] = []
    box: dict[str, object] | None = None
    pending: dict[str, object] | None = None
    previous_time: int | None = None

    for index, row in ordered.iterrows():
        open_time = int(row["open_time"])
        if previous_time is not None and open_time - previous_time != BAR_MS:
            accumulation_run = []
            box = None
            pending = None
        previous_time = open_time

        is_accumulation = (
            float(row[f"p_state_{thresholds.accumulation_state}"]) >= thresholds.accumulation
            and _dominant(row, thresholds.accumulation_state)
        )
        if is_accumulation:
            accumulation_run.append(index)
            if len(accumulation_run) == thresholds.accumulation_run_bars:
                run = ordered.iloc[accumulation_run]
                box = {
                    "start_index": int(accumulation_run[0]),
                    "end_index": int(accumulation_run[-1]),
                    "high": float(run["high"].max()),
                    "low": float(run["low"].min()),
                    "available_index": int(index + 1),
                    "mean_accumulation_probability": float(
                        run[f"p_state_{thresholds.accumulation_state}"].mean()
                    ),
                }
                pending = None
            continue
        accumulation_run = []

        if box is None or index < int(box["available_index"]):
            continue

        box_high = float(box["high"])
        box_low = float(box["low"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        upper_outside = high > box_high
        lower_outside = low < box_low

        if pending is None:
            if upper_outside and lower_outside:
                box = None
                continue
            if upper_outside:
                if close >= box_high:
                    box = None
                    continue
                if (
                    float(row[f"p_state_{thresholds.manipulation_state}"]) >= thresholds.manipulation
                    and _dominant(row, thresholds.manipulation_state)
                ):
                    pending = {
                        "side": "upper",
                        "raid_index": int(index),
                        "raid_open": float(row["open"]),
                        "raid_extreme": high,
                        "raid_probability": float(row[f"p_state_{thresholds.manipulation_state}"]),
                    }
                continue
            if lower_outside:
                if close <= box_low:
                    box = None
                    continue
                if (
                    float(row[f"p_state_{thresholds.manipulation_state}"]) >= thresholds.manipulation
                    and _dominant(row, thresholds.manipulation_state)
                ):
                    pending = {
                        "side": "lower",
                        "raid_index": int(index),
                        "raid_open": float(row["open"]),
                        "raid_extreme": low,
                        "raid_probability": float(row[f"p_state_{thresholds.manipulation_state}"]),
                    }
                continue
            continue

        side = str(pending["side"])
        if side == "upper":
            if lower_outside or close >= box_high:
                box = None
                pending = None
                continue
            pending["raid_extreme"] = max(float(pending["raid_extreme"]), high)
            confirmed = (
                index > int(pending["raid_index"])
                and float(row[f"p_state_{thresholds.distribution_state}"]) >= thresholds.distribution
                and _dominant(row, thresholds.distribution_state)
                and close < float(pending["raid_open"])
                and float(row["body_efficiency"]) < 0.0
                and float(row["flow_imbalance"]) < 0.0
            )
            trade_side = -1
        else:
            if upper_outside or close <= box_low:
                box = None
                pending = None
                continue
            pending["raid_extreme"] = min(float(pending["raid_extreme"]), low)
            confirmed = (
                index > int(pending["raid_index"])
                and float(row[f"p_state_{thresholds.distribution_state}"]) >= thresholds.distribution
                and _dominant(row, thresholds.distribution_state)
                and close > float(pending["raid_open"])
                and float(row["body_efficiency"]) > 0.0
                and float(row["flow_imbalance"]) > 0.0
            )
            trade_side = 1

        if not confirmed:
            continue
        entry_index = index + 1
        if entry_index >= len(ordered):
            box = None
            pending = None
            continue
        entry_row = ordered.iloc[entry_index]
        if int(entry_row["open_time"]) - open_time != BAR_MS:
            box = None
            pending = None
            continue

        entry_price = float(entry_row["open"])
        tick = TICK_SIZE[symbol]
        if trade_side > 0:
            stop_price = float(pending["raid_extreme"]) - tick
            target_price = box_high
            risk_distance = entry_price - stop_price
            reward_distance = target_price - entry_price
        else:
            stop_price = float(pending["raid_extreme"]) + tick
            target_price = box_low
            risk_distance = stop_price - entry_price
            reward_distance = entry_price - target_price

        if risk_distance <= 0.0 or reward_distance <= 0.0:
            box = None
            pending = None
            continue
        reward_risk = reward_distance / risk_distance
        if reward_risk + 1e-12 < thresholds.minimum_reward_risk:
            box = None
            pending = None
            continue

        distribution_probability = float(row[f"p_state_{thresholds.distribution_state}"])
        raid_depth = (
            float(pending["raid_extreme"]) - box_high
            if side == "upper"
            else box_low - float(pending["raid_extreme"])
        )
        event = {
            "event_id": _event_id(symbol, int(entry_row["open_time"]), trade_side, int(box["start_index"]), side),
            "symbol": symbol,
            "side": int(trade_side),
            "box_start_time": int(ordered.iloc[int(box["start_index"])]["open_time"]),
            "box_end_time": int(ordered.iloc[int(box["end_index"])]["bar_end"]),
            "box_high": box_high,
            "box_low": box_low,
            "raid_side": side,
            "raid_time": int(ordered.iloc[int(pending["raid_index"])]["bar_end"]),
            "raid_extreme": float(pending["raid_extreme"]),
            "decision_time": int(row["bar_end"]),
            "entry_time": int(entry_row["open_time"]),
            "entry_index": int(entry_index),
            "entry_price": entry_price,
            "stop_price": float(stop_price),
            "target_price": float(target_price),
            "reward_risk": float(reward_risk),
            "distribution_probability": distribution_probability,
            "manipulation_probability": float(pending["raid_probability"]),
            "raid_depth_bps": float(raid_depth / entry_price * 10000.0),
            "score": float(distribution_probability * reward_risk),
        }
        events.append(event)
        box = None
        pending = None

    return events


def generate_events(frames: dict[str, pd.DataFrame], thresholds: Thresholds) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for symbol in sorted(frames):
        events.extend(generate_symbol_events(symbol, frames[symbol], thresholds))
    events.sort(key=lambda event: (int(event["entry_time"]), -float(event["score"]), str(event["symbol"]), str(event["event_id"])))
    return events


def _funding_for_trade(
    side: int,
    quantity: float,
    entry_time: int,
    exit_time: int,
    frame: pd.DataFrame,
    funding: pd.DataFrame,
) -> tuple[float, list[tuple[int, float]]]:
    if funding.empty or exit_time <= entry_time:
        return 0.0, []
    relevant = funding.loc[(funding["funding_time"] > entry_time) & (funding["funding_time"] <= exit_time)]
    if relevant.empty:
        return 0.0, []
    times = frame["open_time"].to_numpy(dtype=np.int64)
    closes = frame["close"].to_numpy(dtype=np.float64)
    total = 0.0
    cashflows: list[tuple[int, float]] = []
    for row in relevant.itertuples(index=False):
        timestamp = int(row.funding_time)
        index = int(np.searchsorted(times, timestamp, side="left") - 1)
        mark = closes[index] if index >= 0 else float(frame.iloc[0]["open"])
        cashflow = -float(side) * quantity * mark * float(row.funding_rate)
        total += cashflow
        cashflows.append((timestamp, float(cashflow)))
    return float(total), cashflows


def simulate_event(
    event: dict[str, object],
    frame: pd.DataFrame,
    funding: pd.DataFrame,
    nav_before: float,
    cost_bps: float,
    risk_fraction: float,
    notional_cap_multiple: float,
    participation_fraction: float,
) -> tuple[dict[str, object] | None, list[float]]:
    entry_index = int(event["entry_index"])
    if entry_index <= 0 or entry_index >= len(frame):
        return None, []
    entry_price = float(event["entry_price"])
    stop_price = float(event["stop_price"])
    target_price = float(event["target_price"])
    side = int(event["side"])
    stop_distance = abs(entry_price - stop_price)
    per_unit_planned_loss = stop_distance + entry_price * (float(cost_bps) + 2.0) / 10000.0
    if per_unit_planned_loss <= 0.0:
        return None, []

    risk_quantity = nav_before * float(risk_fraction) / per_unit_planned_loss
    leverage_quantity = nav_before * float(notional_cap_multiple) / entry_price
    prior_quote = float(frame.iloc[entry_index - 1]["quote_volume"])
    participation_quantity = max(0.0, prior_quote * float(participation_fraction) / entry_price)
    quantity = min(risk_quantity, leverage_quantity, participation_quantity)
    if not math.isfinite(quantity) or quantity <= 0.0:
        return None, []

    exit_index: int | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    unresolved = False
    for index in range(entry_index, len(frame)):
        row = frame.iloc[index]
        bar_open = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        if side > 0:
            if bar_open <= stop_price:
                exit_index, exit_price, exit_reason = index, bar_open, "gap_stop"
                break
            if bar_open >= target_price:
                exit_index, exit_price, exit_reason = index, target_price, "gap_target"
                break
            stop_hit = low <= stop_price
            target_hit = high >= target_price
        else:
            if bar_open >= stop_price:
                exit_index, exit_price, exit_reason = index, bar_open, "gap_stop"
                break
            if bar_open <= target_price:
                exit_index, exit_price, exit_reason = index, target_price, "gap_target"
                break
            stop_hit = high >= stop_price
            target_hit = low <= target_price
        if stop_hit:
            exit_index, exit_price, exit_reason = index, stop_price, "stop"
            break
        if target_hit:
            exit_index, exit_price, exit_reason = index, target_price, "target"
            break

    if exit_index is None or exit_price is None or exit_reason is None:
        exit_index = len(frame) - 1
        exit_price = stop_price
        exit_reason = "source_boundary_full_stop"
        unresolved = True

    entry_time = int(event["entry_time"])
    exit_time = int(frame.iloc[exit_index]["bar_end"])
    funding_pnl, funding_cashflows = _funding_for_trade(
        side, quantity, entry_time, exit_time, frame, funding
    )
    gross_pnl = float(side) * quantity * (exit_price - entry_price)
    average_notional = quantity * 0.5 * (entry_price + exit_price)
    trading_cost = average_notional * float(cost_bps) / 10000.0
    net_pnl = gross_pnl - trading_cost + funding_pnl
    nav_after = nav_before + net_pnl
    net_bps = net_pnl / max(quantity * entry_price, 1e-300) * 10000.0

    # Mark-to-market equity path for account drawdown. Half the frozen cost is
    # recognized on entry and half is reserved for a realistic liquidation.
    entry_cost = quantity * entry_price * float(cost_bps) / 20000.0
    equity_path: list[float] = []
    funding_cursor = 0
    accrued_funding = 0.0
    for index in range(entry_index, exit_index + 1):
        bar_end = int(frame.iloc[index]["bar_end"])
        while funding_cursor < len(funding_cashflows) and funding_cashflows[funding_cursor][0] <= bar_end:
            accrued_funding += funding_cashflows[funding_cursor][1]
            funding_cursor += 1
        mark = float(frame.iloc[index]["close"])
        projected_exit_cost = quantity * mark * float(cost_bps) / 20000.0
        equity = nav_before - entry_cost + float(side) * quantity * (mark - entry_price) + accrued_funding - projected_exit_cost
        equity_path.append(float(equity))
    equity_path.append(float(nav_after))

    trade = dict(event)
    trade.update(
        {
            "cost_bps": float(cost_bps),
            "quantity": float(quantity),
            "planned_risk_usdt": float(quantity * per_unit_planned_loss),
            "notional_usdt": float(quantity * entry_price),
            "exit_time": exit_time,
            "exit_price": float(exit_price),
            "exit_reason": exit_reason,
            "unresolved": bool(unresolved),
            "gross_pnl_usdt": gross_pnl,
            "trading_cost_usdt": float(trading_cost),
            "funding_pnl_usdt": funding_pnl,
            "net_pnl_usdt": float(net_pnl),
            "net_bps": float(net_bps),
            "nav_before": float(nav_before),
            "nav_after": float(nav_after),
            "account_return": float(net_pnl / nav_before),
        }
    )
    return trade, equity_path


def route_and_replay(
    events: Iterable[dict[str, object]],
    frames: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    stage_start_ms: int,
    stage_end_ms: int,
    cost_bps: float,
    excluded_event_ids: set[str] | None = None,
    initial_nav: float = 10000.0,
    risk_fraction: float = 0.01,
    notional_cap_multiple: float = 3.0,
    participation_fraction: float = 0.02,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    excluded = excluded_event_ids or set()
    ordered = [event for event in events if str(event["event_id"]) not in excluded]
    ordered.sort(key=lambda event: (int(event["entry_time"]), -float(event["score"]), str(event["symbol"]), str(event["event_id"])))
    nav = float(initial_nav)
    cursor_time = int(stage_start_ms - 1)
    pointer = 0
    trades: list[dict[str, object]] = []
    equity_points: list[float] = [nav]

    while pointer < len(ordered) and nav > 0.0:
        while pointer < len(ordered) and int(ordered[pointer]["entry_time"]) <= cursor_time:
            pointer += 1
        if pointer >= len(ordered):
            break
        timestamp = int(ordered[pointer]["entry_time"])
        end = pointer + 1
        while end < len(ordered) and int(ordered[end]["entry_time"]) == timestamp:
            end += 1
        group = ordered[pointer:end]
        selected = sorted(group, key=lambda event: (-float(event["score"]), str(event["symbol"]), str(event["event_id"])))[0]
        symbol = str(selected["symbol"])
        trade, path = simulate_event(
            selected,
            frames[symbol],
            funding.get(symbol, pd.DataFrame(columns=["funding_time", "funding_rate"])),
            nav,
            float(cost_bps),
            float(risk_fraction),
            float(notional_cap_multiple),
            float(participation_fraction),
        )
        pointer = end
        if trade is None:
            cursor_time = timestamp
            continue
        trades.append(trade)
        equity_points.extend(path)
        nav = float(trade["nav_after"])
        cursor_time = int(trade["exit_time"])

    metrics = summarize_trades(
        trades,
        equity_points,
        initial_nav=float(initial_nav),
        stage_start_ms=int(stage_start_ms),
        stage_end_ms=int(stage_end_ms),
    )
    metrics["cost_bps"] = float(cost_bps)
    metrics["excluded_event_count"] = int(len(excluded))
    return trades, metrics


def _period_return(trades: list[dict[str, object]], start_ms: int, end_ms: int) -> float:
    value = 1.0
    for trade in trades:
        exit_time = int(trade["exit_time"])
        if start_ms <= exit_time <= end_ms:
            value *= 1.0 + float(trade["account_return"])
    return float(value - 1.0)


def summarize_trades(
    trades: list[dict[str, object]],
    equity_points: list[float],
    initial_nav: float,
    stage_start_ms: int,
    stage_end_ms: int,
) -> dict[str, object]:
    final_nav = float(trades[-1]["nav_after"]) if trades else float(initial_nav)
    calendar_days = max(1, int((stage_end_ms - stage_start_ms + 1) // (24 * 60 * 60 * 1000)) + 1)
    if final_nav > 0.0:
        geometric_daily_growth = float((final_nav / initial_nav) ** (1.0 / calendar_days) - 1.0)
    else:
        geometric_daily_growth = -1.0

    equity = np.asarray(equity_points if equity_points else [initial_nav], dtype=np.float64)
    peaks = np.maximum.accumulate(equity)
    drawdowns = np.where(peaks > 0.0, 1.0 - equity / peaks, 1.0)
    maximum_drawdown = float(np.max(drawdowns))

    pnl = np.asarray([float(trade["net_pnl_usdt"]) for trade in trades], dtype=np.float64)
    bps = np.asarray([float(trade["net_bps"]) for trade in trades], dtype=np.float64)
    positive_sum = float(pnl[pnl > 0.0].sum()) if len(pnl) else 0.0
    negative_sum = float(-pnl[pnl < 0.0].sum()) if len(pnl) else 0.0
    if negative_sum > 0.0:
        profit_factor: float | None = positive_sum / negative_sum
    elif positive_sum > 0.0:
        profit_factor = None
    else:
        profit_factor = 0.0

    positive_sorted = np.sort(pnl[pnl > 0.0])[::-1] if len(pnl) else np.asarray([], dtype=np.float64)
    if positive_sum > 0.0:
        top5_share: float | None = float(positive_sorted[:5].sum() / positive_sum)
    else:
        top5_share = None

    half_split = pd.Timestamp(stage_start_ms, unit="ms", tz="UTC") + (
        pd.Timestamp(stage_end_ms, unit="ms", tz="UTC") - pd.Timestamp(stage_start_ms, unit="ms", tz="UTC")
    ) / 2
    half_split_ms = int(half_split.timestamp() * 1000)
    half_returns = [
        _period_return(trades, stage_start_ms, half_split_ms),
        _period_return(trades, half_split_ms + 1, stage_end_ms),
    ]

    start = pd.Timestamp(stage_start_ms, unit="ms", tz="UTC")
    end = pd.Timestamp(stage_end_ms, unit="ms", tz="UTC")
    boundaries = [
        int((start + (end - start) * fraction).timestamp() * 1000)
        for fraction in (0.0, 0.25, 0.50, 0.75, 1.0)
    ]
    quarter_returns = [
        _period_return(trades, boundaries[index], boundaries[index + 1] if index == 3 else boundaries[index + 1] - 1)
        for index in range(4)
    ]

    return {
        "trades": int(len(trades)),
        "final_nav": final_nav,
        "total_return": float(final_nav / initial_nav - 1.0),
        "geometric_daily_growth": geometric_daily_growth,
        "maximum_drawdown": maximum_drawdown,
        "mean_net_bps": float(np.mean(bps)) if len(bps) else None,
        "median_net_bps": float(np.median(bps)) if len(bps) else None,
        "profit_factor": profit_factor,
        "top5_positive_pnl_share": top5_share,
        "unresolved_fraction": float(np.mean([bool(trade["unresolved"]) for trade in trades])) if trades else 0.0,
        "half_returns": half_returns,
        "quarter_returns": quarter_returns,
        "positive_quarters": int(sum(value > 0.0 for value in quarter_returns)),
        "calendar_days": calendar_days,
    }


def largest_positive_event_ids(trades: list[dict[str, object]], fraction: float = 0.10) -> set[str]:
    positive = [trade for trade in trades if float(trade["net_pnl_usdt"]) > 0.0]
    positive.sort(key=lambda trade: (-float(trade["net_pnl_usdt"]), str(trade["event_id"])))
    if not positive:
        return set()
    count = max(1, int(math.ceil(len(positive) * float(fraction))))
    return {str(trade["event_id"]) for trade in positive[:count]}
