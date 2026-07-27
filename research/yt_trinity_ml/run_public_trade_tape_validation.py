#!/usr/bin/env python3
"""Validate a frozen coarse authority on chronological Bybit public trades.

This is a fail-closed execution replay.  It consumes the exact scored candidates
saved by the coarse authority and never rebuilds or retunes signals.  Marketable
orders activate after 500 ms and fill from the first chronological trade with a
conservative spread/slippage/observed-volume impact.  Passive entries and targets
require strict trade-through, aggressor-side compatibility, queue depletion and
support partial fills.  Any required archive gap invalidates the account result.
"""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import hashlib
import json
import math
import os
import random
import shutil
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import requests

import run_cisd_bpr_ifvg_research as coarse
from system.core import EventCandidate, RiskConfig, size_position_from_nav


OFFICIAL_START = pd.Timestamp("2024-01-01T00:00:00Z")
OFFICIAL_END = pd.Timestamp("2026-07-01T00:00:00Z")
SYMBOL_RULES = {
    "BTCUSDT": {"quantity_step": 0.001, "minimum_quantity": 0.001, "tick_size": 0.1},
    "ETHUSDT": {"quantity_step": 0.01, "minimum_quantity": 0.01, "tick_size": 0.01},
    "SOLUSDT": {"quantity_step": 0.1, "minimum_quantity": 0.1, "tick_size": 0.001},
    "XRPUSDT": {"quantity_step": 1.0, "minimum_quantity": 1.0, "tick_size": 0.0001},
}
URL_TEMPLATES = (
    "https://public.bybit.com/trading/{symbol}/{symbol}{date}.csv.gz",
    "https://public.bybit.com/trading/{symbol}/{symbol}_{date}.csv.gz",
)


@dataclass(frozen=True)
class FrozenSignal:
    timestamp: pd.Timestamp
    symbol: str
    family: str
    side: int
    decision_price: float
    entry_reference: float
    stop_reference: float
    target_reference: float
    structural_level: float
    feature_row: Mapping[str, float]
    lower_confidence_score: float
    expected_log_growth: float
    expected_net_r: float
    win_probability: float
    chosen_action: str


@dataclass(frozen=True)
class TapeConfig:
    activation_latency_ms: int
    maker_fee_rate: float
    taker_fee_rate: float
    minimum_spread_bps: float
    market_slippage_bps: float
    stop_slippage_bps: float
    passive_entry_queue_multiple: float = 2.0
    passive_target_queue_multiple: float = 1.5
    base_impact_bps: float = 0.75
    impact_bps_per_sqrt_participation: float = 2.5
    maximum_impact_bps: float = 25.0
    maintenance_margin_fraction: float = 0.005
    liquidation_buffer_fraction: float = 0.0025


@dataclass
class PositionEvent:
    timestamp: pd.Timestamp
    symbol: str
    side: int
    delta_quantity: float
    entry_price: float


@dataclass
class CashEvent:
    timestamp: pd.Timestamp
    delta: float
    role: str
    symbol: str | None


@dataclass
class FillEvent:
    timestamp: pd.Timestamp
    symbol: str
    role: str
    side: int
    quantity: float
    price: float
    fee: float
    liquidity: str


@dataclass
class ClosedTrade:
    symbol: str
    family: str
    side: int
    opened_at: pd.Timestamp
    closed_at: pd.Timestamp
    quantity: float
    average_entry_price: float
    exit_reason: str
    net_pnl: float
    account_return: float
    net_r: float


class ArchiveGap(RuntimeError):
    pass


def timestamp(value: Any) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        result = result.tz_localize("UTC")
    else:
        result = result.tz_convert("UTC")
    return result.as_unit("ns")


