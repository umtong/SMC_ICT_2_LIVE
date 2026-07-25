from __future__ import annotations

import csv
import gzip
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

import cross_venue_pilot as v1
import cross_venue_pilot_v2 as v2
import cross_venue_development_v2 as d2

CAUSAL_VERSION = 5
BUCKET_US = v1.BUCKET_MS * 1_000
MAX_QUOTE_AGE_BUCKETS = v1.MAX_QUOTE_AGE_MS // v1.BUCKET_MS
_ORIGINAL_V2_PATCH = v2.patch_v1
_PATCHED = False


@dataclass(frozen=True, slots=True)
class EntryCandidateV5:
    event: v1.Event
    key: tuple[str, str]
    entry_position: int
    entry_us: int


@dataclass(frozen=True, slots=True)
class ExitResolutionV5:
    exit_position: int
    exit_us: int
    exit_price: float
    exit_reason: str
    exit_liquidity_overrun: bool
    trigger_boundary_us: int
    maximum_intratrade_drawdown: float
    maximum_path_drawdown: float


@dataclass(frozen=True, slots=True)
class FixedTradeV5:
    config_id: str
    day: str
    symbol: str
    family: str
    decision_ms: int
    entry_ms: int
    exit_ms: int
    entry_us: int
    exit_us: int
    side: int
    entry_price: float
    exit_price: float
    gross_bps: float
    spread_bps: float
    fee_bps_per_side: float
    net_bps: float
    exit_reason: str
    score: float
    exit_liquidity_overrun: bool
    trigger_boundary_us: int


@dataclass(frozen=True, slots=True)
class AccountTradeV5:
    config_id: str
    day: str
    symbol: str
    family: str
    decision_ms: int
    entry_ms: int
    exit_ms: int
    entry_us: int
    exit_us: int
    side: int
    entry_price: float
    exit_price: float
    stop_price: float
    quantity: float
    notional: float
    leverage: float
    gross_pnl: float
    fees: float
    net_pnl: float
    account_return: float
    nav_before: float
    nav_after: float
    exit_reason: str
    score: float
    exit_liquidity_overrun: bool
    maximum_intratrade_drawdown: float
    trigger_boundary_us: int


def timestamp_us(raw: str) -> int:
    value = int(raw)
    if value >= 10**17:  # nanoseconds
        return value // 1_000
    if value >= 10**14:  # microseconds
        return value
    if value >= 10**11:  # milliseconds
        return value * 1_000
    return value * 1_000_000


def _valid_quote(row: dict[str, str]) -> tuple[float, float, float, float] | None:
    ask = float(row["ask_price"])
    ask_amount = float(row["ask_amount"])
    bid = float(row["bid_price"])
    bid_amount = float(row["bid_amount"])
    values = (bid, bid_amount, ask, ask_amount)
    if not all(math.isfinite(value) for value in values):
        return None
    if ask <= bid or bid <= 0 or min(ask_amount, bid_amount) <= 0:
        return None
    return values


