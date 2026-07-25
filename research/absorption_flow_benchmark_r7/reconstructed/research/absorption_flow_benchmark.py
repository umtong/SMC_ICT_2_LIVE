#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
TICK_SIZE = {"BTCUSDT": 0.1, "ETHUSDT": 0.01, "SOLUSDT": 0.001, "XRPUSDT": 0.0001}
QTY_STEP = {"BTCUSDT": 0.001, "ETHUSDT": 0.001, "SOLUSDT": 0.1, "XRPUSDT": 1.0}
MIN_NOTIONAL = {s: 5.0 for s in SYMBOLS}

DEVELOPMENT_START = pd.Timestamp("2022-04-03T00:00:00Z")
DEVELOPMENT_END = pd.Timestamp("2024-01-01T00:00:00Z")
VALIDATION_START = DEVELOPMENT_END
VALIDATION_END = pd.Timestamp("2025-07-01T00:00:00Z")


@dataclass(frozen=True)
class CostProfile:
    name: str
    fee_rate: float
    slippage_rate: float


COST_PROFILES = (
    CostProfile("base", 0.00055, 0.00020),
    CostProfile("stress_1p5x", 0.000825, 0.00030),
    CostProfile("stress_2x", 0.00110, 0.00040),
)


@dataclass(frozen=True)
class Candidate:
    family: str
    horizon_bars: int
    z_min: float
    z_max: float
    terminal_bars: int
    flow_threshold: float
    efficiency_min: float
    hold_min: float
    stop_buffer_atr: float
    reward_risk: float
    maximum_holding_minutes: int
    cross_state: str

    @property
    def candidate_id(self) -> str:
        zmax = "inf" if not np.isfinite(self.z_max) else f"{self.z_max:g}"
        return (
            f"{self.family}|h{self.horizon_bars}|z{self.z_min:g}-{zmax}|"
            f"t{self.terminal_bars}|f{self.flow_threshold:g}|e{self.efficiency_min:g}|"
            f"hold{self.hold_min:g}|buf{self.stop_buffer_atr:g}|rr{self.reward_risk:g}|"
            f"life{self.maximum_holding_minutes}|x{self.cross_state}"
        )


@dataclass(frozen=True)
class EngineConfig:
    initial_equity: float = 10_000.0
    risk_fraction: float = 0.005
    max_leverage: float = 5.0
    entry_delay_minutes: int = 0
    max_entry_delay_minutes: int = 2


@dataclass
class Event:
    candidate_id: str
    symbol: str
    signal_open_time: pd.Timestamp
    decision_time: pd.Timestamp
    entry_time: pd.Timestamp
    side: int
    score: float
    atr: float
    stop_reference: float
    displacement_extreme: float
    family: str


@dataclass
class Trade:
    candidate_id: str
    cost_profile: str
    symbol: str
    side: int
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_trigger: float
    target_trigger: float
    exit_price: float
    quantity: float
    equity_before: float
    net_pnl: float
    funding_pnl: float
    fees: float
    r_multiple: float
    exit_reason: str
    bars_held: int
    leverage: float
    signal_score: float


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_timestamp(values: pd.Series) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(pd.to_datetime(values, utc=True, errors="raise"))
    if result.tz is None:
        result = result.tz_localize("UTC")
    else:
        result = result.tz_convert("UTC")
    return result