def canonical_json(value: Any) -> str:
    def convert(item: Any) -> Any:
        if dataclasses.is_dataclass(item):
            return convert(dataclasses.asdict(item))
        if isinstance(item, pd.Timestamp):
            return item.isoformat()
        if isinstance(item, np.generic):
            return item.item()
        if isinstance(item, Mapping):
            return {str(key): convert(val) for key, val in item.items()}
        if isinstance(item, (tuple, list)):
            return [convert(val) for val in item]
        if isinstance(item, float) and not np.isfinite(item):
            return None
        return item
    return json.dumps(convert(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_jsonl(path: Path, rows: Iterable[Any]) -> str:
    raw = "".join(canonical_json(row) + "\n" for row in rows)
    path.write_text(raw, encoding="utf-8")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def find_one(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {name}, found {len(matches)}")
    return matches[0]


def load_signals(path: Path) -> list[FrozenSignal]:
    rows: list[FrozenSignal] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        lower = float(row.get("lower_confidence_score") or -math.inf)
        if not np.isfinite(lower) or lower <= 0:
            continue
        action = str(row.get("chosen_action") or "")
        if action not in {"MARKETABLE", "PASSIVE_RETEST"}:
            continue
        rows.append(
            FrozenSignal(
                timestamp=timestamp(row["timestamp"]),
                symbol=str(row["symbol"]),
                family=str(row["family"]),
                side=int(row["side"]),
                decision_price=float(row["decision_price"]),
                entry_reference=float(row["entry_reference"]),
                stop_reference=float(row["stop_reference"]),
                target_reference=float(row["target_reference"]),
                structural_level=float(row["structural_level"]),
                feature_row={str(key): float(value) for key, value in (row.get("feature_row") or {}).items() if isinstance(value, (int, float)) and np.isfinite(value)},
                lower_confidence_score=lower,
                expected_log_growth=float(row.get("expected_log_growth") or -math.inf),
                expected_net_r=float(row.get("expected_net_r") or 0.0),
                win_probability=float(row.get("win_probability") or 0.0),
                chosen_action=action,
            )
        )
    rows.sort(key=lambda item: (item.timestamp, item.symbol, item.side, item.family, item.entry_reference))
    return rows


def extract_contract(summary: Mapping[str, Any]) -> tuple[float, float, TapeConfig]:
    if isinstance(summary.get("frozen_contract"), Mapping):
        contract = summary["frozen_contract"]
        risk_fraction = float(contract["risk_fraction"])
        maximum_leverage = float(contract["maximum_leverage"])
        execution = summary.get("realistic_execution") or {}
    else:
        risk = summary.get("selected_risk") or {}
        risk_fraction = float(risk["risk_fraction"])
        maximum_leverage = float(risk["maximum_leverage"])
        full = summary.get("official_full_period") or {}
        execution = full.get("realistic_execution") or {}
    config = TapeConfig(
        activation_latency_ms=int(execution.get("activation_latency_ms", 500)),
        maker_fee_rate=float(execution.get("maker_fee_rate", 0.0002)),
        taker_fee_rate=float(execution.get("taker_fee_rate", 0.00055)),
        minimum_spread_bps=float(execution.get("minimum_spread_bps", 0.5)),
        market_slippage_bps=float(execution.get("market_slippage_bps", 2.0)),
        stop_slippage_bps=float(execution.get("stop_slippage_bps", 4.0)),
    )
    return risk_fraction, maximum_leverage, config


def normalize_trade_frame(frame: pd.DataFrame, symbol: str, day: pd.Timestamp) -> pd.DataFrame:
    aliases = {str(column).lower(): column for column in frame.columns}
    def column(*names: str) -> str | None:
        for name in names:
            if name.lower() in aliases:
                return aliases[name.lower()]
        return None
    time_column = column("timestamp", "time", "trade_time", "trade_time_ms", "created_at", "T")
    price_column = column("price", "p")
    size_column = column("size", "qty", "quantity", "volume", "q")
    side_column = column("side", "S", "taker_side")
    sequence_column = column("trade_id", "trdMatchID", "id", "sequence", "seq")
    if not time_column or not price_column or not size_column:
        raise ArchiveGap(f"unrecognized trade columns for {symbol} {day.date()}: {list(frame.columns)}")
    raw_time = frame[time_column]
    numeric = pd.to_numeric(raw_time, errors="coerce")
    if numeric.notna().mean() >= 0.95:
        magnitude = float(numeric.dropna().abs().median()) if numeric.notna().any() else 0.0
        if magnitude >= 1e17:
            unit = "ns"
        elif magnitude >= 1e14:
            unit = "us"
        elif magnitude >= 1e11:
            unit = "ms"
        else:
            unit = "s"
        times = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    else:
        times = pd.to_datetime(raw_time, utc=True, errors="coerce")
    result = pd.DataFrame(
        {
            "timestamp": times,
            "price": pd.to_numeric(frame[price_column], errors="coerce"),
            "size": pd.to_numeric(frame[size_column], errors="coerce"),
            "side": frame[side_column].astype(str).str.lower() if side_column else "",
            "sequence": frame[sequence_column].astype(str) if sequence_column else np.arange(len(frame)).astype(str),
        }
    )
    result = result.dropna(subset=["timestamp", "price", "size"])
    result = result[(result["price"] > 0) & (result["size"] > 0)]
    start = day.floor("D")
    end = start + pd.Timedelta(days=1)
    result = result[(result["timestamp"] >= start) & (result["timestamp"] < end)]
    result = result.sort_values(["timestamp", "sequence"], kind="stable").reset_index(drop=True)
    if result.empty:
        raise ArchiveGap(f"empty normalized trade archive for {symbol} {day.date()}")
    result["timestamp_ns"] = pd.DatetimeIndex(result["timestamp"]).as_unit("ns").asi8
    return result


class TradeArchive:
    def __init__(self, cache_root: Path, memory_days: int = 3) -> None:
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.memory_days = memory_days
        self.memory: OrderedDict[tuple[str, str], pd.DataFrame] = OrderedDict()
        self.session = requests.Session()
        self.download_ledger: list[dict[str, Any]] = []

    def _path(self, symbol: str, day: pd.Timestamp) -> Path:
        directory = self.cache_root / symbol
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{symbol}{day:%Y-%m-%d}.csv.gz"

    def _download(self, symbol: str, day: pd.Timestamp, path: Path) -> None:
        errors: list[str] = []
        for template in URL_TEMPLATES:
            url = template.format(symbol=symbol, date=f"{day:%Y-%m-%d}")
            for attempt in range(1, 4):
                temporary = path.with_suffix(path.suffix + ".partial")
                try:
                    with self.session.get(
                        url,
                        headers={"User-Agent": "SMC-ICT-2-LIVE/1.0"},
                        timeout=90,
                        stream=True,
                        allow_redirects=True,
                    ) as response:
                        if response.status_code == 404:
                            errors.append(f"404 {url}")
                            break
                        if response.status_code == 429:
                            time.sleep(10 * attempt + random.random())
                            continue
                        response.raise_for_status()
                        digest = hashlib.sha256()
                        total = 0
                        with temporary.open("wb") as handle:
                            for chunk in response.iter_content(1024 * 1024):
                                if not chunk:
                                    continue
                                handle.write(chunk)
                                digest.update(chunk)
                                total += len(chunk)
                        if total < 100 or temporary.read_bytes()[:2] != b"\x1f\x8b":
                            raise ArchiveGap(f"invalid gzip payload {url} bytes={total}")
                        temporary.replace(path)
                        self.download_ledger.append({
                            "symbol": symbol,
                            "day": f"{day:%Y-%m-%d}",
                            "url": url,
                            "bytes": total,
                            "sha256": digest.hexdigest(),
                            "cached": False,
                        })
                        return
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc} {url}")
                    try:
                        temporary.unlink()
                    except FileNotFoundError:
                        pass
                    time.sleep(min(20, attempt * 2))
        raise ArchiveGap(f"missing Bybit trade archive {symbol} {day.date()}: {errors[-6:]}")

    def get(self, symbol: str, day: pd.Timestamp) -> pd.DataFrame:
        key = (symbol, f"{day:%Y-%m-%d}")
        if key in self.memory:
            frame = self.memory.pop(key)
            self.memory[key] = frame
            return frame
        path = self._path(symbol, day)
        if not path.exists():
            self._download(symbol, day, path)
        else:
            self.download_ledger.append({
                "symbol": symbol,
                "day": f"{day:%Y-%m-%d}",
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "cached": True,
            })
        try:
            frame = pd.read_csv(path, compression="gzip", low_memory=False)
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise ArchiveGap(f"cannot parse {path}: {type(exc).__name__}: {exc}") from exc
        normalized = normalize_trade_frame(frame, symbol, day)
        self.memory[key] = normalized
        while len(self.memory) > self.memory_days:
            self.memory.popitem(last=False)
        return normalized


def aggressor_compatible(side_value: str, required: str) -> bool:
    value = str(side_value or "").lower()
    if not value or value in {"nan", "none"}:
        return True
    if required == "buy":
        return "buy" in value or value in {"b", "1"}
    return "sell" in value or value in {"s", "-1"}


def impact_bps(quantity: float, observed_size: float, config: TapeConfig) -> float:
    participation = max(quantity / max(observed_size, 1e-12), 0.0)
    return min(
        config.maximum_impact_bps,
        config.base_impact_bps + config.impact_bps_per_sqrt_participation * math.sqrt(participation),
    )


def market_entry_price(signal: FrozenSignal, trade_price: float, trade_size: float, quantity: float, config: TapeConfig) -> float:
    cost_bps = config.minimum_spread_bps / 2 + config.market_slippage_bps + impact_bps(quantity, trade_size, config)
    return trade_price * (1 + signal.side * cost_bps / 10_000)


def stop_exit_price(signal: FrozenSignal, trade_price: float, quantity: float, trade_size: float, config: TapeConfig) -> float:
    extra_bps = config.stop_slippage_bps + impact_bps(quantity, trade_size, config)
    if signal.side > 0:
        return min(signal.stop_reference * (1 - extra_bps / 10_000), trade_price * (1 - extra_bps / 10_000))
    return max(signal.stop_reference * (1 + extra_bps / 10_000), trade_price * (1 + extra_bps / 10_000))


def expected_entry(signal: FrozenSignal, config: TapeConfig) -> float:
    if signal.chosen_action == "PASSIVE_RETEST":
        return signal.entry_reference
    cost_bps = config.minimum_spread_bps / 2 + config.market_slippage_bps + config.base_impact_bps
    return signal.decision_price * (1 + signal.side * cost_bps / 10_000)


def liquidation_price(entry: float, side: int, quantity: float, equity: float, maintenance: float, buffer: float) -> float | None:
    notional = quantity * entry
    if equity <= 0 or notional <= 0:
        return entry
    leverage = notional / equity
    if leverage <= 1:
        return None
    if side > 0:
        return entry * (1 - 1 / leverage + maintenance + buffer)
    return entry * (1 + 1 / leverage - maintenance - buffer)


def qualifying_entry(signal: FrozenSignal, price: float, side_value: str, tick: float) -> bool:
    if signal.side > 0:
        return price <= signal.entry_reference - tick and aggressor_compatible(side_value, "sell")
    return price >= signal.entry_reference + tick and aggressor_compatible(side_value, "buy")


def qualifying_target(signal: FrozenSignal, price: float, side_value: str, tick: float) -> bool:
    if signal.side > 0:
        return price >= signal.target_reference + tick and aggressor_compatible(side_value, "buy")
    return price <= signal.target_reference - tick and aggressor_compatible(side_value, "sell")


def stop_crossed(signal: FrozenSignal, price: float) -> bool:
    return price <= signal.stop_reference if signal.side > 0 else price >= signal.stop_reference


def target_crossed(signal: FrozenSignal, price: float) -> bool:
    return price >= signal.target_reference if signal.side > 0 else price <= signal.target_reference


def mark_asof(frame: pd.DataFrame, value: pd.Timestamp) -> float:
    eligible = frame.loc[frame["bar_start"] < value]
    if eligible.empty:
        eligible = frame.loc[frame.index <= value]
    if eligible.empty:
        raise ArchiveGap(f"no mark available at {value}")
    row = eligible.iloc[-1]
    return float(row.get("mark_close", row["close"]))


def funding_for_position(
    signal: FrozenSignal,
    position_events: Sequence[PositionEvent],
    start: pd.Timestamp,
    end: pd.Timestamp,
    funding: Mapping[tuple[str, pd.Timestamp], float],
    mark_frame: pd.DataFrame,
) -> tuple[list[CashEvent], float]:
    events = sorted(
        (event for event in position_events if start <= event.timestamp <= end),
        key=lambda event: event.timestamp,
    )
    funding_times = sorted(
        (time_value, float(rate))
        for (symbol, time_value), rate in funding.items()
        if symbol == signal.symbol and start <= time_value < end
    )
    output: list[CashEvent] = []
    total = 0.0
    event_index = 0
    quantity = 0.0
    for time_value, rate in funding_times:
        while event_index < len(events) and events[event_index].timestamp <= time_value:
            quantity += events[event_index].delta_quantity
            event_index += 1
        if quantity <= 1e-12:
            continue
        mark = mark_asof(mark_frame, time_value)
        payment = -signal.side * quantity * mark * rate
        total += payment
        output.append(CashEvent(time_value, payment, "FUNDING", signal.symbol))
    return output, total


def resolve_signal(
    signal: FrozenSignal,
    requested_quantity: float,
    starting_cash: float,
    archive: TradeArchive,
    funding: Mapping[tuple[str, pd.Timestamp], float],
    mark_frame: pd.DataFrame,
    config: TapeConfig,
) -> dict[str, Any]:
    activation = signal.timestamp + pd.Timedelta(milliseconds=config.activation_latency_ms)
    rule = SYMBOL_RULES[signal.symbol]
    tick = float(rule["tick_size"])
    entry_queue = requested_quantity * config.passive_entry_queue_multiple
    target_queue: float | None = None
    entry_filled = 0.0
    open_quantity = 0.0
    entry_notional = 0.0
    entry_fees = 0.0
    exit_fees = 0.0
    realized_gross = 0.0
    first_entry_time: pd.Timestamp | None = None
    last_event_time = activation
    cash_events: list[CashEvent] = []
    position_events: list[PositionEvent] = []
    fill_events: list[FillEvent] = []
    exit_reason: str | None = None
    liquidated = False
    day = activation.floor("D")
    cursor = activation

    while day < OFFICIAL_END.floor("D") + pd.Timedelta(days=1):
        trades = archive.get(signal.symbol, day)
        subset = trades.loc[
            (trades["timestamp"] >= cursor)
            & (trades["timestamp"] < min(day + pd.Timedelta(days=1), OFFICIAL_END))
        ]
        for row in subset.itertuples(index=False):
            trade_time = timestamp(row.timestamp)
            price = float(row.price)
            size = float(row.size)
            side_value = str(row.side)
            last_event_time = trade_time

            if signal.chosen_action == "MARKETABLE" and entry_filled <= 0:
                fill_price = market_entry_price(signal, price, size, requested_quantity, config)
                protective = signal.side * (fill_price - signal.stop_reference)
                reward = signal.side * (signal.target_reference - fill_price)
                if protective <= 0 or reward <= 0:
                    return {
                        "status": "CANCELLED_LATENCY_GEOMETRY",
                        "end_time": trade_time,
                        "cash": starting_cash,
                        "cash_events": [],
                        "position_events": [],
                        "fill_events": [],
                        "closed_trade": None,
                        "liquidated": False,
                    }
                fee = requested_quantity * fill_price * config.taker_fee_rate
                entry_filled = requested_quantity
                open_quantity = requested_quantity
                entry_notional = requested_quantity * fill_price
                entry_fees = fee
                first_entry_time = trade_time
                cash_events.append(CashEvent(trade_time, -fee, "ENTRY_FEE", signal.symbol))
                position_events.append(PositionEvent(trade_time, signal.symbol, signal.side, requested_quantity, fill_price))
                fill_events.append(FillEvent(trade_time, signal.symbol, "ENTRY", signal.side, requested_quantity, fill_price, fee, "taker"))

            if signal.chosen_action == "PASSIVE_RETEST" and entry_filled < requested_quantity:
                if entry_filled <= 0 and (stop_crossed(signal, price) or target_crossed(signal, price)):
                    return {
                        "status": "CANCELLED_BEFORE_FILL",
                        "end_time": trade_time,
                        "cash": starting_cash,
                        "cash_events": [],
                        "position_events": [],
                        "fill_events": [],
                        "closed_trade": None,
                        "liquidated": False,
                    }
                if qualifying_entry(signal, price, side_value, tick):
                    volume = size
                    if entry_queue > 0:
                        consumed = min(entry_queue, volume)
                        entry_queue -= consumed
                        volume -= consumed
                    if volume > 0:
                        quantity = min(requested_quantity - entry_filled, volume)
                        if quantity > 0:
                            fill_price = signal.entry_reference
                            fee = quantity * fill_price * config.maker_fee_rate
                            entry_filled += quantity
                            open_quantity += quantity
                            entry_notional += quantity * fill_price
                            entry_fees += fee
                            if first_entry_time is None:
                                first_entry_time = trade_time
                            cash_events.append(CashEvent(trade_time, -fee, "ENTRY_FEE", signal.symbol))
                            position_events.append(PositionEvent(trade_time, signal.symbol, signal.side, quantity, fill_price))
                            fill_events.append(FillEvent(trade_time, signal.symbol, "ENTRY", signal.side, quantity, fill_price, fee, "maker"))

            if open_quantity > 1e-12:
                average_entry = entry_notional / max(entry_filled, 1e-12)
                liq = liquidation_price(
                    average_entry,
                    signal.side,
                    open_quantity,
                    starting_cash,
                    config.maintenance_margin_fraction,
                    config.liquidation_buffer_fraction,
                )
                if liq is not None and ((signal.side > 0 and price <= liq) or (signal.side < 0 and price >= liq)):
                    liquidated = True
                    exit_reason = "LIQUIDATION"
                elif stop_crossed(signal, price):
                    exit_reason = "STOP"
                if exit_reason in {"LIQUIDATION", "STOP"}:
                    fill_price = stop_exit_price(signal, price, open_quantity, size, config)
                    fee = open_quantity * fill_price * config.taker_fee_rate
                    gross = signal.side * open_quantity * (fill_price - average_entry)
                    realized_gross += gross
                    exit_fees += fee
                    cash_events.append(CashEvent(trade_time, gross - fee, exit_reason, signal.symbol))
                    position_events.append(PositionEvent(trade_time, signal.symbol, signal.side, -open_quantity, average_entry))
                    fill_events.append(FillEvent(trade_time, signal.symbol, exit_reason, -signal.side, open_quantity, fill_price, fee, "taker"))
                    open_quantity = 0.0
                    break

                if qualifying_target(signal, price, side_value, tick):
                    if target_queue is None:
                        target_queue = max(open_quantity, requested_quantity) * config.passive_target_queue_multiple
                    volume = size
                    if target_queue > 0:
                        consumed = min(target_queue, volume)
                        target_queue -= consumed
                        volume -= consumed
                    if volume > 0:
                        quantity = min(open_quantity, volume)
                        if quantity > 0:
                            fill_price = signal.target_reference
                            fee = quantity * fill_price * config.maker_fee_rate
                            gross = signal.side * quantity * (fill_price - average_entry)
                            realized_gross += gross
                            exit_fees += fee
                            cash_events.append(CashEvent(trade_time, gross - fee, "TARGET", signal.symbol))
                            position_events.append(PositionEvent(trade_time, signal.symbol, signal.side, -quantity, average_entry))
                            fill_events.append(FillEvent(trade_time, signal.symbol, "TARGET", -signal.side, quantity, fill_price, fee, "maker"))
                            open_quantity -= quantity
                            if open_quantity <= 1e-12:
                                open_quantity = 0.0
                                exit_reason = "TARGET"
                                break
        if exit_reason is not None:
            break
        day += pd.Timedelta(days=1)
        cursor = day
        if day >= OFFICIAL_END:
            break

    if first_entry_time is None:
        return {
            "status": "UNRESOLVED_NO_FILL_AT_EVALUATION_END",
            "end_time": OFFICIAL_END,
            "cash": starting_cash,
            "cash_events": [],
            "position_events": [],
            "fill_events": [],
            "closed_trade": None,
            "liquidated": False,
        }

    end_time = last_event_time if exit_reason is not None else OFFICIAL_END
    funding_events, funding_total = funding_for_position(
        signal,
        position_events,
        first_entry_time,
        end_time,
        funding,
        mark_frame,
    )
    cash_events.extend(funding_events)
    ending_cash = starting_cash + sum(event.delta for event in cash_events)
    average_entry = entry_notional / max(entry_filled, 1e-12)
    closed_trade = None
    if exit_reason is not None:
        net_pnl = ending_cash - starting_cash
        expected = expected_entry(signal, config)
        stop_budget = requested_quantity * abs(expected - signal.stop_reference)
        closed_trade = ClosedTrade(
            symbol=signal.symbol,
            family=signal.family,
            side=signal.side,
            opened_at=first_entry_time,
            closed_at=end_time,
            quantity=entry_filled,
            average_entry_price=average_entry,
            exit_reason=exit_reason,
            net_pnl=net_pnl,
            account_return=net_pnl / max(starting_cash, 1e-12),
            net_r=net_pnl / max(stop_budget, 1e-12),
        )
    return {
        "status": exit_reason or "OPEN_AT_EVALUATION_END",
        "end_time": end_time,
        "cash": ending_cash,
        "cash_events": cash_events,
        "position_events": position_events,
        "fill_events": fill_events,
        "closed_trade": closed_trade,
        "liquidated": liquidated,
        "open_quantity": open_quantity,
        "average_entry_price": average_entry,
        "funding_total": funding_total,
    }


def quantity_for_signal(
    signal: FrozenSignal,
    nav: float,
    risk_fraction: float,
    maximum_leverage: float,
    config: TapeConfig,
) -> float:
    rule = SYMBOL_RULES[signal.symbol]
    expected = expected_entry(signal, config)
    family = type("FrozenFamily", (), {"value": signal.family})()
    candidate = EventCandidate(
        timestamp=signal.timestamp,
        symbol=signal.symbol,
        family=family,  # type: ignore[arg-type]
        side=signal.side,
        decision_price=signal.decision_price,
        entry_reference=expected,
        stop_reference=signal.stop_reference,
        target_reference=signal.target_reference,
        structural_level=signal.structural_level,
        feature_row=signal.feature_row,
    )
    risk = RiskConfig(
        risk_fraction=risk_fraction,
        maximum_leverage=maximum_leverage,
        quantity_step=float(rule["quantity_step"]),
        minimum_quantity=float(rule["minimum_quantity"]),
        maintenance_margin_fraction=config.maintenance_margin_fraction,
        liquidation_buffer_fraction=config.liquidation_buffer_fraction,
    )
    entry_fee = config.maker_fee_rate if signal.chosen_action == "PASSIVE_RETEST" else config.taker_fee_rate
    return size_position_from_nav(
        nav,
        candidate,
        risk,
        entry_fee_rate=entry_fee,
        stop_fee_rate=config.taker_fee_rate,
        entry_slippage_fraction=(0.0 if signal.chosen_action == "PASSIVE_RETEST" else (config.minimum_spread_bps / 2 + config.market_slippage_bps + config.base_impact_bps) / 10_000),
        stop_slippage_fraction=(config.stop_slippage_bps + config.base_impact_bps) / 10_000,
    )


def day_end_nav(
    initial_cash: float,
    cash_events: Sequence[CashEvent],
    position_events: Sequence[PositionEvent],
    mark_frames: Mapping[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    cash_rows = sorted(cash_events, key=lambda event: event.timestamp)
    position_rows = sorted(position_events, key=lambda event: event.timestamp)
    cash_index = 0
    position_index = 0
    cash = initial_cash
    active_symbol: str | None = None
    active_side = 0
    quantity = 0.0
    entry_price = 0.0
    output: list[dict[str, Any]] = []
    for day_end in pd.date_range(OFFICIAL_START + pd.Timedelta(days=1), OFFICIAL_END, freq="1D"):
        while cash_index < len(cash_rows) and cash_rows[cash_index].timestamp <= day_end:
            cash += cash_rows[cash_index].delta
            cash_index += 1
        while position_index < len(position_rows) and position_rows[position_index].timestamp <= day_end:
            event = position_rows[position_index]
            if event.delta_quantity > 0:
                if quantity <= 1e-12:
                    active_symbol = event.symbol
                    active_side = event.side
                    entry_price = event.entry_price
                quantity += event.delta_quantity
            else:
                quantity += event.delta_quantity
                if quantity <= 1e-12:
                    quantity = 0.0
                    active_symbol = None
                    active_side = 0
                    entry_price = 0.0
            position_index += 1
        unrealized = 0.0
        if active_symbol is not None and quantity > 0:
            mark = mark_asof(mark_frames[active_symbol], day_end)
            unrealized = active_side * quantity * (mark - entry_price)
        output.append({
            "timestamp": day_end,
            "nav": cash + unrealized,
            "cash": cash,
            "unrealized_pnl": unrealized,
            "symbol": active_symbol,
            "quantity": quantity,
        })
    return output


def account_metrics(daily_nav: Sequence[Mapping[str, Any]], trades: Sequence[ClosedTrade], invalid: bool) -> dict[str, Any]:
    values = np.asarray([10_000.0, *[float(row["nav"]) for row in daily_nav]], dtype=float)
    end_nav = float(values[-1]) if len(values) else 10_000.0
    calendar_days = int((OFFICIAL_END - OFFICIAL_START) / pd.Timedelta(days=1))
    growth = math.exp(math.log(end_nav / 10_000.0) / calendar_days) - 1 if end_nav > 0 and not invalid else -1.0
    peaks = np.maximum.accumulate(values)
    drawdown = 1.0 - values / np.where(peaks > 0, peaks, np.nan)
    pnl = np.asarray([trade.net_pnl for trade in trades], dtype=float)
    returns = np.asarray([trade.account_return for trade in trades], dtype=float)
    positive = pnl[pnl > 0]
    negative = pnl[pnl < 0]
    profit_factor = float(positive.sum() / abs(negative.sum())) if negative.size else (math.inf if positive.size else 0.0)
    top_five = float(np.sort(positive)[-5:].sum() / positive.sum()) if positive.sum() > 0 else 0.0
    winner_removed_nav = end_nav - (float(positive.max()) if positive.size else 0.0)
    winner_removed_return = winner_removed_nav / 10_000.0 - 1
    return {
        "start_nav": 10_000.0,
        "end_nav": end_nav,
        "account_multiple": end_nav / 10_000.0,
        "total_return": end_nav / 10_000.0 - 1,
        "calendar_days": calendar_days,
        "geometric_daily_growth": growth,
        "maximum_drawdown": float(np.nanmax(drawdown)) if drawdown.size else 0.0,
        "completed_trades": len(trades),
        "win_rate": float((pnl > 0).mean()) if pnl.size else 0.0,
        "profit_factor": profit_factor,
        "median_trade_return": float(np.median(returns)) if returns.size else 0.0,
        "top_five_positive_pnl_share": top_five,
        "winner_removal_return": winner_removed_return,
        "liquidated_or_invalid": invalid,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    summary_path = find_one(args.source, "RUN_SUMMARY.json")
    signal_path = find_one(args.source, "SCORED_CANDIDATES.jsonl")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    signals = load_signals(signal_path)
    risk_fraction, maximum_leverage, config = extract_contract(summary)
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    mark_frames: dict[str, pd.DataFrame] = {}
    funding: dict[tuple[str, pd.Timestamp], float] = {}
    symbols = sorted({signal.symbol for signal in signals})
    for symbol in symbols:
        mark_frames[symbol] = coarse.fetch_minute_klines(symbol, OFFICIAL_START, OFFICIAL_END, args.cache_dir / "marks")
        funding.update(coarse.fetch_funding(symbol, OFFICIAL_START, OFFICIAL_END, args.cache_dir / "funding"))
    archive = TradeArchive(args.cache_dir / "trades")
    grouped: dict[pd.Timestamp, list[FrozenSignal]] = defaultdict(list)
    for signal in signals:
        if OFFICIAL_START <= signal.timestamp < OFFICIAL_END:
            grouped[signal.timestamp].append(signal)

    cash = 10_000.0
    slot_release = OFFICIAL_START
    cash_events: list[CashEvent] = []
    position_events: list[PositionEvent] = []
    fills: list[FillEvent] = []
    closed_trades: list[ClosedTrade] = []
    outcomes: list[dict[str, Any]] = []
    invalid = False
    source_error: str | None = None
    processed_groups = 0
    for decision_time in sorted(grouped):
        if decision_time < slot_release or invalid:
            continue
        selected = max(
            grouped[decision_time],
            key=lambda signal: (
                signal.lower_confidence_score,
                signal.expected_log_growth,
                signal.expected_net_r,
                signal.symbol,
            ),
        )
        quantity = quantity_for_signal(selected, cash, risk_fraction, maximum_leverage, config)
        if quantity <= 0:
            outcomes.append({
                "timestamp": decision_time,
                "symbol": selected.symbol,
                "family": selected.family,
                "status": "ZERO_QUANTITY",
            })
            continue
        try:
            resolved = resolve_signal(
                selected,
                quantity,
                cash,
                archive,
                funding,
                mark_frames[selected.symbol],
                config,
            )
        except ArchiveGap as exc:
            invalid = True
            source_error = str(exc)
            break
        cash = float(resolved["cash"])
        cash_events.extend(resolved["cash_events"])
        position_events.extend(resolved["position_events"])
        fills.extend(resolved["fill_events"])
        if resolved["closed_trade"] is not None:
            closed_trades.append(resolved["closed_trade"])
        invalid = invalid or bool(resolved.get("liquidated")) or cash <= 0
        slot_release = min(timestamp(resolved["end_time"]), OFFICIAL_END)
        outcomes.append({
            "timestamp": decision_time,
            "symbol": selected.symbol,
            "family": selected.family,
            "side": selected.side,
            "chosen_action": selected.chosen_action,
            "requested_quantity": quantity,
            "status": resolved["status"],
            "end_time": resolved["end_time"],
            "ending_cash": cash,
            "funding_total": resolved.get("funding_total", 0.0),
            "fill_count": len(resolved["fill_events"]),
        })
        processed_groups += 1
        if processed_groups % 10 == 0:
            checkpoint = {
                "processed_groups": processed_groups,
                "decision_time": decision_time,
                "cash": cash,
                "slot_release": slot_release,
                "closed_trades": len(closed_trades),
                "downloaded_days": len(archive.download_ledger),
                "invalid": invalid,
            }
            (args.output / "CHECKPOINT.json").write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
            print(json.dumps(checkpoint, ensure_ascii=False, default=str), flush=True)

    daily = day_end_nav(10_000.0, cash_events, position_events, mark_frames)
    metrics = account_metrics(daily, closed_trades, invalid)
    signal_sha = hashlib.sha256(signal_path.read_bytes()).hexdigest()
    daily_sha = write_jsonl(args.output / "DAILY_NAV.jsonl", daily)
    trade_sha = write_jsonl(args.output / "CLOSED_TRADES.jsonl", closed_trades)
    fill_sha = write_jsonl(args.output / "FILLS.jsonl", fills)
    outcome_sha = write_jsonl(args.output / "OUTCOMES.jsonl", outcomes)
    download_sha = write_jsonl(args.output / "TRADE_ARCHIVE_LEDGER.jsonl", archive.download_ledger)
    if source_error:
        decision = "EVENT_TAPE_DATA_INCOMPLETE_INVALID"
    elif invalid:
        decision = "EVENT_TAPE_LIQUIDATION_OR_ACCOUNT_INVALID"
    elif float(metrics["geometric_daily_growth"]) >= 0.01:
        decision = "TARGET_EXCEEDED_PUBLIC_TRADE_TAPE_PENDING_QUOTE_STRESS"
    elif float(metrics["geometric_daily_growth"]) > 0:
        decision = "POSITIVE_PUBLIC_TRADE_TAPE_BELOW_TARGET"
    else:
        decision = "PUBLIC_TRADE_TAPE_ECONOMIC_FAIL"
    result = {
        "schema_version": 1,
        "stage": "FULL_2024_2026_PUBLIC_TRADE_TAPE_NOT_YET_QUOTE_RANKABLE",
        "source_summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "source_scored_candidates_sha256": signal_sha,
        "source_strategy_id": summary.get("strategy_id"),
        "source_route_key": summary.get("route_key", "pooled_trinity"),
        "frozen_risk_fraction": risk_fraction,
        "frozen_maximum_leverage": maximum_leverage,
        "tape_config": dataclasses.asdict(config),
        "positive_scored_candidate_count": len(signals),
        "processed_entry_groups": processed_groups,
        "metrics": metrics,
        "source_error": source_error,
        "decision": decision,
        "rankable": False,
        "rankability_blockers": [
            "historical best-bid/ask and displayed depth are not yet bound; trades infer aggressor-compatible execution conservatively",
            "complete three-channel content corpus and audited ontology binding remains required",
        ],
        "evidence": {
            "daily_nav_sha256": daily_sha,
            "closed_trades_sha256": trade_sha,
            "fills_sha256": fill_sha,
            "outcomes_sha256": outcome_sha,
            "trade_archive_ledger_sha256": download_sha,
            "daily_nav_rows": len(daily),
            "closed_trade_rows": len(closed_trades),
            "fill_rows": len(fills),
            "outcome_rows": len(outcomes),
            "archive_days": len(archive.download_ledger),
        },
    }
    path = args.output / "RUN_SUMMARY.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (args.output / "RUN_SUMMARY.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  RUN_SUMMARY.json\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
