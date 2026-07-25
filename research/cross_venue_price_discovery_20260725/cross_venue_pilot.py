from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import itertools
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests

BASE = "https://datasets.tardis.dev/v1"
BINANCE = "binance-futures"
BYBIT = "bybit"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
PILOT_DAYS = ("2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01")
BUCKET_MS = 100
MAX_QUOTE_AGE_MS = 1000
FIXED_NOTIONAL = 1000.0


@dataclass(frozen=True, slots=True)
class Config:
    family: str
    observation_ms: int
    displacement_spreads: float
    flow_imbalance: float
    follower_fraction: float
    latency_ms: int
    hold_ms: int
    stop_spreads: float
    basis_z: float

    @property
    def config_id(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class Event:
    day: str
    symbol: str
    family: str
    decision_ms: int
    side: int
    score: float
    initial_basis_residual: float


@dataclass(frozen=True, slots=True)
class Trade:
    config_id: str
    day: str
    symbol: str
    family: str
    decision_ms: int
    entry_ms: int
    exit_ms: int
    side: int
    entry_price: float
    exit_price: float
    gross_bps: float
    spread_bps: float
    fee_bps_per_side: float
    net_bps: float
    exit_reason: str
    score: float


def url(venue: str, data_type: str, symbol: str, date: str) -> str:
    y, m, d = date.split("-")
    return f"{BASE}/{venue}/{data_type}/{y}/{m}/{d}/{symbol}.csv.gz"


def timestamp_ms(raw: str) -> int:
    value = int(raw)
    if value >= 10**17:
        return value // 1_000_000
    if value >= 10**14:
        return value // 1_000
    if value >= 10**11:
        return value
    return value * 1000


def download(session: requests.Session, target: Path, source_url: str) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        payload = target.read_bytes()
        return {"url": source_url, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "cache_hit": True}
    errors: list[str] = []
    for attempt in range(5):
        try:
            response = session.get(source_url, timeout=(30, 300))
            if response.status_code == 200:
                target.write_bytes(response.content)
                return {"url": source_url, "bytes": len(response.content), "sha256": hashlib.sha256(response.content).hexdigest(), "cache_hit": False}
            errors.append(f"HTTP {response.status_code}")
            if response.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(2**attempt, 16))
    raise RuntimeError(f"download failed {source_url}: {'; '.join(errors[-5:])}")


def read_trades(path: Path) -> pd.DataFrame:
    buckets: dict[int, list[float]] = {}
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "side", "price", "amount"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"trade schema missing {sorted(missing)}")
        for row in reader:
            ts = timestamp_ms(row["timestamp"])
            bucket = ts // BUCKET_MS * BUCKET_MS
            price, amount = float(row["price"]), float(row["amount"])
            if not (math.isfinite(price) and math.isfinite(amount) and price > 0 and amount > 0):
                continue
            notional = price * amount
            signed = notional if row["side"].strip().lower() == "buy" else -notional
            item = buckets.get(bucket)
            if item is None:
                buckets[bucket] = [notional, signed, price, 1.0]
            else:
                item[0] += notional
                item[1] += signed
                item[2] = price
                item[3] += 1.0
    if not buckets:
        raise ValueError(f"no trades in {path}")
    rows = [(k, *v) for k, v in buckets.items()]
    return pd.DataFrame(rows, columns=["bucket_ms", "trade_notional", "signed_notional", "last_trade", "trade_count"]).sort_values("bucket_ms").set_index("bucket_ms")