def load_minute(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    required = [
        "timestamp", "open", "high", "low", "close", "volume", "quote_volume",
        "num_trades", "taker_buy_base_volume", "taker_buy_quote_volume",
    ]
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    frame = frame[required].copy()
    frame.index = normalize_timestamp(frame.pop("timestamp"))
    frame.index.name = "timestamp"
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError(f"{path}: timestamps must be increasing and unique")
    for column in frame:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    invalid = (
        (frame.high < frame[["open", "close"]].max(axis=1))
        | (frame.low > frame[["open", "close"]].min(axis=1))
        | (frame.high < frame.low)
        | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (frame.quote_volume < 0)
        | (frame.num_trades < 0)
    )
    if invalid.any():
        raise ValueError(f"{path}: invalid rows={int(invalid.sum())}")
    frame["signed_quote"] = 2.0 * frame.taker_buy_quote_volume - frame.quote_volume
    return frame


def load_funding(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if "timestamp" not in frame or "funding_rate" not in frame:
        raise ValueError(f"{path}: funding schema")
    frame = frame[["timestamp", "funding_rate"]].copy()
    frame.index = normalize_timestamp(frame.pop("timestamp"))
    frame.index.name = "timestamp"
    frame.funding_rate = pd.to_numeric(frame.funding_rate, errors="raise")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{path}: funding timestamps")
    return frame


def strict_resample_5m(minute: pd.DataFrame) -> pd.DataFrame:
    grouped = minute.resample("5min", label="left", closed="left", origin="epoch")
    out = grouped.agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), quote_volume=("quote_volume", "sum"), num_trades=("num_trades", "sum"),
        signed_quote=("signed_quote", "sum"), minute_count=("close", "count"),
    )
    timestamp_series = pd.Series(minute.index, index=minute.index)
    first = timestamp_series.resample("5min", label="left", closed="left", origin="epoch").first()
    last = timestamp_series.resample("5min", label="left", closed="left", origin="epoch").last()
    exact = (
        out.minute_count.eq(5)
        & first.eq(first.index)
        & last.eq(last.index + pd.Timedelta(minutes=4))
    )
    out = out.loc[exact].drop(columns="minute_count")
    out["ret_1"] = np.log(out.close / out.close.shift(1))
    out["flow_imbalance"] = out.signed_quote / out.quote_volume.replace(0, np.nan)
    return out


def prior_z(series: pd.Series, window: int, minimum: int) -> pd.Series:
    shifted = series.shift(1)
    mean = shifted.rolling(window, min_periods=minimum).mean()
    std = shifted.rolling(window, min_periods=minimum).std(ddof=0).replace(0, np.nan)
    return (series - mean) / std


