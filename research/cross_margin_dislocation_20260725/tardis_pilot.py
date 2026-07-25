from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import itertools
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from tardis_source_probe import BASE, ROUTES, canonical_url, to_ms

BUCKET_MS = 100
MAX_QUOTE_AGE_MS = 1000
FIXED_NOTIONAL = 1000.0
PILOT_DAYS = ("2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01")
FEE_LEVELS = (0.0, 5.0, 7.5, 10.0)


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
    asset: str
    family: str
    decision_ms: int
    side: int
    score: float
    initial_basis_residual: float


@dataclass(frozen=True, slots=True)
class Trade:
    config_id: str
    day: str
    asset: str
    family: str
    decision_ms: int
    entry_ms: int
    exit_ms: int
    side: int
    entry_price: float
    exit_price: float
    gross_bps: float
    fee_bps_per_side: float
    net_bps: float
    exit_reason: str
    score: float
    exit_liquidity_overrun: bool


def fetch(session: requests.Session, source: str, target: Path) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        payload = target.read_bytes()
        return {"url": source, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "cache_hit": True}
    errors: list[str] = []
    for attempt in range(5):
        try:
            response = session.get(source, timeout=(30, 300))
            if response.status_code == 200:
                target.write_bytes(response.content)
                return {"url": source, "bytes": len(response.content), "sha256": hashlib.sha256(response.content).hexdigest(), "cache_hit": False}
            errors.append(f"HTTP {response.status_code}")
            if response.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(2**attempt, 16))
    raise RuntimeError(f"download failed {source}: {'; '.join(errors[-5:])}")


def read_trades(path: Path) -> pd.DataFrame:
    buckets: dict[int, list[float]] = {}
    previous_local: int | None = None
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "local_timestamp", "side", "price", "amount"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"trade schema missing {sorted(missing)}")
        for row in reader:
            local = to_ms(row["local_timestamp"])
            if previous_local is not None and local < previous_local:
                raise ValueError("local_timestamp not monotonic")
            previous_local = local
            price, amount = float(row["price"]), float(row["amount"])
            if not (math.isfinite(price) and math.isfinite(amount) and price > 0 and amount > 0):
                continue
            bucket = local // BUCKET_MS * BUCKET_MS
            signed_amount = amount if row["side"].strip().lower() == "buy" else -amount
            item = buckets.get(bucket)
            if item is None:
                buckets[bucket] = [amount, signed_amount, price, 1.0]
            else:
                item[0] += amount
                item[1] += signed_amount
                item[2] = price
                item[3] += 1.0
    if not buckets:
        raise ValueError(f"no valid trades {path}")
    rows = [(key, *values) for key, values in buckets.items()]
    return pd.DataFrame(rows, columns=["bucket_ms", "amount", "signed_amount", "last_trade", "trade_count"]).sort_values("bucket_ms").set_index("bucket_ms")


def read_quotes(path: Path) -> pd.DataFrame:
    buckets: dict[int, tuple[float, float, float, float, int]] = {}
    previous_local: int | None = None
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "local_timestamp", "ask_price", "ask_amount", "bid_price", "bid_amount"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"quote schema missing {sorted(missing)}")
        for row in reader:
            local = to_ms(row["local_timestamp"])
            if previous_local is not None and local < previous_local:
                raise ValueError("local_timestamp not monotonic")
            previous_local = local
            ask, ask_amount = float(row["ask_price"]), float(row["ask_amount"])
            bid, bid_amount = float(row["bid_price"]), float(row["bid_amount"])
            if not all(math.isfinite(value) for value in (ask, ask_amount, bid, bid_amount)):
                continue
            if ask <= bid or bid <= 0 or min(ask_amount, bid_amount) <= 0:
                continue
            bucket = local // BUCKET_MS * BUCKET_MS
            buckets[bucket] = (bid, bid_amount, ask, ask_amount, local)
    if not buckets:
        raise ValueError(f"no valid quotes {path}")
    rows = [(key, *values) for key, values in buckets.items()]
    return pd.DataFrame(rows, columns=["bucket_ms", "bid", "bid_amount", "ask", "ask_amount", "quote_event_ms"]).sort_values("bucket_ms").set_index("bucket_ms")