def read_quotes(path: Path) -> pd.DataFrame:
    buckets: dict[int, tuple[float, float, float, float, int]] = {}
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "ask_price", "ask_amount", "bid_price", "bid_amount"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"quote schema missing {sorted(missing)}")
        for row in reader:
            ts = timestamp_ms(row["timestamp"])
            bucket = ts // BUCKET_MS * BUCKET_MS
            ask, ask_amount = float(row["ask_price"]), float(row["ask_amount"])
            bid, bid_amount = float(row["bid_price"]), float(row["bid_amount"])
            if not all(math.isfinite(x) for x in (ask, ask_amount, bid, bid_amount)) or ask <= bid or bid <= 0 or min(ask_amount, bid_amount) <= 0:
                continue
            buckets[bucket] = (bid, bid_amount, ask, ask_amount, ts)
    if not buckets:
        raise ValueError(f"no quotes in {path}")
    rows = [(k, *v) for k, v in buckets.items()]
    return pd.DataFrame(rows, columns=["bucket_ms", "bid", "bid_amount", "ask", "ask_amount", "quote_event_ms"]).sort_values("bucket_ms").set_index("bucket_ms")


def align(binance_trades: pd.DataFrame, binance_quotes: pd.DataFrame, bybit_trades: pd.DataFrame, bybit_quotes: pd.DataFrame) -> pd.DataFrame:
    start = max(x.index.min() for x in (binance_trades, binance_quotes, bybit_trades, bybit_quotes))
    end = min(x.index.max() for x in (binance_trades, binance_quotes, bybit_trades, bybit_quotes))
    grid = np.arange(start, end + BUCKET_MS, BUCKET_MS, dtype=np.int64)
    out = pd.DataFrame(index=grid)
    for prefix, trades, quotes in (("bn", binance_trades, binance_quotes), ("bb", bybit_trades, bybit_quotes)):
        trade = trades.reindex(grid)
        out[f"{prefix}_trade_notional"] = trade.trade_notional.fillna(0.0)
        out[f"{prefix}_signed_notional"] = trade.signed_notional.fillna(0.0)
        out[f"{prefix}_trade_count"] = trade.trade_count.fillna(0.0)
        quote = quotes.reindex(grid)
        actual = quote.quote_event_ms.copy()
        quote = quote.ffill(limit=MAX_QUOTE_AGE_MS // BUCKET_MS)
        for name in ("bid", "bid_amount", "ask", "ask_amount", "quote_event_ms"):
            out[f"{prefix}_{name}"] = quote[name]
        out[f"{prefix}_quote_actual"] = actual.notna()
        out[f"{prefix}_mid"] = (out[f"{prefix}_bid"] + out[f"{prefix}_ask"]) / 2.0
        out[f"{prefix}_spread"] = out[f"{prefix}_ask"] - out[f"{prefix}_bid"]
        out[f"{prefix}_quote_imbalance"] = (out[f"{prefix}_bid_amount"] - out[f"{prefix}_ask_amount"]) / (out[f"{prefix}_bid_amount"] + out[f"{prefix}_ask_amount"])
    valid = np.isfinite(out[["bn_mid", "bb_mid", "bn_spread", "bb_spread"]]).all(axis=1)
    return out.loc[valid].copy()


def rolling_sum(values: pd.Series, bins: int) -> pd.Series:
    return values.rolling(bins, min_periods=bins).sum()


def signal_events(frame: pd.DataFrame, config: Config, day: str, symbol: str) -> list[Event]:
    bins = max(1, config.observation_ms // BUCKET_MS)
    short_bins = max(1, min(5, bins // 2))
    bn_log = np.log(frame.bn_mid)
    bb_log = np.log(frame.bb_mid)
    bn_ret = bn_log - bn_log.shift(bins)
    bb_ret = bb_log - bb_log.shift(bins)
    bn_flow_num = rolling_sum(frame.bn_signed_notional, bins)
    bn_flow_den = rolling_sum(frame.bn_trade_notional, bins).replace(0, np.nan)
    bb_flow_num = rolling_sum(frame.bb_signed_notional, bins)
    bb_flow_den = rolling_sum(frame.bb_trade_notional, bins).replace(0, np.nan)
    bn_flow = bn_flow_num / bn_flow_den
    bb_flow = bb_flow_num / bb_flow_den
    bn_flow_short = rolling_sum(frame.bn_signed_notional, short_bins) / rolling_sum(frame.bn_trade_notional, short_bins).replace(0, np.nan)
    basis = bb_log - bn_log
    basis_history = basis.shift(1)
    basis_mean = basis_history.rolling(600, min_periods=300).mean()
    basis_std = basis_history.rolling(600, min_periods=300).std(ddof=0).replace(0, np.nan)
    basis_residual = basis - basis_mean
    basis_z = basis_residual / basis_std
    bybit_spread_log = frame.bb_spread / frame.bb_mid
    binance_spread_log = frame.bn_spread / frame.bn_mid
    events: list[Event] = []

    if config.family == "bybit_to_binance_propagation":
        direction = np.sign(bb_ret)
        displacement = bb_ret.abs() / bybit_spread_log.replace(0, np.nan)
        response = direction * bn_ret / bb_ret.abs().replace(0, np.nan)
        cross_gap = direction * basis_residual
        mask = (
            (displacement >= config.displacement_spreads)
            & (direction * bb_flow >= config.flow_imbalance)
            & (response >= -0.25)
            & (response <= config.follower_fraction)
            & (direction * bn_flow >= -0.20)
            & (cross_gap > 0)
        )
        score = displacement + direction * bb_flow + cross_gap / bybit_spread_log.replace(0, np.nan)
        sides = direction
    elif config.family == "binance_overshoot_fade":
        direction = np.sign(bn_ret)
        displacement = bn_ret.abs() / binance_spread_log.replace(0, np.nan)
        bybit_response = direction * bb_ret / bn_ret.abs().replace(0, np.nan)
        overshoot = -direction * basis_residual
        mask = (
            (displacement >= config.displacement_spreads)
            & (direction * bn_flow >= config.flow_imbalance)
            & (bybit_response >= -0.25)
            & (bybit_response <= config.follower_fraction)
            & (direction * bn_flow_short <= 0.20)
            & (overshoot > 0)
        )
        score = displacement + direction * bn_flow + overshoot / binance_spread_log.replace(0, np.nan)
        sides = -direction
    else:
        direction = np.sign(bn_ret + bb_ret)
        both = (direction * bn_ret > 0) & (direction * bb_ret > 0)
        contracting = basis_residual * basis_residual.diff() < 0
        mask = (
            both
            & (basis_z.abs() >= config.basis_z)
            & contracting
            & (direction * bn_flow >= -0.20)
            & (direction * bb_flow >= -0.20)
        )
        score = basis_z.abs() + (bn_ret.abs() / binance_spread_log.replace(0, np.nan)) + (bb_ret.abs() / bybit_spread_log.replace(0, np.nan))
        sides = np.sign(basis_residual)

    mask = mask.fillna(False) & mask.shift(1, fill_value=False).eq(False) & sides.ne(0)
    raw = np.flatnonzero(mask.to_numpy())
    cooldown_bins = max(10, config.hold_ms // BUCKET_MS)
    next_free = -1
    for position in raw:
        if position < next_free:
            continue
        ts = int(frame.index[position])
        events.append(Event(day, symbol, config.family, ts, int(sides.iloc[position]), float(score.iloc[position]), float(basis_residual.iloc[position])))
        next_free = position + cooldown_bins
    return events


def execution_price(row: pd.Series, side: int, entering: bool) -> tuple[float, float] | None:
    if entering:
        price = float(row.bn_ask if side > 0 else row.bn_bid)
        available = float(row.bn_ask_amount if side > 0 else row.bn_bid_amount)
    else:
        price = float(row.bn_bid if side > 0 else row.bn_ask)
        available = float(row.bn_bid_amount if side > 0 else row.bn_ask_amount)
    quantity = FIXED_NOTIONAL / price
    if quantity > 0.05 * available:
        return None
    spread = float(row.bn_ask - row.bn_bid)
    participation = quantity / max(available, 1e-12)
    impact = spread * max(participation / 0.05, 0.0) * 0.25
    return (price + side * impact if entering else price - side * impact), spread


def simulate(frame: pd.DataFrame, events: Iterable[Event], config: Config, fee_bps_per_side: float) -> list[Trade]:
    quote_rows = frame.loc[frame.bn_quote_actual].copy()
    quote_times = quote_rows.index.to_numpy(np.int64)
    if not len(quote_times):
        return []
    trades: list[Trade] = []
    free_time = -1
    for event in sorted(events, key=lambda item: (-item.score, item.decision_ms)):
        if event.decision_ms < free_time:
            continue
        target = event.decision_ms + config.latency_ms
        entry_pos = int(np.searchsorted(quote_times, target, side="left"))
        if entry_pos >= len(quote_times):
            continue
        entry_ms = int(quote_times[entry_pos])
        if entry_ms < target:
            raise AssertionError("entry preceded latency boundary")
        entry_row = quote_rows.iloc[entry_pos]
        entry_fill = execution_price(entry_row, event.side, True)
        if entry_fill is None:
            continue
        entry_price, entry_spread = entry_fill
        entry_mid = float(entry_row.bn_mid)
        stop = entry_mid - event.side * config.stop_spreads * entry_spread
        end_ms = entry_ms + config.hold_ms
        exit_pos = int(np.searchsorted(quote_times, end_ms, side="left"))
        exit_pos = min(exit_pos, len(quote_times) - 1)
        reason = "horizon"
        chosen = exit_pos
        initial_gap = abs(event.initial_basis_residual)
        for pos in range(entry_pos, exit_pos + 1):
            row = quote_rows.iloc[pos]
            mid = float(row.bn_mid)
            if (event.side > 0 and mid <= stop) or (event.side < 0 and mid >= stop):
                chosen, reason = pos, "protective_stop"
                break
            current_basis = math.log(float(row.bb_mid) / mid)
            history_end = int(np.searchsorted(frame.index.to_numpy(np.int64), int(quote_times[pos]), side="right"))
            hist = np.log(frame.bb_mid.iloc[max(0, history_end - 601):max(0, history_end - 1)]) - np.log(frame.bn_mid.iloc[max(0, history_end - 601):max(0, history_end - 1)])
            if len(hist) >= 300:
                residual = current_basis - float(hist.median())
                if initial_gap > 0 and abs(residual) <= 0.25 * initial_gap:
                    chosen, reason = pos, "cross_venue_convergence"
                    break
        exit_ms = int(quote_times[chosen])
        exit_row = quote_rows.iloc[chosen]
        exit_fill = execution_price(exit_row, event.side, False)
        if exit_fill is None:
            continue
        exit_price, _ = exit_fill
        gross = event.side * math.log(exit_price / entry_price) * 10_000.0
        spread_bps = entry_spread / entry_mid * 10_000.0
        net = gross - 2.0 * fee_bps_per_side
        trades.append(Trade(config.config_id, event.day, event.symbol, event.family, event.decision_ms, entry_ms, exit_ms, event.side, entry_price, exit_price, gross, spread_bps, fee_bps_per_side, net, reason, event.score))
        free_time = exit_ms + BUCKET_MS
    return trades


def trimmed_mean(values: np.ndarray, fraction: float) -> float | None:
    if not len(values):
        return None
    remove = max(1, int(math.ceil(len(values) * fraction)))
    return float(np.sort(values)[:-remove].mean()) if len(values) > remove else None


def metrics(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0, "mean_net_bps": None, "profit_factor": None, "positive_day_fraction": 0.0, "top10pct_removed_mean_bps": None, "top5_positive_share": 1.0, "total_fixed_notional_return": 0.0}
    frame = pd.DataFrame([asdict(item) for item in trades])
    net = frame.net_bps.to_numpy(float)
    positive = net[net > 0]
    negative = net[net < 0]
    day = frame.groupby("day").net_bps.sum()
    positive_sum = float(positive.sum())
    return {
        "n": int(len(frame)),
        "mean_net_bps": float(net.mean()),
        "median_net_bps": float(np.median(net)),
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) else None,
        "positive_day_fraction": float((day > 0).mean()),
        "median_trades_per_day": float(frame.groupby("day").size().median()),
        "top10pct_removed_mean_bps": trimmed_mean(net, 0.10),
        "top5_positive_share": float(np.sort(positive)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0,
        "total_fixed_notional_return": float(net.sum() / 10_000.0),
        "symbol_counts": frame.symbol.value_counts().to_dict(),
        "day_returns_bps": day.to_dict(),
    }


def pilot_grid() -> list[Config]:
    return [Config(*values) for values in itertools.product(
        ("bybit_to_binance_propagation", "binance_overshoot_fade", "simultaneous_shock_basis_snapback"),
        (1000, 3000),
        (4.0, 8.0),
        (0.60, 0.75),
        (0.25, 0.50),
        (100, 500),
        (3000, 10000),
        (4.0, 8.0),
        (2.0, 3.0),
    )]


def load_day(cache: Path, session: requests.Session, date: str, symbol: str) -> tuple[pd.DataFrame, list[dict]]:
    sources = []
    data = {}
    for venue in (BINANCE, BYBIT):
        for data_type in ("trades", "quotes"):
            target = cache / venue / data_type / date / f"{symbol}.csv.gz"
            source = url(venue, data_type, symbol, date)
            sources.append({"venue": venue, "data_type": data_type, "symbol": symbol, "date": date, **download(session, target, source)})
            data[(venue, data_type)] = read_trades(target) if data_type == "trades" else read_quotes(target)
    return align(data[(BINANCE, "trades")], data[(BINANCE, "quotes")], data[(BYBIT, "trades")], data[(BYBIT, "quotes")]), sources


def run(output: Path, cache: Path, days: tuple[str, ...] = PILOT_DAYS) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    all_frames: dict[tuple[str, str], pd.DataFrame] = {}
    source_records: list[dict] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-venue-pilot/1.0"
        for day in days:
            for symbol in SYMBOLS:
                frame, records = load_day(cache, session, day, symbol)
                all_frames[(day, symbol)] = frame
                source_records.extend(records)
                print(json.dumps({"day": day, "symbol": symbol, "aligned_rows": len(frame)}), flush=True)
    rows = []
    ledgers: list[pd.DataFrame] = []
    configs = pilot_grid()
    for number, config in enumerate(configs, 1):
        events: list[Event] = []
        for (day, symbol), frame in all_frames.items():
            events.extend(signal_events(frame, config, day, symbol))
        for fee in (0.0, 5.0, 7.5, 10.0):
            trades: list[Trade] = []
            by_key: dict[tuple[str, str], list[Event]] = {}
            for event in events:
                by_key.setdefault((event.day, event.symbol), []).append(event)
            # A second global merge is applied after per-symbol simulations to prevent simultaneous BTC/ETH positions.
            provisional: list[Trade] = []
            for key, day_events in by_key.items():
                provisional.extend(simulate(all_frames[key], day_events, config, fee))
            free = -1
            for trade in sorted(provisional, key=lambda item: (item.entry_ms, -item.score, item.symbol)):
                if trade.entry_ms >= free:
                    trades.append(trade)
                    free = trade.exit_ms + BUCKET_MS
            summary = metrics(trades)
            rows.append({"config_id": config.config_id, **asdict(config), "fee_bps_per_side": fee, "event_count": len(events), **{k: v for k, v in summary.items() if not isinstance(v, dict)}})
            if fee == 5.0 and trades:
                ledger = pd.DataFrame([asdict(item) for item in trades])
                ledger["config_id"] = config.config_id
                ledgers.append(ledger)
        if number % 50 == 0:
            print(json.dumps({"configs_done": number, "configs_total": len(configs)}), flush=True)
    grid = pd.DataFrame(rows)
    grid.to_csv(output / "PILOT_GRID.csv", index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(output / "PILOT_5BPS_LEDGERS.csv", index=False)
    base = grid[grid.fee_bps_per_side == 5.0].copy()
    zero = grid[grid.fee_bps_per_side == 0.0][["config_id", "mean_net_bps", "total_fixed_notional_return"]].rename(columns={"mean_net_bps": "zero_fee_mean_bps", "total_fixed_notional_return": "zero_fee_total_return"})
    stress = grid[grid.fee_bps_per_side == 10.0][["config_id", "mean_net_bps", "total_fixed_notional_return"]].rename(columns={"mean_net_bps": "ten_fee_mean_bps", "total_fixed_notional_return": "ten_fee_total_return"})
    candidates = base.merge(zero, on="config_id").merge(stress, on="config_id")
    candidates["fatal_edge_pass"] = (
        (candidates.n >= 100)
        & (candidates.zero_fee_mean_bps > 0)
        & (candidates.total_fixed_notional_return > 0)
        & (candidates.ten_fee_total_return > 0)
        & (candidates.top10pct_removed_mean_bps > 0)
        & (candidates.positive_day_fraction >= 0.50)
    )
    candidates = candidates.sort_values(["fatal_edge_pass", "ten_fee_total_return", "config_id"], ascending=[False, False, True])
    candidates.to_csv(output / "PILOT_CANDIDATES.csv", index=False)
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-1850-XVENUE-001",
        "stage": "SYSTEMATIC_SAMPLE_FATAL_EDGE_PILOT",
        "pilot_days": list(days),
        "configurations": len(configs),
        "fatal_edge_pass_count": int(candidates.fatal_edge_pass.sum()),
        "best": candidates.iloc[0].replace({np.nan: None}).to_dict() if len(candidates) else None,
        "full_development_opened": False,
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "champion_eligible": False,
        "source_records": source_records,
    }
    path = output / "PILOT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    (output / "PILOT_RESULT.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    return result


def self_test() -> None:
    index = np.arange(0, 20_000, BUCKET_MS, dtype=np.int64)
    frame = pd.DataFrame(index=index)
    for prefix, offset in (("bn", 0.0), ("bb", 0.0)):
        frame[f"{prefix}_bid"] = 99.9 + offset
        frame[f"{prefix}_ask"] = 100.1 + offset
        frame[f"{prefix}_bid_amount"] = 100.0
        frame[f"{prefix}_ask_amount"] = 100.0
        frame[f"{prefix}_quote_event_ms"] = index
        frame[f"{prefix}_quote_actual"] = True
        frame[f"{prefix}_mid"] = 100.0 + offset
        frame[f"{prefix}_spread"] = 0.2
        frame[f"{prefix}_trade_notional"] = 0.0
        frame[f"{prefix}_signed_notional"] = 0.0
        frame[f"{prefix}_trade_count"] = 0.0
        frame[f"{prefix}_quote_imbalance"] = 0.0
    frame.loc[5000:5900, "bb_mid"] = np.linspace(100, 101, 10)
    frame.loc[5000:5900, "bb_bid"] = frame.loc[5000:5900, "bb_mid"] - 0.1
    frame.loc[5000:5900, "bb_ask"] = frame.loc[5000:5900, "bb_mid"] + 0.1
    frame.loc[5000:5900, "bb_trade_notional"] = 1000.0
    frame.loc[5000:5900, "bb_signed_notional"] = 900.0
    config = Config("bybit_to_binance_propagation", 1000, 4.0, 0.60, 0.50, 500, 3000, 4.0, 2.0)
    events = signal_events(frame, config, "synthetic", "BTCUSDT")
    assert events
    trades = simulate(frame, events, config, 0.0)
    assert all(item.entry_ms >= item.decision_ms + 500 for item in trades)
    changed = frame.copy()
    changed.loc[15000:, "bb_mid"] *= 2.0
    prefix_a = signal_events(frame, config, "synthetic", "BTCUSDT")
    prefix_b = signal_events(changed, config, "synthetic", "BTCUSDT")
    assert [(x.decision_ms, x.side) for x in prefix_a if x.decision_ms < 15000] == [(x.decision_ms, x.side) for x in prefix_b if x.decision_ms < 15000]
    print("cross-venue pilot self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    result = run(args.output, args.cache)
    print(json.dumps({"fatal_edge_pass_count": result["fatal_edge_pass_count"], "best": result["best"]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