def prepare_features(five_by_symbol: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    prepared: dict[str, pd.DataFrame] = {}
    common_index = None
    for frame in five_by_symbol.values():
        idx = frame.loc[DEVELOPMENT_START:VALIDATION_END - pd.Timedelta(minutes=1)].index
        common_index = idx if common_index is None else common_index.intersection(idx)
    if common_index is None or len(common_index) == 0:
        raise ValueError("empty common index")
    common_index = common_index.sort_values()
    horizon_returns: dict[int, pd.DataFrame] = {}
    for horizon in (12, 24, 48):
        values = {}
        for symbol, frame in five_by_symbol.items():
            aligned = frame.reindex(common_index)
            values[symbol] = np.log(aligned.close / aligned.close.shift(horizon))
        returns = pd.DataFrame(values, index=common_index)
        horizon_returns[horizon] = returns

    for symbol, original in five_by_symbol.items():
        frame = original.copy()
        atr = pd.concat([
            frame.high - frame.low,
            (frame.high - frame.close.shift(1)).abs(),
            (frame.low - frame.close.shift(1)).abs(),
        ], axis=1).max(axis=1).rolling(48, min_periods=48).mean()
        frame["atr"] = atr
        frame["volume_z"] = prior_z(np.log1p(frame.quote_volume), 2016, 576)
        frame["trade_z"] = prior_z(np.log1p(frame.num_trades), 2016, 576)
        for terminal in (3, 6):
            terminal_quote = frame.quote_volume.rolling(terminal, min_periods=terminal).sum()
            frame[f"flow_{terminal}"] = frame.signed_quote.rolling(terminal, min_periods=terminal).sum() / terminal_quote.replace(0, np.nan)
        for horizon in (12, 24, 48):
            displacement = np.log(frame.close / frame.close.shift(horizon))
            sigma = frame.ret_1.shift(1).rolling(2016, min_periods=576).std(ddof=0)
            frame[f"disp_{horizon}"] = displacement
            frame[f"z_{horizon}"] = displacement / (sigma * math.sqrt(horizon)).replace(0, np.nan)
            path = frame.ret_1.abs().rolling(horizon, min_periods=horizon).sum()
            frame[f"eff_{horizon}"] = displacement.abs() / path.replace(0, np.nan)
            rolling_high = frame.high.rolling(horizon + 1, min_periods=horizon + 1).max()
            rolling_low = frame.low.rolling(horizon + 1, min_periods=horizon + 1).min()
            span = (rolling_high - rolling_low).replace(0, np.nan)
            frame[f"high_{horizon}"] = rolling_high
            frame[f"low_{horizon}"] = rolling_low
            frame[f"long_hold_{horizon}"] = (frame.close - rolling_low) / span
            frame[f"short_hold_{horizon}"] = (rolling_high - frame.close) / span
            # Ensure horizon observations are exactly five minutes apart; no silent crossing of data gaps.
            expected = frame.index.to_series().shift(horizon) + pd.Timedelta(minutes=5 * horizon)
            frame[f"exact_{horizon}"] = expected.eq(frame.index.to_series())
            common = horizon_returns[horizon].median(axis=1, skipna=False)
            common = common.reindex(frame.index)
            frame[f"common_{horizon}"] = common
            frame[f"residual_{horizon}"] = displacement - common
        prepared[symbol] = frame
    return prepared


def candidate_grid() -> list[Candidate]:
    candidates: list[Candidate] = []
    # Economically distinct families. Parameter count is deliberately modest and disclosed.
    for family in ("absorption_continuation", "aligned_continuation", "absorption_reversal"):
        for horizon in (12, 24, 48):
            for regime in ((2.0, 4.5), (3.0, math.inf)):
                for terminal in (3, 6):
                    for reward_risk in (1.0, 2.0, 4.0):
                        if family == "absorption_continuation":
                            flow_threshold, efficiency_min, hold_min = -0.05, 0.35, 0.70
                        elif family == "aligned_continuation":
                            flow_threshold, efficiency_min, hold_min = 0.10, 0.45, 0.70
                        else:
                            flow_threshold, efficiency_min, hold_min = -0.05, 0.25, 0.50
                        maximum_holding = {1.0: 240, 2.0: 480, 4.0: 720}[reward_risk]
                        for cross_state in ("none", "idiosyncratic"):
                            candidates.append(Candidate(
                                family=family,
                                horizon_bars=horizon,
                                z_min=regime[0],
                                z_max=regime[1],
                                terminal_bars=terminal,
                                flow_threshold=flow_threshold,
                                efficiency_min=efficiency_min,
                                hold_min=hold_min,
                                stop_buffer_atr=0.25 if horizon <= 24 else 0.50,
                                reward_risk=reward_risk,
                                maximum_holding_minutes=maximum_holding,
                                cross_state=cross_state,
                            ))
    return candidates


def generate_events(features: dict[str, pd.DataFrame], candidate: Candidate, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
    events: list[Event] = []
    h = candidate.horizon_bars
    for symbol, frame in features.items():
        section = frame.loc[start - pd.Timedelta(days=14):end - pd.Timedelta(minutes=1)].copy()
        displacement = section[f"disp_{h}"]
        direction = np.sign(displacement).astype("float")
        abs_z = section[f"z_{h}"].abs()
        flow_directional = direction * section[f"flow_{candidate.terminal_bars}"]
        hold = pd.Series(np.where(direction > 0, section[f"long_hold_{h}"], section[f"short_hold_{h}"]), index=section.index)
        common_directional = direction * section[f"common_{h}"]
        residual_directional = direction * section[f"residual_{h}"]

        base = (
            section[f"exact_{h}"].fillna(False)
            & abs_z.ge(candidate.z_min)
            & (abs_z.lt(candidate.z_max) if np.isfinite(candidate.z_max) else True)
            & section[f"eff_{h}"].ge(candidate.efficiency_min)
            & section.atr.gt(0)
            & section.volume_z.gt(-1.0)
            & section.trade_z.gt(-1.0)
            & direction.ne(0)
        )
        if candidate.cross_state == "idiosyncratic":
            # Require asset-specific displacement beyond the four-asset common move.
            base &= residual_directional.gt(0.0010) & common_directional.gt(-0.0020)

        if candidate.family == "absorption_continuation":
            condition = base & flow_directional.le(candidate.flow_threshold) & hold.ge(candidate.hold_min)
            side = direction
        elif candidate.family == "aligned_continuation":
            condition = base & flow_directional.ge(candidate.flow_threshold) & hold.ge(candidate.hold_min)
            side = direction
        else:
            last_return_directional = direction * section.ret_1
            condition = (
                base
                & flow_directional.le(candidate.flow_threshold)
                & last_return_directional.lt(0)
                & hold.le(0.70)
                & hold.ge(0.30)
            )
            side = -direction

        # One candidate per state episode, not one per bar while the same condition persists.
        episode = condition & ~condition.shift(1, fill_value=False)
        episode &= (episode.index >= start) & (episode.index < end)
        indices = np.flatnonzero(episode.to_numpy(bool))
        for idx in indices:
            row = section.iloc[idx]
            open_time = section.index[idx]
            decision = open_time + pd.Timedelta(minutes=5)
            signal_side = int(side.iloc[idx])
            if candidate.family == "absorption_reversal":
                stop_reference = float(row[f"high_{h}"] if signal_side < 0 else row[f"low_{h}"])
            else:
                terminal_slice = section.iloc[max(0, idx - candidate.terminal_bars + 1):idx + 1]
                stop_reference = float(terminal_slice.low.min() if signal_side > 0 else terminal_slice.high.max())
            displacement_extreme = float(row[f"high_{h}"] if signal_side < 0 else row[f"low_{h}"])
            score = float(abs_z.iloc[idx] * max(section[f"eff_{h}"].iloc[idx], 0) * (1 + abs(flow_directional.iloc[idx])))
            events.append(Event(
                candidate_id=candidate.candidate_id,
                symbol=symbol,
                signal_open_time=open_time,
                decision_time=decision,
                entry_time=decision,
                side=signal_side,
                score=score,
                atr=float(row.atr),
                stop_reference=stop_reference,
                displacement_extreme=displacement_extreme,
                family=candidate.family,
            ))
    return sorted(events, key=lambda event: (event.entry_time, -event.score, event.symbol))


def round_down(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step + 1e-12) * step


def trigger_for_net_reward(entry_exec: float, unit_loss: float, side: int, reward_risk: float, cost: CostProfile) -> float:
    target_net = reward_risk * unit_loss
    if side > 0:
        exit_exec = (entry_exec * (1 + cost.fee_rate) + target_net) / (1 - cost.fee_rate)
        return exit_exec / (1 - cost.slippage_rate)
    exit_exec = (entry_exec * (1 - cost.fee_rate) - target_net) / (1 + cost.fee_rate)
    return exit_exec / (1 + cost.slippage_rate)


def funding_for_trade(
    symbol: str,
    side: int,
    quantity: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
    funding: dict[str, pd.DataFrame],
    minute: dict[str, pd.DataFrame],
) -> float:
    settlements = funding[symbol]
    rows = settlements[(settlements.index > start) & (settlements.index <= end)]
    if rows.empty:
        return 0.0
    total = 0.0
    price_frame = minute[symbol]
    for timestamp, row in rows.iterrows():
        minute_time = timestamp.floor("min")
        pos = price_frame.index.searchsorted(minute_time, side="left")
        if pos >= len(price_frame) or price_frame.index[pos] - minute_time > pd.Timedelta(minutes=2):
            continue
        mark_proxy = float(price_frame.open.iloc[pos])
        total += -side * quantity * mark_proxy * float(row.funding_rate)
    return total


def execute_event(
    event: Event,
    candidate: Candidate,
    equity: float,
    minute: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    cost: CostProfile,
    engine: EngineConfig,
) -> Trade | None:
    bars = minute[event.symbol]
    pos = bars.index.searchsorted(event.entry_time, side="left")
    if pos >= len(bars):
        return None
    actual_entry_time = bars.index[pos]
    if actual_entry_time - event.entry_time > pd.Timedelta(minutes=engine.max_entry_delay_minutes):
        return None
    raw_entry = float(bars.open.iloc[pos])
    entry_exec = raw_entry * (1 + cost.slippage_rate * event.side)
    stop_trigger = event.stop_reference - candidate.stop_buffer_atr * event.atr if event.side > 0 else event.stop_reference + candidate.stop_buffer_atr * event.atr
    if event.side > 0 and not (0 < stop_trigger < raw_entry):
        return None
    if event.side < 0 and not (stop_trigger > raw_entry > 0):
        return None
    stop_exec_nominal = stop_trigger * (1 - cost.slippage_rate * event.side)
    unit_loss = event.side * (entry_exec - stop_exec_nominal) + cost.fee_rate * (entry_exec + stop_exec_nominal)
    if not np.isfinite(unit_loss) or unit_loss <= 0:
        return None
    target_trigger = trigger_for_net_reward(entry_exec, unit_loss, event.side, candidate.reward_risk, cost)
    if event.side > 0 and target_trigger <= raw_entry:
        return None
    if event.side < 0 and target_trigger >= raw_entry:
        return None
    risk_cash = equity * engine.risk_fraction
    quantity = min(risk_cash / unit_loss, equity * engine.max_leverage / entry_exec)
    quantity = round_down(quantity, QTY_STEP[event.symbol])
    if quantity <= 0 or quantity * raw_entry < MIN_NOTIONAL[event.symbol]:
        return None
    leverage = quantity * raw_entry / equity
    max_exit_time = actual_entry_time + pd.Timedelta(minutes=candidate.maximum_holding_minutes)
    end_pos = bars.index.searchsorted(max_exit_time, side="left")
    end_pos = min(end_pos, len(bars) - 1)
    segment = bars.iloc[pos:end_pos + 1]
    if segment.empty:
        return None
    diffs = segment.index.to_series().diff().dropna()
    if (diffs > pd.Timedelta(minutes=1)).any():
        return None

    exit_time: pd.Timestamp | None = None
    exit_raw: float | None = None
    reason = ""
    for bar_time, row in segment.iterrows():
        open_price, high, low = float(row.open), float(row.high), float(row.low)
        if event.side > 0:
            if open_price <= stop_trigger:
                exit_time, exit_raw, reason = bar_time, open_price, "gap_stop"
                break
            stop_hit = low <= stop_trigger
            target_hit = high >= target_trigger
            if stop_hit:
                exit_time, exit_raw, reason = bar_time, stop_trigger, "stop"
                break
            if target_hit:
                exit_time, exit_raw, reason = bar_time, target_trigger, "target"
                break
        else:
            if open_price >= stop_trigger:
                exit_time, exit_raw, reason = bar_time, open_price, "gap_stop"
                break
            stop_hit = high >= stop_trigger
            target_hit = low <= target_trigger
            if stop_hit:
                exit_time, exit_raw, reason = bar_time, stop_trigger, "stop"
                break
            if target_hit:
                exit_time, exit_raw, reason = bar_time, target_trigger, "target"
                break
    if exit_time is None:
        scheduled = max_exit_time
        horizon_pos = bars.index.searchsorted(scheduled, side="left")
        if horizon_pos >= len(bars) or bars.index[horizon_pos] - scheduled > pd.Timedelta(minutes=2):
            return None
        exit_time = bars.index[horizon_pos]
        exit_raw = float(bars.open.iloc[horizon_pos])
        reason = "horizon"
    assert exit_raw is not None
    exit_exec = exit_raw * (1 - cost.slippage_rate * event.side)
    gross = event.side * quantity * (exit_exec - entry_exec)
    fees = quantity * cost.fee_rate * (entry_exec + exit_exec)
    funding_pnl = funding_for_trade(event.symbol, event.side, quantity, actual_entry_time, exit_time, funding, minute)
    net = gross - fees + funding_pnl
    planned_risk = quantity * unit_loss
    r_multiple = net / planned_risk if planned_risk > 0 else np.nan
    return Trade(
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
        r_multiple=float(r_multiple),
        exit_reason=reason,
        bars_held=int((exit_time - actual_entry_time) / pd.Timedelta(minutes=1)),
        leverage=leverage,
        signal_score=event.score,
    )


def simulate(
    events: list[Event],
    candidate: Candidate,
    minute: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    cost: CostProfile,
    start: pd.Timestamp,
    end: pd.Timestamp,
    engine: EngineConfig,
) -> tuple[pd.DataFrame, pd.Series]:
    filtered = [event for event in events if start <= event.entry_time < end]
    equity = engine.initial_equity
    free_time = start
    trades: list[Trade] = []
    i = 0
    while i < len(filtered):
        timestamp = filtered[i].entry_time
        group: list[Event] = []
        while i < len(filtered) and filtered[i].entry_time == timestamp:
            group.append(filtered[i]); i += 1
        if timestamp < free_time:
            continue
        selected = max(group, key=lambda event: (event.score, -SYMBOLS.index(event.symbol)))
        trade = execute_event(selected, candidate, equity, minute, funding, cost, engine)
        if trade is None:
            continue
        equity += trade.net_pnl
        if equity <= 0:
            trades.append(trade)
            break
        trades.append(trade)
        free_time = trade.exit_time + pd.Timedelta(minutes=1)
    frame = pd.DataFrame([dataclasses.asdict(trade) for trade in trades])
    daily_index = pd.date_range(start.floor("D"), end.ceil("D"), freq="1D", inclusive="left", tz="UTC")
    daily = pd.Series(engine.initial_equity, index=daily_index, dtype=float)
    if not frame.empty:
        frame["exit_time"] = pd.to_datetime(frame.exit_time, utc=True)
        cumulative = engine.initial_equity + frame.set_index("exit_time").net_pnl.cumsum()
        union = daily.index.union(cumulative.index).sort_values()
        series = cumulative.reindex(union).ffill().fillna(engine.initial_equity)
        daily = series.reindex(daily.index, method="ffill").fillna(engine.initial_equity)
    return frame, daily


def metrics(trades: pd.DataFrame, daily_equity: pd.Series, initial_equity: float) -> dict[str, Any]:
    if trades.empty:
        return {
            "trade_count": 0, "total_return": 0.0, "geometric_daily": 0.0, "max_drawdown": 0.0,
            "average_r": np.nan, "profit_factor": 0.0, "win_rate": 0.0, "top1_share": 1.0,
            "top5_share": 1.0, "top10_share": 1.0, "return_without_top5": -1.0,
            "positive_month_fraction": 0.0, "median_holding_minutes": np.nan, "max_leverage": 0.0,
        }
    end_equity = initial_equity + float(trades.net_pnl.sum())
    total_return = end_equity / initial_equity - 1.0
    days = max((daily_equity.index[-1] - daily_equity.index[0]) / pd.Timedelta(days=1), 1)
    geometric_daily = (end_equity / initial_equity) ** (1.0 / days) - 1.0 if end_equity > 0 else -1.0
    curve = daily_equity.to_numpy(float)
    peaks = np.maximum.accumulate(curve)
    max_drawdown = float(np.min(curve / peaks - 1.0))
    positive = trades.loc[trades.net_pnl > 0, "net_pnl"].to_numpy(float)
    negative = -trades.loc[trades.net_pnl < 0, "net_pnl"].to_numpy(float)
    profit_factor = float(positive.sum() / negative.sum()) if negative.sum() > 0 else (999.0 if positive.sum() > 0 else 0.0)
    sorted_positive = np.sort(positive)[::-1]
    positive_total = positive.sum()
    share = lambda count: float(sorted_positive[:count].sum() / positive_total) if positive_total > 0 else 1.0
    remove = min(5, len(trades))
    top_indices = trades.net_pnl.nlargest(remove).index
    without_top = (initial_equity + trades.drop(top_indices).net_pnl.sum()) / initial_equity - 1.0
    monthly = daily_equity.resample("MS").last().pct_change().dropna()
    return {
        "trade_count": int(len(trades)),
        "total_return": float(total_return),
        "geometric_daily": float(geometric_daily),
        "max_drawdown": max_drawdown,
        "average_r": float(trades.r_multiple.mean()),
        "profit_factor": profit_factor,
        "win_rate": float((trades.net_pnl > 0).mean()),
        "top1_share": share(1), "top5_share": share(5), "top10_share": share(10),
        "return_without_top5": float(without_top),
        "positive_month_fraction": float((monthly > 0).mean()) if len(monthly) else 0.0,
        "median_holding_minutes": float(trades.bars_held.median()),
        "max_leverage": float(trades.leverage.max()),
        "funding_pnl": float(trades.funding_pnl.sum()),
        "fees": float(trades.fees.sum()),
    }


def gate_development(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    pivot = rows.pivot_table(index="candidate_id", columns=["period", "cost_profile"], values=[
        "trade_count", "total_return", "average_r", "profit_factor", "max_drawdown", "top5_share",
        "return_without_top5", "positive_month_fraction", "geometric_daily",
    ], aggfunc="first")
    records = []
    for candidate_id, row in pivot.iterrows():
        def value(metric: str, period: str, cost: str, default: float = np.nan) -> float:
            try: return float(row[(metric, period, cost)])
            except Exception: return default
        eligible = True
        for period in ("dev_2022", "dev_2023"):
            for cost in ("base", "stress_2x"):
                eligible &= value("trade_count", period, cost, 0) >= 20
                eligible &= value("total_return", period, cost, -1) > 0
                eligible &= value("average_r", period, cost, -1) > 0
                eligible &= value("profit_factor", period, cost, 0) >= 1.10
                eligible &= value("max_drawdown", period, cost, -1) >= -0.20
                eligible &= value("top5_share", period, cost, 1) <= 0.55
                eligible &= value("return_without_top5", period, cost, -1) > -0.05
        score = min(value("geometric_daily", p, "stress_2x", -1) for p in ("dev_2022", "dev_2023"))
        records.append({"candidate_id": candidate_id, "eligible_development": bool(eligible), "development_score": score})
    return pd.DataFrame(records).sort_values(["eligible_development", "development_score"], ascending=[False, False])


def evaluate_candidate(
    candidate: Candidate,
    events: list[Event],
    minute: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    periods: dict[str, tuple[pd.Timestamp, pd.Timestamp]],
    costs: Iterable[CostProfile],
    engine: EngineConfig,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], pd.DataFrame]]:
    rows: list[dict[str, Any]] = []
    ledgers: dict[tuple[str, str], pd.DataFrame] = {}
    for period_name, (start, end) in periods.items():
        for cost in costs:
            trades, daily = simulate(events, candidate, minute, funding, cost, start, end, engine)
            row = {"candidate_id": candidate.candidate_id, "family": candidate.family, "period": period_name, "cost_profile": cost.name, **metrics(trades, daily, engine.initial_equity)}
            rows.append(row)
            ledgers[(period_name, cost.name)] = trades
    return rows, ledgers


def build_manifest(paths: dict[str, Path], funding_paths: dict[str, Path], minute: dict[str, pd.DataFrame]) -> dict[str, Any]:
    records = {}
    for symbol in SYMBOLS:
        idx = minute[symbol].index
        gaps = idx.to_series().diff().dropna()
        abnormal = gaps[gaps != pd.Timedelta(minutes=1)]
        records[symbol] = {
            "path": str(paths[symbol]), "sha256": sha256_path(paths[symbol]), "bytes": paths[symbol].stat().st_size,
            "rows": len(minute[symbol]), "start": idx.min().isoformat(), "end": idx.max().isoformat(),
            "abnormal_gap_count": int(len(abnormal)), "largest_gap_seconds": float(abnormal.max().total_seconds()) if len(abnormal) else 0.0,
            "funding_path": str(funding_paths[symbol]), "funding_sha256": sha256_path(funding_paths[symbol]),
        }
    return {
        "schema_version": 1,
        "dataset_id": "BINANCE_USDM_4ASSET_1M_PREHOLDOUT_V1",
        "source_contract": "BTC/ETH hash-pinned public derivative cache; SOL/XRP official Binance Vision checksum-verified cache",
        "symbols": list(SYMBOLS),
        "holdout_cutoff_exclusive": VALIDATION_END.isoformat(),
        "development_start": DEVELOPMENT_START.isoformat(),
        "no_gap_fill": True,
        "timestamp_semantics": "bar open UTC; decisions after completed bars",
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", choices=["prepare", "screen", "validate", "all"], default="all")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    paths = {
        "BTCUSDT": args.data_root / "btc_eth/BTCUSDT_preholdout.parquet",
        "ETHUSDT": args.data_root / "btc_eth/ETHUSDT_preholdout.parquet",
        "SOLUSDT": args.data_root / "sol_xrp_flow/SOLUSDT_official_preholdout.parquet",
        "XRPUSDT": args.data_root / "sol_xrp_flow/XRPUSDT_official_preholdout.parquet",
    }
    funding_paths = {
        "BTCUSDT": args.data_root / "btc_eth/BTCUSDT_funding_preholdout.parquet",
        "ETHUSDT": args.data_root / "btc_eth/ETHUSDT_funding_preholdout.parquet",
        "SOLUSDT": args.data_root / "sol_xrp_funding/SOLUSDT_funding_preholdout.parquet",
        "XRPUSDT": args.data_root / "sol_xrp_funding/XRPUSDT_funding_preholdout.parquet",
    }
    minute = {symbol: load_minute(path) for symbol, path in paths.items()}
    funding = {symbol: load_funding(path) for symbol, path in funding_paths.items()}
    manifest = build_manifest(paths, funding_paths, minute)
    (args.output / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    five = {symbol: strict_resample_5m(frame) for symbol, frame in minute.items()}
    features = prepare_features(five)
    engine = EngineConfig()
    candidates = candidate_grid()
    prereg = {
        "schema_version": 1,
        "study_id": "ABSORPTION_FLOW_BENCHMARK_V1",
        "candidate_count": len(candidates),
        "candidate_ids": [candidate.candidate_id for candidate in candidates],
        "development": [DEVELOPMENT_START.isoformat(), DEVELOPMENT_END.isoformat()],
        "validation": [VALIDATION_START.isoformat(), VALIDATION_END.isoformat()],
        "cost_profiles": [dataclasses.asdict(cost) for cost in COST_PROFILES],
        "engine": dataclasses.asdict(engine),
        "families": ["absorption_continuation", "aligned_continuation", "absorption_reversal"],
        "validation_open_rule": "Only candidates passing both 2022 and 2023 base and 2x development gates are evaluated on 2024 and 2025H1.",
        "terminal_holdout_opened": False,
    }
    (args.output / "preregistration.json").write_text(json.dumps(prereg, indent=2), encoding="utf-8")

    development_periods = {
        "dev_2022": (DEVELOPMENT_START, pd.Timestamp("2023-01-01T00:00:00Z")),
        "dev_2023": (pd.Timestamp("2023-01-01T00:00:00Z"), DEVELOPMENT_END),
    }
    screen_rows: list[dict[str, Any]] = []
    event_cache: dict[str, list[Event]] = {}
    for number, candidate in enumerate(candidates, start=1):
        events = generate_events(features, candidate, DEVELOPMENT_START, VALIDATION_END)
        event_cache[candidate.candidate_id] = events
        rows, _ = evaluate_candidate(candidate, events, minute, funding, development_periods, COST_PROFILES, engine)
        screen_rows.extend(rows)
        if number % 12 == 0:
            print(f"development {number}/{len(candidates)}", flush=True)
    screen = pd.DataFrame(screen_rows)
    screen.to_parquet(args.output / "development_screen.parquet", index=False)
    ranking = gate_development(screen)
    ranking.to_csv(args.output / "development_ranking.csv", index=False)
    survivors = ranking.loc[ranking.eligible_development].copy()
    top_ids = survivors.head(12).candidate_id.tolist()

    validation_rows: list[dict[str, Any]] = []
    ledgers_out: list[pd.DataFrame] = []
    candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
    validation_periods = {
        "oos_2024": (VALIDATION_START, pd.Timestamp("2025-01-01T00:00:00Z")),
        "oos_2025H1": (pd.Timestamp("2025-01-01T00:00:00Z"), VALIDATION_END),
    }
    for candidate_id in top_ids:
        candidate = candidate_map[candidate_id]
        rows, ledgers = evaluate_candidate(candidate, event_cache[candidate_id], minute, funding, validation_periods, COST_PROFILES, engine)
        validation_rows.extend(rows)
        for (period, cost), ledger in ledgers.items():
            if not ledger.empty:
                copy = ledger.copy(); copy["period"] = period; copy["cost_profile"] = cost
                ledgers_out.append(copy)
    validation = pd.DataFrame(validation_rows)
    validation.to_csv(args.output / "validation_results.csv", index=False)
    ledgers_frame = pd.concat(ledgers_out, ignore_index=True) if ledgers_out else pd.DataFrame()
    ledgers_frame.to_parquet(args.output / "validation_trades.parquet", index=False)

    robust = []
    if not validation.empty:
        for candidate_id, group in validation.groupby("candidate_id"):
            okay = True
            for period in validation_periods:
                for cost in ("base", "stress_2x"):
                    row = group[(group.period == period) & (group.cost_profile == cost)]
                    if row.empty:
                        okay = False; continue
                    r = row.iloc[0]
                    okay &= r.trade_count >= 20 and r.total_return > 0 and r.average_r > 0 and r.profit_factor >= 1.10
                    okay &= r.max_drawdown >= -0.20 and r.top5_share <= 0.55 and r.return_without_top5 > -0.05
            min_g = group[group.cost_profile == "stress_2x"].geometric_daily.min()
            robust.append({"candidate_id": candidate_id, "robust_oos": bool(okay), "min_oos_2x_geometric_daily": float(min_g)})
    robust_frame = pd.DataFrame(robust).sort_values(["robust_oos", "min_oos_2x_geometric_daily"], ascending=[False, False]) if robust else pd.DataFrame(columns=["candidate_id", "robust_oos", "min_oos_2x_geometric_daily"])
    robust_frame.to_csv(args.output / "robust_oos.csv", index=False)
    best = robust_frame.iloc[0].to_dict() if len(robust_frame) else None
    target_pass = bool(best and best["robust_oos"] and best["min_oos_2x_geometric_daily"] >= 0.01)
    summary = {
        "status": "COMPLETE",
        "study_id": "ABSORPTION_FLOW_BENCHMARK_V1",
        "candidate_count": len(candidates),
        "development_survivors": len(survivors),
        "validation_candidates": len(top_ids),
        "robust_oos_count": int(robust_frame.robust_oos.sum()) if len(robust_frame) else 0,
        "best": best,
        "target_passed": target_pass,
        "champion_eligible": target_pass,
        "terminal_holdout_opened": False,
        "orders_submitted": False,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