def _same_quote(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    return left == right


def _min_bid_row(group: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return min(group, key=lambda item: (item[0], -item[2], item[1], item[3]))


def _max_ask_row(group: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return max(group, key=lambda item: (item[2], -item[0], -item[3], -item[1]))


def _new_bucket(bucket_us: int) -> dict:
    return {
        "bucket_us": bucket_us,
        "first_event_us": None,
        "first_min_bid_row": None,
        "first_max_ask_row": None,
        "last_signal_us": None,
        "last_signal_row": None,
        "low_bid_row": None,
        "high_ask_row": None,
        "quote_count": 0,
        "ambiguous_group_count": 0,
    }


def _update_extrema(accumulator: dict, quote: tuple[float, float, float, float]) -> None:
    low = accumulator["low_bid_row"]
    if low is None or (quote[0], -quote[2], quote[1], quote[3]) < (low[0], -low[2], low[1], low[3]):
        accumulator["low_bid_row"] = quote
    high = accumulator["high_ask_row"]
    if high is None or (quote[2], -quote[0], -quote[3], -quote[1]) > (high[2], -high[0], -high[3], -high[1]):
        accumulator["high_ask_row"] = quote
    accumulator["quote_count"] += 1


def _commit_group(accumulator: dict, local_us: int, group: list[tuple[float, float, float, float]]) -> None:
    if not group:
        return
    if accumulator["first_event_us"] is None:
        accumulator["first_event_us"] = local_us
        accumulator["first_min_bid_row"] = _min_bid_row(group)
        accumulator["first_max_ask_row"] = _max_ask_row(group)
    first = group[0]
    if all(_same_quote(first, item) for item in group[1:]):
        accumulator["last_signal_us"] = local_us
        accumulator["last_signal_row"] = first
    else:
        accumulator["ambiguous_group_count"] += 1


def _quote_fields(prefix: str, quote: tuple[float, float, float, float] | None) -> dict[str, float]:
    if quote is None:
        return {
            f"{prefix}_bid": np.nan,
            f"{prefix}_bid_amount": np.nan,
            f"{prefix}_ask": np.nan,
            f"{prefix}_ask_amount": np.nan,
        }
    bid, bid_amount, ask, ask_amount = quote
    return {
        f"{prefix}_bid": bid,
        f"{prefix}_bid_amount": bid_amount,
        f"{prefix}_ask": ask,
        f"{prefix}_ask_amount": ask_amount,
    }


def _finalize_bucket(accumulator: dict) -> dict:
    first_bid = accumulator["first_min_bid_row"]
    first_ask = accumulator["first_max_ask_row"]
    low_bid = accumulator["low_bid_row"]
    high_ask = accumulator["high_ask_row"]
    signal = accumulator["last_signal_row"]
    row = {
        "bucket_ms": accumulator["bucket_us"] // 1_000,
        "quote_event_us": accumulator["last_signal_us"],
        "quote_event_ms": None if accumulator["last_signal_us"] is None else accumulator["last_signal_us"] // 1_000,
        "first_event_us": accumulator["first_event_us"],
        "first_event_ms": None if accumulator["first_event_us"] is None else accumulator["first_event_us"] // 1_000,
        "quote_count": accumulator["quote_count"],
        "ambiguous_group_count": accumulator["ambiguous_group_count"],
        **_quote_fields("", signal),
    }
    # Remove the leading underscore produced by the generic helper.
    row.update({key[1:] if key.startswith("_") else key: value for key, value in list(row.items()) if key.startswith("_")})
    for key in [key for key in list(row) if key.startswith("_")]:
        del row[key]
    if first_bid is not None:
        row.update({
            "first_bid": first_bid[0],
            "first_bid_amount": first_bid[1],
            "first_bid_ask": first_bid[2],
            "first_bid_ask_amount": first_bid[3],
        })
    if first_ask is not None:
        row.update({
            "first_ask_bid": first_ask[0],
            "first_ask_bid_amount": first_ask[1],
            "first_ask": first_ask[2],
            "first_ask_amount": first_ask[3],
        })
    if low_bid is not None:
        row.update({
            "low_bid": low_bid[0],
            "low_bid_amount": low_bid[1],
            "low_bid_ask": low_bid[2],
            "low_bid_ask_amount": low_bid[3],
        })
    if high_ask is not None:
        row.update({
            "high_ask_bid": high_ask[0],
            "high_ask_bid_amount": high_ask[1],
            "high_ask": high_ask[2],
            "high_ask_amount": high_ask[3],
        })
    return row


def read_quotes_v5(path: Path) -> pd.DataFrame:
    output: list[dict] = []
    delays_us: list[int] = []
    previous_local_us: int | None = None
    previous_exchange_us: int | None = None
    local_monotonic = True
    exchange_monotonic = True
    current_bucket_us: int | None = None
    current_group_us: int | None = None
    current_group: list[tuple[float, float, float, float]] = []
    accumulator: dict | None = None

    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "local_timestamp", "ask_price", "ask_amount", "bid_price", "bid_amount"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"quote schema missing {sorted(missing)}")
        for raw in reader:
            exchange_us = timestamp_us(raw["timestamp"])
            local_us = timestamp_us(raw["local_timestamp"])
            if previous_local_us is not None and local_us < previous_local_us:
                local_monotonic = False
            if previous_exchange_us is not None and exchange_us < previous_exchange_us:
                exchange_monotonic = False
            previous_local_us, previous_exchange_us = local_us, exchange_us
            delays_us.append(local_us - exchange_us)
            quote = _valid_quote(raw)
            if quote is None:
                continue
            bucket_us = local_us // BUCKET_US * BUCKET_US
            if current_bucket_us is None:
                current_bucket_us = bucket_us
                current_group_us = local_us
                accumulator = _new_bucket(bucket_us)
            elif bucket_us != current_bucket_us:
                assert accumulator is not None and current_group_us is not None
                _commit_group(accumulator, current_group_us, current_group)
                output.append(_finalize_bucket(accumulator))
                current_bucket_us = bucket_us
                current_group_us = local_us
                current_group = []
                accumulator = _new_bucket(bucket_us)
            elif local_us != current_group_us:
                assert accumulator is not None and current_group_us is not None
                _commit_group(accumulator, current_group_us, current_group)
                current_group_us = local_us
                current_group = []
            assert accumulator is not None
            _update_extrema(accumulator, quote)
            current_group.append(quote)

    if not local_monotonic:
        raise ValueError(f"local_timestamp is not monotonic in {path}")
    if accumulator is not None and current_group_us is not None:
        _commit_group(accumulator, current_group_us, current_group)
        output.append(_finalize_bucket(accumulator))
    if not output:
        raise ValueError(f"no valid quotes in {path}")

    delays = np.asarray(delays_us, dtype=np.int64)
    v2.LATENCY_DIAGNOSTICS.append({
        "path": str(path),
        "rows": int(len(delays)),
        "local_timestamp_monotonic": local_monotonic,
        "exchange_timestamp_monotonic": exchange_monotonic,
        "negative_exchange_to_local_latency_count": int((delays < 0).sum()),
        "exchange_to_local_latency_ms_median": float(np.median(delays) / 1_000.0) if len(delays) else None,
        "exchange_to_local_latency_ms_p95": float(np.quantile(delays, 0.95) / 1_000.0) if len(delays) else None,
        "exchange_to_local_latency_ms_max": float(delays.max() / 1_000.0) if len(delays) else None,
        "availability_precision": "microsecond",
    })
    return pd.DataFrame(output).sort_values("bucket_ms").set_index("bucket_ms")


def align_v5(
    binance_trades: pd.DataFrame,
    binance_quotes: pd.DataFrame,
    bybit_trades: pd.DataFrame,
    bybit_quotes: pd.DataFrame,
) -> pd.DataFrame:
    start = max(item.index.min() for item in (binance_trades, binance_quotes, bybit_trades, bybit_quotes))
    end = min(item.index.max() for item in (binance_trades, binance_quotes, bybit_trades, bybit_quotes))
    grid = np.arange(start, end + v1.BUCKET_MS, v1.BUCKET_MS, dtype=np.int64)
    out = pd.DataFrame(index=grid)
    execution_columns = [
        "first_event_us", "first_event_ms",
        "first_bid", "first_bid_amount", "first_bid_ask", "first_bid_ask_amount",
        "first_ask", "first_ask_amount", "first_ask_bid", "first_ask_bid_amount",
        "low_bid", "low_bid_amount", "low_bid_ask", "low_bid_ask_amount",
        "high_ask", "high_ask_amount", "high_ask_bid", "high_ask_bid_amount",
        "quote_count", "ambiguous_group_count",
    ]
    for prefix, trades, quotes in (("bn", binance_trades, binance_quotes), ("bb", bybit_trades, bybit_quotes)):
        trade = trades.reindex(grid)
        out[f"{prefix}_trade_notional"] = trade.trade_notional.fillna(0.0)
        out[f"{prefix}_signed_notional"] = trade.signed_notional.fillna(0.0)
        out[f"{prefix}_trade_count"] = trade.trade_count.fillna(0.0)

        quote = quotes.reindex(grid)
        actual = quote.first_event_us.copy()
        signal = quote[["bid", "bid_amount", "ask", "ask_amount", "quote_event_ms", "quote_event_us"]].ffill(limit=MAX_QUOTE_AGE_BUCKETS)
        for name in signal.columns:
            out[f"{prefix}_{name}"] = signal[name]
        out[f"{prefix}_quote_actual"] = actual.notna()
        for name in execution_columns:
            if name in quote:
                out[f"{prefix}_{name}"] = quote[name]
        out[f"{prefix}_mid"] = (out[f"{prefix}_bid"] + out[f"{prefix}_ask"]) / 2.0
        out[f"{prefix}_spread"] = out[f"{prefix}_ask"] - out[f"{prefix}_bid"]
        denominator = out[f"{prefix}_bid_amount"] + out[f"{prefix}_ask_amount"]
        out[f"{prefix}_quote_imbalance"] = (
            out[f"{prefix}_bid_amount"] - out[f"{prefix}_ask_amount"]
        ) / denominator.replace(0, np.nan)
    return out


def patch_v5() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _ORIGINAL_V2_PATCH()
    v1.read_quotes = read_quotes_v5
    v1.align = align_v5
    v2.patch_v1 = patch_v5
    _PATCHED = True


def _quote_from_first(row: pd.Series, side: int, entering: bool) -> dict[str, float] | None:
    use_ask_row = (entering and side > 0) or ((not entering) and side < 0)
    if use_ask_row:
        values = {
            "bid": row.get("bn_first_ask_bid"),
            "bid_amount": row.get("bn_first_ask_bid_amount"),
            "ask": row.get("bn_first_ask"),
            "ask_amount": row.get("bn_first_ask_amount"),
        }
    else:
        values = {
            "bid": row.get("bn_first_bid"),
            "bid_amount": row.get("bn_first_bid_amount"),
            "ask": row.get("bn_first_bid_ask"),
            "ask_amount": row.get("bn_first_bid_ask_amount"),
        }
    if not all(value is not None and math.isfinite(float(value)) for value in values.values()):
        return None
    result = {key: float(value) for key, value in values.items()}
    if result["ask"] <= result["bid"] or min(result["bid_amount"], result["ask_amount"]) <= 0:
        return None
    return result


def _quote_from_bucket_extreme(row: pd.Series, side: int) -> dict[str, float] | None:
    if side > 0:
        values = {
            "bid": row.get("bn_low_bid"),
            "bid_amount": row.get("bn_low_bid_amount"),
            "ask": row.get("bn_low_bid_ask"),
            "ask_amount": row.get("bn_low_bid_ask_amount"),
        }
    else:
        values = {
            "bid": row.get("bn_high_ask_bid"),
            "bid_amount": row.get("bn_high_ask_bid_amount"),
            "ask": row.get("bn_high_ask"),
            "ask_amount": row.get("bn_high_ask_amount"),
        }
    if not all(value is not None and math.isfinite(float(value)) for value in values.values()):
        return None
    result = {key: float(value) for key, value in values.items()}
    if result["ask"] <= result["bid"] or min(result["bid_amount"], result["ask_amount"]) <= 0:
        return None
    return result


def _entry_fill(quote: dict[str, float], side: int, quantity: float) -> tuple[float, float] | None:
    reference = quote["ask"] if side > 0 else quote["bid"]
    available = quote["ask_amount"] if side > 0 else quote["bid_amount"]
    if quantity <= 0 or quantity > d2.MAX_TOP_QUOTE_PARTICIPATION * available + 1e-12:
        return None
    spread = quote["ask"] - quote["bid"]
    participation = quantity / available
    normalized = participation / d2.MAX_TOP_QUOTE_PARTICIPATION
    impact = spread * 0.25 * max(normalized, 0.0)
    return reference + side * impact, spread


def _mandatory_exit(quote: dict[str, float], side: int, quantity: float) -> tuple[float, bool]:
    reference = quote["bid"] if side > 0 else quote["ask"]
    available = quote["bid_amount"] if side > 0 else quote["ask_amount"]
    spread = quote["ask"] - quote["bid"]
    if quantity <= 0 or reference <= 0 or available <= 0 or spread <= 0:
        raise ValueError("unusable V5 exit quote")
    participation = quantity / available
    normalized = participation / d2.MAX_TOP_QUOTE_PARTICIPATION
    impact_spreads = 0.25 * min(normalized, 1.0) + 2.0 * max(normalized - 1.0, 0.0)
    impact = spread * impact_spreads
    if side > 0:
        price = max(reference * 0.10, reference - impact)
    else:
        price = reference + impact
    return price, participation > d2.MAX_TOP_QUOTE_PARTICIPATION


def _size_position(
    quote: dict[str, float],
    side: int,
    stop_mid: float,
    nav: float,
    fee_bps: float,
) -> tuple[float, float, float] | None:
    reference = quote["ask"] if side > 0 else quote["bid"]
    available = quote["ask_amount"] if side > 0 else quote["bid_amount"]
    spread = quote["ask"] - quote["bid"]
    max_quantity = min(d2.MAX_LEVERAGE * nav / reference, d2.MAX_TOP_QUOTE_PARTICIPATION * available)
    if max_quantity <= 0:
        return None
    quantity = max_quantity
    for _ in range(6):
        filled = _entry_fill(quote, side, quantity)
        if filled is None:
            return None
        entry_price = filled[0]
        participation = quantity / available
        stop_impact = spread * (0.5 + 0.25 * max(participation / d2.MAX_TOP_QUOTE_PARTICIPATION, 0.0))
        stop_execution = stop_mid - side * stop_impact
        unit_loss = abs(entry_price - stop_execution) + (entry_price + abs(stop_execution)) * fee_bps / 10_000.0
        if not math.isfinite(unit_loss) or unit_loss <= 0:
            return None
        risk_quantity = nav * d2.RISK_FRACTION / unit_loss
        updated = min(max_quantity, risk_quantity)
        if abs(updated - quantity) <= max(1e-12, 1e-6 * quantity):
            quantity = updated
            break
        quantity = updated
    filled = _entry_fill(quote, side, quantity)
    if filled is None or quantity <= 0:
        return None
    entry_price = filled[0]
    leverage = quantity * entry_price / nav
    planned_loss = quantity * (
        abs(entry_price - stop_mid)
        + (entry_price + abs(stop_mid)) * fee_bps / 10_000.0
        + spread
    )
    if planned_loss > nav * d2.RISK_FRACTION * 1.05 or leverage > d2.MAX_LEVERAGE + 1e-9:
        return None
    return quantity, entry_price, leverage


def _first_quote_index(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    raw = pd.to_numeric(frame["bn_first_event_us"], errors="coerce").to_numpy(float)
    positions = np.flatnonzero(np.isfinite(raw))
    times = raw[positions].astype(np.int64)
    if len(times) and np.any(np.diff(times) < 0):
        raise ValueError("Binance first local-arrival quote times are not monotonic")
    return positions, times


def _first_quote_after(frame: pd.DataFrame, target_us: int) -> tuple[int, int] | None:
    positions, times = _first_quote_index(frame)
    offset = int(np.searchsorted(times, target_us, side="left"))
    if offset >= len(times):
        return None
    return int(positions[offset]), int(times[offset])


def _prepare_basis(frame: pd.DataFrame) -> None:
    if "_v5_basis" in frame.columns:
        return
    basis = np.log(frame.bb_mid) - np.log(frame.bn_mid)
    frame["_v5_basis"] = basis
    frame["_v5_basis_median"] = basis.shift(1).rolling(600, min_periods=300).median()


def _entry_candidates(
    frames: dict[tuple[str, str], pd.DataFrame],
    events: Iterable[v1.Event],
    config: v1.Config,
) -> list[EntryCandidateV5]:
    candidates: list[EntryCandidateV5] = []
    for event in events:
        key = (event.day, event.symbol)
        frame = frames.get(key)
        if frame is None or frame.empty:
            continue
        target_us = (event.decision_ms + config.latency_ms) * 1_000
        found = _first_quote_after(frame, target_us)
        if found is None:
            continue
        position, entry_us = found
        fixed_end_us = (int(frame.index.max()) + v1.BUCKET_MS) * 1_000
        required_end_us = entry_us + config.hold_ms * 1_000 + config.latency_ms * 1_000 + 2 * BUCKET_US
        if required_end_us > fixed_end_us:
            continue
        candidates.append(EntryCandidateV5(event, key, position, entry_us))
    candidates.sort(
        key=lambda item: (
            item.entry_us,
            -item.event.score,
            item.event.decision_ms,
            item.event.symbol,
            item.event.family,
        )
    )
    return candidates


def _drawdown(mark_nav: float, peak: float) -> float:
    if not math.isfinite(mark_nav):
        return 1.0
    return min(1.0, max(0.0, 1.0 - mark_nav / max(peak, 1e-12)))


def _resolve_exit(
    frame: pd.DataFrame,
    candidate: EntryCandidateV5,
    config: v1.Config,
    quantity: float,
    entry_price: float,
    stop_mid: float,
    fee_bps: float,
    nav: float,
    account_peak: float,
) -> ExitResolutionV5:
    _prepare_basis(frame)
    event = candidate.event
    entry_position = candidate.entry_position
    entry_us = candidate.entry_us
    entry_fee = quantity * entry_price * fee_bps / 10_000.0
    horizon_us = entry_us + config.hold_ms * 1_000
    horizon_boundary_us = ((horizon_us + BUCKET_US - 1) // BUCKET_US) * BUCKET_US
    trigger_position: int | None = None
    trigger_boundary_us: int | None = None
    reason: str | None = None
    maximum_intratrade_drawdown = 0.0
    maximum_path_drawdown = 0.0

    def mark_position(position: int) -> None:
        nonlocal maximum_intratrade_drawdown, maximum_path_drawdown
        quote = _quote_from_bucket_extreme(frame.iloc[position], event.side)
        if quote is None:
            return
        mark_price, _ = _mandatory_exit(quote, event.side, quantity)
        mark_fee = quantity * mark_price * fee_bps / 10_000.0
        mark_nav = nav + event.side * quantity * (mark_price - entry_price) - entry_fee - mark_fee
        maximum_intratrade_drawdown = max(maximum_intratrade_drawdown, _drawdown(mark_nav, nav))
        maximum_path_drawdown = max(maximum_path_drawdown, _drawdown(mark_nav, account_peak))

    for position in range(entry_position, len(frame)):
        row = frame.iloc[position]
        bucket_end_us = (int(frame.index[position]) + v1.BUCKET_MS) * 1_000
        mark_position(position)
        if event.side > 0:
            adverse = row.get("bn_low_bid")
            stop_hit = adverse is not None and math.isfinite(float(adverse)) and float(adverse) <= stop_mid
        else:
            adverse = row.get("bn_high_ask")
            stop_hit = adverse is not None and math.isfinite(float(adverse)) and float(adverse) >= stop_mid

        convergence = False
        if position > entry_position and not stop_hit and horizon_boundary_us > bucket_end_us:
            basis = row.get("_v5_basis")
            median = row.get("_v5_basis_median")
            if basis is not None and median is not None and math.isfinite(float(basis)) and math.isfinite(float(median)):
                residual = float(basis) - float(median)
                initial_gap = abs(event.initial_basis_residual)
                convergence = initial_gap > 0 and abs(residual) <= 0.25 * initial_gap

        if stop_hit:
            trigger_position = position
            trigger_boundary_us = bucket_end_us
            reason = "protective_stop"
            break
        if horizon_boundary_us <= bucket_end_us:
            trigger_position = position
            trigger_boundary_us = horizon_boundary_us
            reason = "horizon"
            break
        if convergence:
            trigger_position = position
            trigger_boundary_us = bucket_end_us
            reason = "cross_venue_convergence"
            break

    if trigger_position is None or trigger_boundary_us is None or reason is None:
        raise ValueError("V5 position reached the fixed source boundary without a causal exit trigger")
    exit_target_us = trigger_boundary_us + config.latency_ms * 1_000
    found = _first_quote_after(frame, exit_target_us)
    if found is None:
        raise ValueError("V5 accepted entry has no actual Binance quote after exit latency")
    exit_position, exit_us = found
    for position in range(trigger_position + 1, exit_position):
        mark_position(position)
    exit_quote = _quote_from_first(frame.iloc[exit_position], event.side, entering=False)
    if exit_quote is None:
        raise ValueError("V5 exit first-quote group is unusable")
    exit_price, overrun = _mandatory_exit(exit_quote, event.side, quantity)
    exit_fee = quantity * exit_price * fee_bps / 10_000.0
    exit_nav = nav + event.side * quantity * (exit_price - entry_price) - entry_fee - exit_fee
    maximum_intratrade_drawdown = max(maximum_intratrade_drawdown, _drawdown(exit_nav, nav))
    maximum_path_drawdown = max(maximum_path_drawdown, _drawdown(exit_nav, account_peak))
    return ExitResolutionV5(
        exit_position,
        exit_us,
        exit_price,
        reason,
        overrun,
        trigger_boundary_us,
        maximum_intratrade_drawdown,
        maximum_path_drawdown,
    )


def simulate_fixed_day_v5(
    frames: dict[tuple[str, str], pd.DataFrame],
    events: Iterable[v1.Event],
    config: v1.Config,
) -> list[FixedTradeV5]:
    trades: list[FixedTradeV5] = []
    free_time_us = -1
    for candidate in _entry_candidates(frames, events, config):
        if candidate.entry_us < free_time_us:
            continue
        frame = frames[candidate.key]
        event = candidate.event
        entry_quote = _quote_from_first(frame.iloc[candidate.entry_position], event.side, entering=True)
        if entry_quote is None:
            continue
        reference = entry_quote["ask"] if event.side > 0 else entry_quote["bid"]
        quantity = v1.FIXED_NOTIONAL / reference
        entry_fill = _entry_fill(entry_quote, event.side, quantity)
        if entry_fill is None:
            continue
        entry_price, entry_spread = entry_fill
        entry_mid = (entry_quote["bid"] + entry_quote["ask"]) / 2.0
        stop_mid = entry_mid - event.side * config.stop_spreads * entry_spread
        resolved = _resolve_exit(
            frame,
            candidate,
            config,
            quantity,
            entry_price,
            stop_mid,
            0.0,
            v1.FIXED_NOTIONAL,
            v1.FIXED_NOTIONAL,
        )
        gross_bps = event.side * math.log(resolved.exit_price / entry_price) * 10_000.0
        spread_bps = entry_spread / entry_mid * 10_000.0
        trades.append(FixedTradeV5(
            config.config_id,
            event.day,
            event.symbol,
            event.family,
            event.decision_ms,
            candidate.entry_us // 1_000,
            resolved.exit_us // 1_000,
            candidate.entry_us,
            resolved.exit_us,
            event.side,
            entry_price,
            resolved.exit_price,
            gross_bps,
            spread_bps,
            0.0,
            gross_bps,
            resolved.exit_reason,
            event.score,
            resolved.exit_liquidity_overrun,
            resolved.trigger_boundary_us,
        ))
        free_time_us = resolved.exit_us + BUCKET_US
    return trades


def apply_fixed_fee(trades: Iterable[FixedTradeV5], fee_bps_per_side: float) -> list[FixedTradeV5]:
    return [
        replace(
            trade,
            fee_bps_per_side=fee_bps_per_side,
            net_bps=trade.gross_bps - 2.0 * fee_bps_per_side,
        )
        for trade in trades
    ]


def initial_account_state() -> dict[str, float]:
    return {
        "nav": d2.INITIAL_NAV,
        "peak": d2.INITIAL_NAV,
        "maximum_drawdown": 0.0,
    }


def simulate_account_day_v5(
    frames: dict[tuple[str, str], pd.DataFrame],
    events: Iterable[v1.Event],
    config: v1.Config,
    fee_bps: float,
    state: dict[str, float] | None = None,
) -> tuple[list[AccountTradeV5], dict[str, float]]:
    current = dict(initial_account_state() if state is None else state)
    nav = float(current["nav"])
    peak = float(current["peak"])
    maximum_drawdown = float(current["maximum_drawdown"])
    free_time_us = -1
    trades: list[AccountTradeV5] = []

    for candidate in _entry_candidates(frames, events, config):
        if candidate.entry_us < free_time_us:
            continue
        frame = frames[candidate.key]
        event = candidate.event
        entry_quote = _quote_from_first(frame.iloc[candidate.entry_position], event.side, entering=True)
        if entry_quote is None:
            continue
        entry_spread = entry_quote["ask"] - entry_quote["bid"]
        entry_mid = (entry_quote["bid"] + entry_quote["ask"]) / 2.0
        stop_mid = entry_mid - event.side * config.stop_spreads * entry_spread
        sized = _size_position(entry_quote, event.side, stop_mid, nav, fee_bps)
        if sized is None:
            continue
        quantity, entry_price, leverage = sized
        resolved = _resolve_exit(
            frame,
            candidate,
            config,
            quantity,
            entry_price,
            stop_mid,
            fee_bps,
            nav,
            peak,
        )
        entry_fee = quantity * entry_price * fee_bps / 10_000.0
        exit_fee = quantity * resolved.exit_price * fee_bps / 10_000.0
        gross = event.side * quantity * (resolved.exit_price - entry_price)
        fees = entry_fee + exit_fee
        net = gross - fees
        before = nav
        nav += net
        account_return = net / before
        peak = max(peak, nav)
        maximum_drawdown = max(
            maximum_drawdown,
            resolved.maximum_path_drawdown,
            _drawdown(nav, peak),
        )
        trades.append(AccountTradeV5(
            config.config_id,
            event.day,
            event.symbol,
            event.family,
            event.decision_ms,
            candidate.entry_us // 1_000,
            resolved.exit_us // 1_000,
            candidate.entry_us,
            resolved.exit_us,
            event.side,
            entry_price,
            resolved.exit_price,
            stop_mid,
            quantity,
            quantity * entry_price,
            leverage,
            gross,
            fees,
            net,
            account_return,
            before,
            nav,
            resolved.exit_reason,
            event.score,
            resolved.exit_liquidity_overrun,
            resolved.maximum_intratrade_drawdown,
            resolved.trigger_boundary_us,
        ))
        free_time_us = resolved.exit_us + BUCKET_US
        if nav <= 0:
            break

    return trades, {
        "nav": nav,
        "ending_nav": nav,
        "peak": peak,
        "maximum_drawdown": maximum_drawdown,
    }


def _removed_path_return(frame: pd.DataFrame, fraction: float) -> float | None:
    if frame.empty:
        return None
    count = max(1, int(math.ceil(len(frame) * fraction)))
    removed = set(frame.nlargest(count, "account_return").index)
    retained = frame.loc[~frame.index.isin(removed), "account_return"].to_numpy(float)
    return float(np.prod(1.0 + retained) - 1.0) if len(retained) else None


def account_metrics_v5(
    trades: list[AccountTradeV5],
    state: dict[str, float],
    days: Iterable[str],
) -> dict:
    day_list = list(days)
    if not trades:
        return {
            "n": 0,
            "eligible_days": len(day_list),
            "trades_per_day_median": 0.0,
            "positive_day_fraction": 0.0,
            "total_return": 0.0,
            "geometric_sample_day_return": 0.0,
            "profit_factor": None,
            "maximum_drawdown": 0.0,
            "closed_path_drawdown": 0.0,
            "conservative_combined_drawdown": 0.0,
            "top10pct_removed_return": None,
            "top5_positive_share": 1.0,
            "return_2022": 0.0,
            "return_2023": 0.0,
            "maximum_single_symbol_positive_pnl_share": 1.0,
            "exit_liquidity_overrun_count": 0,
            "maximum_intratrade_drawdown": 0.0,
            "ending_nav": float(state.get("nav", d2.INITIAL_NAV)),
        }
    frame = pd.DataFrame([asdict(item) for item in trades])
    daily = frame.groupby("day").account_return.apply(
        lambda values: float(np.prod(1.0 + values.to_numpy(float)) - 1.0)
    ).reindex(day_list, fill_value=0.0)
    positive_frame = frame.loc[frame.net_pnl > 0]
    positive = positive_frame.net_pnl.to_numpy(float)
    negative = frame.loc[frame.net_pnl < 0, "net_pnl"].to_numpy(float)
    positive_sum = float(positive.sum())
    positive_by_symbol = positive_frame.groupby("symbol").net_pnl.sum()
    counts = frame.groupby("day").size().reindex(day_list, fill_value=0)
    year_returns: dict[int, float] = {}
    for year in (2022, 2023):
        values = daily.loc[[day.startswith(str(year)) for day in daily.index]].to_numpy(float)
        year_returns[year] = float(np.prod(1.0 + values) - 1.0) if len(values) else 0.0
    nav_path = np.r_[d2.INITIAL_NAV, frame.nav_after.to_numpy(float)]
    nav_peak = np.maximum.accumulate(nav_path)
    closed_drawdown = float(np.max(1.0 - nav_path / np.maximum(nav_peak, 1e-12)))
    intratrade = float(frame.maximum_intratrade_drawdown.max())
    combined = min(1.0, closed_drawdown + intratrade)
    maximum_drawdown = max(float(state.get("maximum_drawdown", 0.0)), combined)
    return {
        "n": int(len(frame)),
        "eligible_days": len(day_list),
        "trades_per_day_median": float(counts.median()),
        "positive_day_fraction": float((daily > 0).mean()),
        "total_return": float(state["nav"] / d2.INITIAL_NAV - 1.0),
        "geometric_sample_day_return": float(np.expm1(np.log1p(daily).mean())),
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) else None,
        "maximum_drawdown": maximum_drawdown,
        "closed_path_drawdown": closed_drawdown,
        "conservative_combined_drawdown": combined,
        "top10pct_removed_return": _removed_path_return(frame, 0.10),
        "top5_positive_share": float(np.sort(positive)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0,
        "return_2022": year_returns[2022],
        "return_2023": year_returns[2023],
        "maximum_single_symbol_positive_pnl_share": float(positive_by_symbol.max() / positive_sum) if positive_sum > 0 else 1.0,
        "symbol_net_pnl": frame.groupby("symbol").net_pnl.sum().to_dict(),
        "symbol_positive_pnl": positive_by_symbol.to_dict(),
        "day_returns": daily.to_dict(),
        "exit_liquidity_overrun_count": int(frame.exit_liquidity_overrun.sum()),
        "maximum_intratrade_drawdown": intratrade,
        "ending_nav": float(state["nav"]),
    }
