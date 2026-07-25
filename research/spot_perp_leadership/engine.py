from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import asdict, dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from .data import BAR_MS, SYMBOLS, PairMarket
from .features import PairFeatures

@dataclass(frozen=True, slots=True)
class Config:
    family: str
    lag: int
    leadership_window: int
    leadership_threshold: float
    signal_threshold: float
    response_threshold: float
    flow_threshold: float
    hold: int
    stop_atr: float

    @property
    def config_id(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

@dataclass(frozen=True, slots=True)
class Costs:
    entry: float = 6.0
    normal_exit: float = 6.0
    stop_exit: float = 8.0
    funding_buffer: float = 1.0

    def scale(self, multiplier: float) -> "Costs":
        return Costs(
            self.entry * multiplier,
            self.normal_exit * multiplier,
            self.stop_exit * multiplier,
            self.funding_buffer * multiplier,
        )

@dataclass(frozen=True, slots=True)
class Candidate:
    signal_ms: int
    symbol_index: int
    bar_index: int
    side: int
    score: float
    tie: int

@dataclass(frozen=True, slots=True)
class Trade:
    config_id: str
    family: str
    signal_ms: int
    entry_ms: int
    exit_ms: int
    symbol: str
    side: int
    score: float
    entry: float
    exit: float
    stop: float
    stopped: bool
    net_bps: float
    net_r: float
    planned_loss: float
    notional: float
    account_return: float

def config_grid() -> list[Config]:
    """Compact economically distinct grid; thresholds are not locally fine-tuned."""
    rows: list[Config] = []
    lags, holds, stops = (1, 5, 15), (5, 15, 30), (1.5, 2.5)
    leadership_window = 2_880
    for lag, lead, shock, response, flow, hold, stop in itertools.product(
        lags, (0.02, 0.08), (1.5, 2.5), (0.5, 1.0),
        (0.0, 0.10), holds, stops,
    ):
        rows.append(Config(
            "spot_underreaction_continuation", lag, leadership_window,
            lead, shock, response, flow, hold, stop,
        ))
    for lag, lead, shock, flow, hold, stop in itertools.product(
        lags, (0.02, 0.08), (1.5, 2.5), (0.0, 0.10), holds, stops,
    ):
        rows.append(Config(
            "perp_led_continuation", lag, leadership_window,
            lead, shock, 0.5, flow, hold, stop,
        ))
    for family in ("basis_convergence", "basis_widening_continuation"):
        for lag, threshold, flow, hold, stop in itertools.product(
            lags, (1.5, 2.5), (0.0, 0.10), holds, stops,
        ):
            rows.append(Config(
                family, lag, leadership_window, 0.0,
                threshold, 0.5, flow, hold, stop,
            ))
    for lag, shock, flow, hold, stop in itertools.product(
        lags, (1.5, 2.5), (0.0, 0.10), holds, stops,
    ):
        rows.append(Config(
            "flow_divergence_reversal", lag, leadership_window,
            0.0, shock, 0.5, flow, hold, stop,
        ))
    return rows

def candidates(symbol_index: int, market: PairMarket, features: PairFeatures, config: Config) -> list[Candidate]:
    lag = config.lag
    leadership = features.leadership[config.leadership_window]
    spot_z = features.spot_retz[lag]
    perp_z = features.perp_retz[lag]
    spot_side, perp_side = np.sign(spot_z), np.sign(perp_z)
    spot_flow = spot_side * features.spot_tfi[lag]
    perp_flow_for_spot = spot_side * features.perp_tfi[lag]
    perp_flow = perp_side * features.perp_tfi[lag]
    spot_flow_for_perp = perp_side * features.spot_tfi[lag]
    if config.family == "spot_underreaction_continuation":
        mask = (
            (leadership >= config.leadership_threshold)
            & (abs(spot_z) >= config.signal_threshold)
            & (features.spot_to_perp_gap_z[lag] >= config.response_threshold)
            & (spot_flow >= config.flow_threshold)
            & (perp_flow_for_spot >= -0.05)
        )
        side = spot_side
        score = abs(spot_z) + features.spot_to_perp_gap_z[lag] + np.maximum(spot_flow, 0) + np.maximum(perp_flow_for_spot, 0)
    elif config.family == "perp_led_continuation":
        mask = (
            (leadership <= -config.leadership_threshold)
            & (abs(perp_z) >= config.signal_threshold)
            & (perp_flow >= config.flow_threshold)
            & (spot_flow_for_perp >= 0)
            & (features.perp_to_spot_gap_z[lag] >= -0.5)
        )
        side = perp_side
        score = abs(perp_z) + np.maximum(perp_flow, 0) + np.maximum(spot_flow_for_perp, 0) + abs(leadership)
    elif config.family == "basis_convergence":
        basis_side = -np.sign(features.basis_z)
        basis_flow = basis_side * features.perp_tfi[lag]
        mask = (
            (abs(features.basis_z) >= config.signal_threshold)
            & (basis_side * features.basis_change_z[lag] >= 0)
            & (basis_flow >= config.flow_threshold)
        )
        side = basis_side
        score = abs(features.basis_z) + np.maximum(basis_flow, 0) + np.maximum(basis_side * features.basis_change_z[lag], 0)
    elif config.family == "basis_widening_continuation":
        widening_side = np.sign(features.basis_change_z[lag])
        widening_flow = widening_side * features.perp_tfi[lag]
        mask = (
            (abs(features.basis_z) >= config.signal_threshold)
            & (abs(features.basis_change_z[lag]) >= config.response_threshold)
            & (np.sign(features.basis_z) == widening_side)
            & (widening_flow >= config.flow_threshold)
        )
        side = widening_side
        score = abs(features.basis_z) + abs(features.basis_change_z[lag]) + np.maximum(widening_flow, 0)
    else:
        price_side = perp_side
        divergence = -price_side * features.perp_tfi[lag]
        spot_confirmation = price_side * features.spot_tfi[lag]
        mask = (
            (abs(perp_z) >= config.signal_threshold)
            & (divergence >= config.flow_threshold)
            & (spot_confirmation >= 0)
        )
        side = -price_side
        score = abs(perp_z) + np.maximum(divergence, 0) + np.maximum(spot_confirmation, 0)
    valid = mask & np.isfinite(score) & np.isfinite(side) & (side != 0)
    bars = np.flatnonzero(valid)
    return [
        Candidate(int(market.times[bar]), symbol_index, int(bar), int(side[bar]), float(score[bar]), int(bar))
        for bar in bars
    ]

def simulate(
    markets: Mapping[str, PairMarket],
    feature_map: Mapping[str, PairFeatures],
    config: Config,
    costs: Costs,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[Trade]:
    lower, upper = int(start.value // 1_000_000), int(end.value // 1_000_000)
    all_candidates: list[Candidate] = []
    for symbol_index, symbol in enumerate(SYMBOLS):
        all_candidates.extend(candidates(symbol_index, markets[symbol], feature_map[symbol], config))
    all_candidates = [item for item in all_candidates if lower <= item.signal_ms < upper]
    all_candidates.sort(key=lambda item: (item.signal_ms, -item.score, item.tie, item.symbol_index))
    trades: list[Trade] = []
    free_time, cursor = -1, 0
    while cursor < len(all_candidates):
        signal = all_candidates[cursor].signal_ms
        group_end = cursor + 1
        while group_end < len(all_candidates) and all_candidates[group_end].signal_ms == signal:
            group_end += 1
        if signal >= free_time:
            for item in all_candidates[cursor:group_end]:
                symbol = SYMBOLS[item.symbol_index]
                market = markets[symbol]
                feature = feature_map[symbol]
                entry_bar, timeout_bar = item.bar_index + 1, item.bar_index + 1 + config.hold
                if (
                    timeout_bar >= len(market.times)
                    or market.times[entry_bar] != market.times[item.bar_index] + BAR_MS
                    or market.times[timeout_bar] - market.times[entry_bar] != config.hold * BAR_MS
                ):
                    continue
                entry = float(market.perp_open[entry_bar])
                atr = float(feature.perp_atr[item.bar_index])
                if not math.isfinite(entry) or not math.isfinite(atr) or entry <= 0 or atr <= 0:
                    continue
                distance = max(config.stop_atr * atr, entry * 0.0010)
                if distance > entry * 0.03:
                    continue
                stop = entry - item.side * distance
                exit_bar, exit_price, stopped, valid = timeout_bar, float(market.perp_open[timeout_bar]), False, True
                for bar in range(entry_bar, timeout_bar):
                    open_price = float(market.perp_open[bar])
                    high = float(market.perp_high[bar])
                    low = float(market.perp_low[bar])
                    if not all(math.isfinite(value) for value in (open_price, high, low)):
                        valid = False
                        break
                    if item.side > 0 and low <= stop:
                        exit_bar, exit_price, stopped = bar, (open_price if open_price < stop else stop), True
                        break
                    if item.side < 0 and high >= stop:
                        exit_bar, exit_price, stopped = bar, (open_price if open_price > stop else stop), True
                        break
                if not valid or not math.isfinite(exit_price):
                    continue
                exit_cost = costs.stop_exit if stopped else costs.normal_exit
                net_fraction = item.side * (exit_price / entry - 1) - (
                    costs.entry + exit_cost + costs.funding_buffer
                ) / 10_000
                planned_loss = distance / entry + (
                    costs.entry + costs.stop_exit + costs.funding_buffer
                ) / 10_000
                notional = min(0.01 / planned_loss, 5.0)
                trades.append(Trade(
                    config.config_id,
                    config.family,
                    item.signal_ms,
                    int(market.times[entry_bar]),
                    int(market.times[exit_bar] + BAR_MS),
                    symbol,
                    item.side,
                    item.score,
                    entry,
                    exit_price,
                    stop,
                    stopped,
                    net_fraction * 10_000,
                    net_fraction / planned_loss,
                    planned_loss,
                    notional,
                    net_fraction * notional,
                ))
                free_time = int(market.times[exit_bar] + BAR_MS)
                break
        cursor = group_end
    return trades

def trimmed(values: np.ndarray, fraction: float) -> float | None:
    if not len(values):
        return None
    count = max(1, int(math.ceil(len(values) * fraction)))
    return float(np.sort(values)[:-count].mean()) if len(values) > count else None

def metrics(trades: list[Trade], start: pd.Timestamp, end: pd.Timestamp) -> dict:
    days = pd.date_range(start, end, inclusive="left", freq="D")
    if not trades:
        return {
            "n": 0, "eligible_days": len(days), "trades_per_day": 0.0,
            "mean_net_r": None, "top10pct_removed_mean_r": None,
            "geometric_daily_return": 0.0, "ending_nav_multiple": 1.0,
            "max_drawdown": 0.0, "positive_month_fraction": 0.0,
            "single_trade_positive_profit_share": 1.0,
        }
    frame = pd.DataFrame([asdict(trade) for trade in trades])
    frame["day"] = pd.to_datetime(frame.exit_ms, unit="ms", utc=True).dt.floor("D")
    daily = frame.groupby("day").account_return.apply(
        lambda values: float(np.prod(1 + values.to_numpy()) - 1)
    ).reindex(days, fill_value=0.0)
    equity = np.cumprod(1 + daily.to_numpy())
    drawdown = equity / np.maximum.accumulate(equity) - 1
    monthly = daily.groupby(daily.index.to_period("M")).apply(
        lambda values: float(np.prod(1 + values.to_numpy()) - 1)
    )
    positive = np.maximum(frame.account_return.to_numpy(float), 0)
    positive_sum = float(positive.sum())
    trade_r = frame.net_r.to_numpy(float)
    return {
        "n": len(frame),
        "eligible_days": len(days),
        "trades_per_day": len(frame) / len(days),
        "mean_net_bps": float(frame.net_bps.mean()),
        "mean_net_r": float(trade_r.mean()),
        "top1pct_removed_mean_r": trimmed(trade_r, 0.01),
        "top5pct_removed_mean_r": trimmed(trade_r, 0.05),
        "top10pct_removed_mean_r": trimmed(trade_r, 0.10),
        "top10_removed_mean_r": float(np.sort(trade_r)[:-10].mean()) if len(trade_r) > 10 else None,
        "geometric_daily_return": float(np.expm1(np.log1p(daily).mean())),
        "ending_nav_multiple": float(equity[-1]),
        "max_drawdown": float(drawdown.min()),
        "positive_month_fraction": float((monthly > 0).mean()),
        "stop_rate": float(frame.stopped.mean()),
        "single_trade_positive_profit_share": float(positive.max() / positive_sum) if positive_sum > 0 else 1.0,
        "symbol_contribution": frame.groupby("symbol").account_return.sum().to_dict(),
        "direction_contribution": frame.groupby("side").account_return.sum().to_dict(),
    }

def passes(summary: Mapping, minimum_trades: int = 100, minimum_frequency: float = 0.25) -> bool:
    def value(name: str, default: float = -math.inf) -> float:
        item = summary.get(name)
        return default if item is None else float(item)

    return (
        int(summary.get("n", 0)) >= minimum_trades
        and value("trades_per_day", 0) >= minimum_frequency
        and value("mean_net_r") > 0
        and value("top10pct_removed_mean_r") > 0
        and value("geometric_daily_return") > 0
        and value("positive_month_fraction", 0) >= 0.58
        and value("single_trade_positive_profit_share", 1) <= 0.15
    )

def stage_score(base: Mapping, stress: Mapping) -> float:
    keys = ("mean_net_r", "top10pct_removed_mean_r", "geometric_daily_return")
    values = [base.get(key) for key in keys] + [stress.get(key) for key in keys]
    return -1e9 if any(item is None for item in values) else float(min(float(item) for item in values))