def align(coin_trades: pd.DataFrame, coin_quotes: pd.DataFrame, usd_trades: pd.DataFrame, usd_quotes: pd.DataFrame) -> pd.DataFrame:
    start = max(item.index.min() for item in (coin_trades, coin_quotes, usd_trades, usd_quotes))
    end = min(item.index.max() for item in (coin_trades, coin_quotes, usd_trades, usd_quotes))
    grid = np.arange(start, end + BUCKET_MS, BUCKET_MS, dtype=np.int64)
    frame = pd.DataFrame(index=grid)
    for prefix, trades, quotes in (("cm", coin_trades, coin_quotes), ("um", usd_trades, usd_quotes)):
        trade = trades.reindex(grid)
        frame[f"{prefix}_amount"] = trade.amount.fillna(0.0)
        frame[f"{prefix}_signed_amount"] = trade.signed_amount.fillna(0.0)
        frame[f"{prefix}_trade_count"] = trade.trade_count.fillna(0.0)
        quote = quotes.reindex(grid)
        actual = quote.quote_event_ms.copy()
        carried = quote.ffill(limit=MAX_QUOTE_AGE_MS // BUCKET_MS)
        for column in ("bid", "bid_amount", "ask", "ask_amount", "quote_event_ms"):
            frame[f"{prefix}_{column}"] = carried[column]
        frame[f"{prefix}_quote_actual"] = actual.notna()
        frame[f"{prefix}_mid"] = (frame[f"{prefix}_bid"] + frame[f"{prefix}_ask"]) / 2.0
        frame[f"{prefix}_spread"] = frame[f"{prefix}_ask"] - frame[f"{prefix}_bid"]
    valid = np.isfinite(frame[["cm_mid", "um_mid", "cm_spread", "um_spread"]]).all(axis=1)
    return frame.loc[valid].copy()


def rolling_ratio(signed: pd.Series, total: pd.Series, bins: int) -> pd.Series:
    numerator = signed.rolling(bins, min_periods=bins).sum()
    denominator = total.rolling(bins, min_periods=bins).sum().replace(0, np.nan)
    return numerator / denominator


def signals(frame: pd.DataFrame, config: Config, day: str, asset: str) -> list[Event]:
    bins = max(1, config.observation_ms // BUCKET_MS)
    short_bins = max(1, min(5, bins // 2))
    cm_log = np.log(frame.cm_mid)
    um_log = np.log(frame.um_mid)
    cm_ret = cm_log - cm_log.shift(bins)
    um_ret = um_log - um_log.shift(bins)
    cm_flow = rolling_ratio(frame.cm_signed_amount, frame.cm_amount, bins)
    um_flow = rolling_ratio(frame.um_signed_amount, frame.um_amount, bins)
    cm_flow_short = rolling_ratio(frame.cm_signed_amount, frame.cm_amount, short_bins)
    basis = cm_log - um_log
    history = basis.shift(1)
    median = history.rolling(600, min_periods=300).median()
    sigma = history.rolling(600, min_periods=300).std(ddof=0).replace(0, np.nan)
    residual = basis - median
    basis_z = residual / sigma
    cm_spread_log = frame.cm_spread / frame.cm_mid
    um_spread_log = frame.um_spread / frame.um_mid

    if config.family == "coinm_downside_collateral_cascade":
        displacement = (-cm_ret) / cm_spread_log.replace(0, np.nan)
        response = (-um_ret) / cm_ret.abs().replace(0, np.nan)
        mask = (
            (cm_ret < 0)
            & (displacement >= config.displacement_spreads)
            & (cm_flow <= -config.flow_imbalance)
            & (response >= -0.25)
            & (response <= config.follower_fraction)
            & (um_flow <= 0.20)
            & (residual < 0)
        )
        side = pd.Series(-1, index=frame.index)
        score = displacement - cm_flow + (-residual) / cm_spread_log.replace(0, np.nan)
    elif config.family == "coinm_flow_first_propagation":
        direction = np.sign(cm_ret)
        displacement = cm_ret.abs() / cm_spread_log.replace(0, np.nan)
        response = direction * um_ret / cm_ret.abs().replace(0, np.nan)
        mask = (
            (direction != 0)
            & (displacement >= config.displacement_spreads)
            & (direction * cm_flow >= config.flow_imbalance)
            & (response >= -0.25)
            & (response <= config.follower_fraction)
            & (direction * um_flow >= -0.20)
            & (direction * residual > 0)
        )
        side = direction
        score = displacement + direction * cm_flow + direction * residual / cm_spread_log.replace(0, np.nan)
    elif config.family == "usdm_overreaction_fade":
        direction = np.sign(um_ret)
        displacement = um_ret.abs() / um_spread_log.replace(0, np.nan)
        anchor_response = direction * cm_ret / um_ret.abs().replace(0, np.nan)
        mask = (
            (direction != 0)
            & (displacement >= config.displacement_spreads)
            & (direction * um_flow >= config.flow_imbalance)
            & (anchor_response >= -0.25)
            & (anchor_response <= config.follower_fraction)
            & (direction * cm_flow_short <= 0.20)
            & (direction * residual < 0)
        )
        side = -direction
        score = displacement + direction * um_flow + (-direction * residual) / um_spread_log.replace(0, np.nan)
    else:
        direction = np.sign(cm_ret + um_ret)
        both = (direction * cm_ret > 0) & (direction * um_ret > 0)
        contracting = residual * residual.diff() < 0
        mask = (
            both
            & (basis_z.abs() >= config.basis_z)
            & contracting
            & (direction * cm_flow >= -0.20)
            & (direction * um_flow >= -0.20)
        )
        side = -np.sign(residual)
        score = basis_z.abs() + cm_ret.abs() / cm_spread_log.replace(0, np.nan) + um_ret.abs() / um_spread_log.replace(0, np.nan)

    mask = mask.fillna(False) & mask.shift(1, fill_value=False).eq(False) & side.ne(0)
    rows = np.flatnonzero(mask.to_numpy())
    cooldown = max(10, config.hold_ms // BUCKET_MS)
    next_free = -1
    events: list[Event] = []
    for position in rows:
        if position < next_free:
            continue
        decision = int(frame.index[position] + BUCKET_MS)
        events.append(Event(day, asset, config.family, decision, int(side.iloc[position]), float(score.iloc[position]), float(residual.iloc[position])))
        next_free = position + cooldown
    return events


def entry_price(row: pd.Series, side: int) -> tuple[float, float] | None:
    price = float(row.um_ask if side > 0 else row.um_bid)
    amount = float(row.um_ask_amount if side > 0 else row.um_bid_amount)
    spread = float(row.um_ask - row.um_bid)
    quantity = FIXED_NOTIONAL / price
    if quantity > 0.05 * amount:
        return None
    impact = spread * 0.25 * max((quantity / amount) / 0.05, 0.0)
    return price + side * impact, spread


def exit_price(row: pd.Series, side: int, quantity: float) -> tuple[float, bool] | None:
    price = float(row.um_bid if side > 0 else row.um_ask)
    amount = float(row.um_bid_amount if side > 0 else row.um_ask_amount)
    spread = float(row.um_ask - row.um_bid)
    if not all(math.isfinite(value) for value in (price, amount, spread)) or price <= 0 or amount <= 0 or spread <= 0:
        return None
    participation = quantity / amount
    normalized = participation / 0.05
    impact = spread * (0.25 * min(normalized, 1.0) + 2.0 * max(normalized - 1.0, 0.0))
    return (max(price * 0.10, price - impact) if side > 0 else price + impact), participation > 0.05


def simulate(frame: pd.DataFrame, events: list[Event], config: Config, fee: float) -> list[Trade]:
    quotes = frame.loc[frame.um_quote_actual].copy()
    quote_times = quotes.um_quote_event_ms.to_numpy(np.int64)
    frame_times = frame.index.to_numpy(np.int64)
    results: list[Trade] = []
    free = -1
    for event in sorted(events, key=lambda item: (item.decision_ms, -item.score, item.asset, item.family)):
        if event.decision_ms < free:
            continue
        target = event.decision_ms + config.latency_ms
        start = int(np.searchsorted(quote_times, target, side="left"))
        if start >= len(quote_times):
            continue
        entry_ms = int(quote_times[start])
        row = quotes.iloc[start]
        opened = entry_price(row, event.side)
        if opened is None:
            continue
        entered, spread = opened
        quantity = FIXED_NOTIONAL / entered
        stop = float(row.um_mid) - event.side * config.stop_spreads * spread
        end = min(int(np.searchsorted(quote_times, entry_ms + config.hold_ms, side="left")), len(quote_times) - 1)
        chosen, reason = end, "horizon"
        initial_gap = abs(event.initial_basis_residual)
        for position in range(start, end + 1):
            current = quotes.iloc[position]
            stopped = float(current.um_bid) <= stop if event.side > 0 else float(current.um_ask) >= stop
            if stopped:
                chosen, reason = position, "protective_stop"
                break
            basis = math.log(float(current.cm_mid) / float(current.um_mid))
            bucket = int(quotes.index[position])
            history_end = int(np.searchsorted(frame_times, bucket, side="right"))
            hist_start = max(0, history_end - 601)
            hist_stop = max(hist_start, history_end - 1)
            history = np.log(frame.cm_mid.iloc[hist_start:hist_stop]) - np.log(frame.um_mid.iloc[hist_start:hist_stop])
            if len(history) >= 300:
                current_residual = basis - float(history.median())
                if initial_gap > 0 and abs(current_residual) <= 0.25 * initial_gap:
                    chosen, reason = position, "basis_convergence"
                    break
        closed = exit_price(quotes.iloc[chosen], event.side, quantity)
        if closed is None:
            raise ValueError("entered trade reached unusable actual USD-M exit quote")
        exited, overrun = closed
        gross = event.side * math.log(exited / entered) * 10_000.0
        net = gross - 2.0 * fee
        results.append(Trade(config.config_id, event.day, event.asset, event.family, event.decision_ms, entry_ms, int(quote_times[chosen]), event.side, entered, exited, gross, fee, net, reason, event.score, overrun))
        free = int(quote_times[chosen]) + BUCKET_MS
    return results


def metrics(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0, "mean_net_bps": None, "positive_day_fraction": 0.0, "profit_factor": None, "top10pct_removed_mean_bps": None, "top5_positive_share": 1.0, "total_fixed_notional_return": 0.0}
    frame = pd.DataFrame([asdict(item) for item in trades])
    net = frame.net_bps.to_numpy(float)
    positive = net[net > 0]
    negative = net[net < 0]
    day = frame.groupby("day").net_bps.sum()
    remove = max(1, int(math.ceil(len(net) * 0.10)))
    trimmed = float(np.sort(net)[:-remove].mean()) if len(net) > remove else None
    positive_sum = float(positive.sum())
    return {
        "n": int(len(frame)),
        "mean_net_bps": float(net.mean()),
        "median_net_bps": float(np.median(net)),
        "positive_day_fraction": float((day > 0).mean()),
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) else None,
        "top10pct_removed_mean_bps": trimmed,
        "top5_positive_share": float(np.sort(positive)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0,
        "total_fixed_notional_return": float(net.sum() / 10_000.0),
        "median_trades_per_day": float(frame.groupby("day").size().median()),
        "exit_liquidity_overrun_count": int(frame.exit_liquidity_overrun.sum()),
        "asset_counts": frame.asset.value_counts().to_dict(),
        "day_returns_bps": day.to_dict(),
    }


def grid() -> list[Config]:
    return [Config(*values) for values in itertools.product(
        ("coinm_downside_collateral_cascade", "coinm_flow_first_propagation", "usdm_overreaction_fade", "simultaneous_basis_snapback"),
        (500, 1000, 3000),
        (2.0, 4.0, 8.0),
        (0.60, 0.75),
        (0.25, 0.50),
        (50, 100, 250),
        (1000, 3000, 10000),
        (4.0, 8.0),
        (2.0, 3.0),
    )]


def load_day(cache: Path, session: requests.Session, day: str, asset: str) -> tuple[pd.DataFrame, list[dict]]:
    source_records = []
    data = {}
    for leg, (venue, symbol) in ROUTES[asset].items():
        for data_type in ("trades", "quotes"):
            source = canonical_url(venue, data_type, symbol, day)
            target = cache / venue / data_type / day / f"{symbol}.csv.gz"
            source_records.append({"asset": asset, "leg": leg, "data_type": data_type, "date": day, **fetch(session, source, target)})
            data[(leg, data_type)] = read_trades(target) if data_type == "trades" else read_quotes(target)
    return align(data[("coin_m", "trades")], data[("coin_m", "quotes")], data[("usd_m", "trades")], data[("usd_m", "quotes")]), source_records


def run(output: Path, cache: Path, days: tuple[str, ...] = PILOT_DAYS) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    frames = {}
    sources = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-margin-tardis-pilot/1.0"
        for day in days:
            for asset in ROUTES:
                frame, records = load_day(cache, session, day, asset)
                frames[(day, asset)] = frame
                sources.extend(records)
                print(json.dumps({"day": day, "asset": asset, "aligned_rows": len(frame)}), flush=True)
    rows = []
    ledgers = []
    configs = grid()
    for number, config in enumerate(configs, 1):
        events = []
        for (day, asset), frame in frames.items():
            events.extend(signals(frame, config, day, asset))
        for fee in FEE_LEVELS:
            provisional = []
            for key, frame in frames.items():
                subset = [event for event in events if (event.day, event.asset) == key]
                provisional.extend(simulate(frame, subset, config, fee))
            free = -1
            trades = []
            for trade in sorted(provisional, key=lambda item: (item.entry_ms, -item.score, item.asset)):
                if trade.entry_ms >= free:
                    trades.append(trade)
                    free = trade.exit_ms + BUCKET_MS
            summary = metrics(trades)
            rows.append({"config_id": config.config_id, **asdict(config), "fee_bps_per_side": fee, "event_count": len(events), **{key: value for key, value in summary.items() if not isinstance(value, dict)}})
            if fee == 5.0 and trades:
                ledgers.append(pd.DataFrame([asdict(item) for item in trades]))
        if number % 100 == 0:
            print(json.dumps({"configs_done": number, "configs_total": len(configs)}), flush=True)
    table = pd.DataFrame(rows)
    table.to_csv(output / "PILOT_GRID.csv", index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(output / "PILOT_5BPS_LEDGERS.csv", index=False)
    base = table[table.fee_bps_per_side == 5.0].copy()
    zero = table[table.fee_bps_per_side == 0.0][["config_id", "mean_net_bps", "total_fixed_notional_return"]].rename(columns={"mean_net_bps": "zero_fee_mean_bps", "total_fixed_notional_return": "zero_fee_total_return"})
    stress = table[table.fee_bps_per_side == 10.0][["config_id", "mean_net_bps", "total_fixed_notional_return"]].rename(columns={"mean_net_bps": "ten_fee_mean_bps", "total_fixed_notional_return": "ten_fee_total_return"})
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
        "schema_version": 2,
        "claim_id": "CLM-20260725-2120-CROSS-MARGIN-001",
        "dataset_revision": "TARDIS_PUBLIC_NORMALIZED_SAMPLE_V1",
        "stage": "SYSTEMATIC_SAMPLE_FATAL_EDGE_PILOT",
        "pilot_days": list(days),
        "configurations": len(configs),
        "fatal_edge_pass_count": int(candidates.fatal_edge_pass.sum()),
        "best": candidates.iloc[0].replace({np.nan: None}).to_dict() if len(candidates) else None,
        "development_opened": False,
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "champion_eligible": False,
        "source_records": sources,
    }
    path = output / "PILOT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    (output / "PILOT_RESULT.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    return result


def self_test() -> None:
    index = np.arange(0, 120_000, BUCKET_MS, dtype=np.int64)
    frame = pd.DataFrame(index=index)
    for prefix in ("cm", "um"):
        frame[f"{prefix}_bid"] = 99.9
        frame[f"{prefix}_ask"] = 100.1
        frame[f"{prefix}_bid_amount"] = 100.0
        frame[f"{prefix}_ask_amount"] = 100.0
        frame[f"{prefix}_quote_event_ms"] = index + 99
        frame[f"{prefix}_quote_actual"] = True
        frame[f"{prefix}_mid"] = 100.0
        frame[f"{prefix}_spread"] = 0.2
        frame[f"{prefix}_amount"] = 0.0
        frame[f"{prefix}_signed_amount"] = 0.0
        frame[f"{prefix}_trade_count"] = 0.0
    frame.loc[70_000:70_900, "cm_mid"] = np.linspace(100, 99, 10)
    frame.loc[70_000:70_900, "cm_bid"] = frame.loc[70_000:70_900, "cm_mid"] - 0.1
    frame.loc[70_000:70_900, "cm_ask"] = frame.loc[70_000:70_900, "cm_mid"] + 0.1
    frame.loc[70_000:70_900, "cm_amount"] = 100.0
    frame.loc[70_000:70_900, "cm_signed_amount"] = -90.0
    config = Config("coinm_downside_collateral_cascade", 1000, 2.0, 0.60, 0.50, 100, 3000, 4.0, 2.0)
    events = signals(frame, config, "synthetic", "BTC")
    assert events and all(event.decision_ms % BUCKET_MS == 0 for event in events)
    changed = frame.copy()
    changed.loc[90_000:, "cm_mid"] *= 2.0
    a = [(event.decision_ms, event.side) for event in signals(frame, config, "d", "BTC") if event.decision_ms < 90_000]
    b = [(event.decision_ms, event.side) for event in signals(changed, config, "d", "BTC") if event.decision_ms < 90_000]
    assert a == b
    trades = simulate(frame, events, config, 0.0)
    assert all(trade.entry_ms >= trade.decision_ms + config.latency_ms for trade in trades)
    print("cross-margin Tardis pilot self-test passed")


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
