from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
import requests

BAR_MS = 300_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
LEADERS = ("BTCUSDT", "ETHUSDT")
BASES = (
    "https://data.binance.vision",
    "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision",
)
PERIODS = {
    "development_2023": (pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")),
    "validation_2024": (pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")),
    "confirmation_2025": (pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")),
}
KLINE_COLUMNS = (
    "open_time_ms", "open", "high", "low", "close", "base_volume",
    "close_time_ms", "quote_volume", "trade_count", "taker_buy_base",
    "taker_buy_quote", "ignore",
)


@dataclass(frozen=True, slots=True)
class Config:
    family: str
    lag: int
    leader_z: float
    gap_z: float
    flow: float
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

    def scale(self, x: float) -> "Costs":
        return Costs(self.entry * x, self.normal_exit * x, self.stop_exit * x, self.funding_buffer * x)


@dataclass(frozen=True, slots=True)
class Market:
    times: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    quote: np.ndarray
    buy_quote: np.ndarray


@dataclass(frozen=True, slots=True)
class Features:
    sigma: np.ndarray
    atr: np.ndarray
    ret: Mapping[int, np.ndarray]
    retz: Mapping[int, np.ndarray]
    tfi: Mapping[int, np.ndarray]


@dataclass(frozen=True, slots=True)
class Events:
    time: np.ndarray
    target: np.ndarray
    bar: np.ndarray
    leader: np.ndarray
    lag: np.ndarray
    leader_side: np.ndarray
    leader_z: np.ndarray
    gap_z: np.ndarray
    leader_flow: np.ndarray
    target_flow: np.ndarray
    target_ret: np.ndarray
    tie: np.ndarray


@dataclass(frozen=True, slots=True)
class Trade:
    config_id: str
    family: str
    signal_ms: int
    entry_ms: int
    exit_ms: int
    leader: str
    target: str
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


def epoch_ms(values: np.ndarray) -> tuple[np.ndarray, int]:
    """Normalize Binance millisecond or microsecond timestamps without float conversion."""
    out = np.asarray(values, dtype=np.int64).copy()
    micro = out > 100_000_000_000_000
    count = int(micro.sum())
    out[micro] //= 1_000
    if np.any(out < 0):
        raise ValueError("negative timestamp")
    return out, count


def months(start: str, end: str) -> list[str]:
    a, b = pd.Period(start, "M"), pd.Period(end, "M")
    if a > b:
        raise ValueError("start after end")
    return [str(x) for x in pd.period_range(a, b, freq="M")]


def fetch(session: requests.Session, path: str) -> tuple[bytes, str]:
    errors: list[str] = []
    for base in BASES:
        for attempt in range(4):
            url = base + path
            try:
                response = session.get(url, timeout=180)
                if response.status_code == 200:
                    return response.content, url
                errors.append(f"{url}: HTTP {response.status_code}")
            except requests.RequestException as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
            time.sleep(2**attempt)
    raise RuntimeError("; ".join(errors[-8:]))


def parse_kline_zip(payload: bytes) -> tuple[pd.DataFrame, int]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV: {names}")
        raw = archive.read(names[0])
    first = raw.splitlines()[0].decode("utf-8-sig").split(",")[0].strip()
    has_header = not first.lstrip("-").isdigit()
    frame = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None).iloc[:, :12]
    if frame.shape[1] != 12:
        raise ValueError("invalid kline width")
    frame.columns = KLINE_COLUMNS
    for column in KLINE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["open_time_ms"], n1 = epoch_ms(frame["open_time_ms"].fillna(-1).to_numpy(np.int64))
    frame["close_time_ms"], n2 = epoch_ms(frame["close_time_ms"].fillna(-1).to_numpy(np.int64))
    return frame, n1 + n2


def download_snapshot(destination: Path, start: str, end: str, symbols: tuple[str, ...] = SYMBOLS) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-causal-research/1.0"
        for symbol in symbols:
            frames, sources = [], []
            for month in months(start, end):
                name = f"{symbol}-5m-{month}.zip"
                path = f"/data/futures/um/monthly/klines/{symbol}/5m/{name}"
                payload, url = fetch(session, path)
                checksum, _ = fetch(session, path + ".CHECKSUM")
                expected = checksum.decode("utf-8-sig").strip().split()[0].lower()
                actual = hashlib.sha256(payload).hexdigest()
                if actual != expected:
                    raise ValueError(f"checksum mismatch {name}")
                frame, repaired = parse_kline_zip(payload)
                frames.append(frame)
                sources.append({
                    "month": month,
                    "url": url,
                    "sha256": actual,
                    "bytes": len(payload),
                    "rows": len(frame),
                    "timestamp_repairs": repaired,
                })
                print(json.dumps({"symbol": symbol, "month": month, "rows": len(frame)}), flush=True)
            merged = pd.concat(frames, ignore_index=True)
            before = len(merged)
            merged = merged.sort_values("open_time_ms").drop_duplicates("open_time_ms", keep="last")
            duplicates = before - len(merged)
            required = ["open", "high", "low", "close", "quote_volume", "taker_buy_quote"]
            finite = np.isfinite(merged[required].to_numpy(float)).all(axis=1)
            nonfinite = int((~finite).sum())
            merged = merged.loc[finite].copy()
            high = merged[["open", "high", "low", "close"]].max(axis=1)
            low = merged[["open", "high", "low", "close"]].min(axis=1)
            envelope = int(((high != merged.high) | (low != merged.low)).sum())
            merged["high"], merged["low"] = high, low
            merged = merged.sort_values("open_time_ms").reset_index(drop=True)
            diffs = np.diff(merged.open_time_ms.to_numpy(np.int64))
            arrays = {
                "open_time_ms": merged.open_time_ms.to_numpy(np.int64),
                "open": merged.open.to_numpy(float),
                "high": merged.high.to_numpy(float),
                "low": merged.low.to_numpy(float),
                "close": merged.close.to_numpy(float),
                "quote_volume": merged.quote_volume.to_numpy(float),
                "taker_buy_quote": merged.taker_buy_quote.to_numpy(float),
            }
            output = destination / f"{symbol}_5m.npz"
            np.savez_compressed(output, **arrays)
            records.append({
                "symbol": symbol,
                "rows": len(merged),
                "start_ms": int(merged.open_time_ms.iloc[0]),
                "end_ms": int(merged.open_time_ms.iloc[-1]),
                "duplicates_removed": int(duplicates),
                "nonfinite_removed": nonfinite,
                "envelope_repairs": envelope,
                "gaps": int((diffs != BAR_MS).sum()),
                "missing_bars": int(np.maximum(diffs // BAR_MS - 1, 0).sum()),
                "snapshot_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "sources": sources,
            })
    manifest = {
        "schema_version": 1,
        "market": "Binance USD-M perpetual futures",
        "dataset": "monthly 5m klines",
        "symbols": list(symbols),
        "start_month": start,
        "end_month": end,
        "causal_availability": "completed bar; entry no earlier than next bar open",
        "revision_rule": "source archives identified by observed SHA-256; replacements are new revisions",
        "records": records,
    }
    (destination / "DATASET_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def load_market(root: Path, symbols: tuple[str, ...] = SYMBOLS) -> Market:
    payload = {symbol: dict(np.load(root / f"{symbol}_5m.npz")) for symbol in symbols}
    start = max(int(payload[symbol]["open_time_ms"][0]) for symbol in symbols)
    end = min(int(payload[symbol]["open_time_ms"][-1]) for symbol in symbols)
    times = np.arange(start, end + BAR_MS, BAR_MS, dtype=np.int64)
    fields = {
        name: np.full((len(symbols), len(times)), np.nan)
        for name in ("open", "high", "low", "close", "quote_volume", "taker_buy_quote")
    }
    for symbol_index, symbol in enumerate(symbols):
        item = payload[symbol]
        positions = np.searchsorted(times, item["open_time_ms"])
        valid = (positions < len(times)) & (times[np.minimum(positions, len(times) - 1)] == item["open_time_ms"])
        for name in fields:
            fields[name][symbol_index, positions[valid]] = item[name][valid]
    return Market(
        times,
        fields["open"],
        fields["high"],
        fields["low"],
        fields["close"],
        fields["quote_volume"],
        fields["taker_buy_quote"],
    )


def prior_beta(x_values: np.ndarray, y_values: np.ndarray, window: int = 2016, min_periods: int = 1008) -> np.ndarray:
    x, y = pd.Series(x_values), pd.Series(y_values)
    mx = x.rolling(window, min_periods=min_periods).mean().shift(1)
    my = y.rolling(window, min_periods=min_periods).mean().shift(1)
    covariance = (x * y).rolling(window, min_periods=min_periods).mean().shift(1) - mx * my
    variance = (x * x).rolling(window, min_periods=min_periods).mean().shift(1) - mx * mx
    return (covariance / variance.replace(0, np.nan)).to_numpy(float)


def make_features(market: Market, lags: tuple[int, ...] = (3, 6, 12)) -> Features:
    log_close = np.log(market.close)
    one_bar = np.full_like(market.close, np.nan)
    one_bar[:, 1:] = log_close[:, 1:] - log_close[:, :-1]
    sigma, atr = np.empty_like(market.close), np.empty_like(market.close)
    for symbol_index in range(len(SYMBOLS)):
        sigma[symbol_index] = pd.Series(one_bar[symbol_index]).rolling(2016, min_periods=1008).std(ddof=0).shift(1).to_numpy()
        previous = np.r_[np.nan, market.close[symbol_index, :-1]]
        true_range = np.maximum(
            market.high[symbol_index] - market.low[symbol_index],
            np.maximum(abs(market.high[symbol_index] - previous), abs(market.low[symbol_index] - previous)),
        )
        atr[symbol_index] = pd.Series(true_range).rolling(288, min_periods=144).mean().shift(1).to_numpy()
    returns, return_z, tfi = {}, {}, {}
    signed_quote = 2 * market.buy_quote - market.quote
    for lag in lags:
        lag_return = np.full_like(market.close, np.nan)
        lag_return[:, lag:] = log_close[:, lag:] - log_close[:, :-lag]
        returns[lag] = lag_return
        return_z[lag] = lag_return / (sigma * math.sqrt(lag))
        flow = np.full_like(market.close, np.nan)
        for symbol_index in range(len(SYMBOLS)):
            quote = pd.Series(market.quote[symbol_index]).rolling(lag, min_periods=lag).sum().to_numpy()
            signed = pd.Series(signed_quote[symbol_index]).rolling(lag, min_periods=lag).sum().to_numpy()
            flow[symbol_index] = np.divide(signed, quote, out=np.full_like(signed, np.nan), where=quote > 0)
        tfi[lag] = flow
    return Features(sigma, atr, returns, return_z, tfi)


def make_events(market: Market, features: Features) -> Events:
    rows, tie = [], 0
    symbol_index = {symbol: i for i, symbol in enumerate(SYMBOLS)}
    for leader in LEADERS:
        leader_index = symbol_index[leader]
        for target in SYMBOLS:
            if target == leader:
                continue
            target_index = symbol_index[target]
            for lag in (3, 6, 12):
                leader_return = features.ret[lag][leader_index]
                target_return = features.ret[lag][target_index]
                leader_z = features.retz[lag][leader_index]
                target_z = features.retz[lag][target_index]
                side = np.sign(leader_z)
                expected = prior_beta(leader_return, target_return) * leader_return
                scale = features.sigma[target_index] * math.sqrt(lag)
                gap = np.divide(
                    side * (expected - target_return),
                    scale,
                    out=np.full_like(expected, np.nan),
                    where=scale > 0,
                )
                leader_flow = side * features.tfi[lag][leader_index]
                target_flow = side * features.tfi[lag][target_index]
                valid = (
                    np.isfinite(leader_z)
                    & np.isfinite(target_z)
                    & np.isfinite(gap)
                    & np.isfinite(leader_flow)
                    & np.isfinite(target_flow)
                    & (abs(leader_z) >= 1.5)
                    & (abs(gap) >= 0.5)
                    & (side != 0)
                )
                bars = np.flatnonzero(valid)
                if not len(bars):
                    continue
                count = len(bars)
                rows.append((
                    market.times[bars],
                    np.full(count, target_index),
                    bars,
                    np.full(count, leader_index),
                    np.full(count, lag),
                    side[bars],
                    abs(leader_z[bars]),
                    gap[bars],
                    leader_flow[bars],
                    target_flow[bars],
                    side[bars] * target_z[bars],
                    np.arange(tie, tie + count),
                ))
                tie += count
    columns = [np.concatenate([row[index] for row in rows]) for index in range(12)]
    order = np.lexsort((columns[11], columns[0]))
    return Events(*(column[order] for column in columns))


def grid() -> list[Config]:
    import itertools

    return [Config(*values) for values in itertools.product(
        ("underreaction_continuation", "overreaction_reversal", "flow_disagreement_reversal"),
        (3, 6, 12),
        (1.5, 2.0, 2.5),
        (0.5, 1.0),
        (0.0, 0.15),
        (1, 3, 6, 12),
        (1.5, 2.5),
    )]


def eligible(events: Events, config: Config) -> np.ndarray:
    base = (
        (events.lag == config.lag)
        & (events.leader_z >= config.leader_z)
        & (events.leader_flow >= 0)
    )
    if config.family == "underreaction_continuation":
        return base & (events.gap_z >= config.gap_z) & (events.target_flow >= config.flow) & (events.target_ret >= -0.25)
    if config.family == "overreaction_reversal":
        return base & (events.gap_z <= -config.gap_z) & (events.target_flow <= -config.flow) & (events.target_ret >= 0.25)
    return base & (events.target_ret >= config.gap_z) & (events.target_flow <= -config.flow)


def simulate(
    market: Market,
    features: Features,
    events: Events,
    config: Config,
    costs: Costs,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[Trade]:
    lower, upper = int(start.value // 1_000_000), int(end.value // 1_000_000)
    candidates = np.flatnonzero(eligible(events, config) & (events.time >= lower) & (events.time < upper))
    if not len(candidates):
        return []
    scores = (
        events.leader_z[candidates]
        + abs(events.gap_z[candidates])
        + np.maximum(events.leader_flow[candidates], 0)
        + abs(events.target_flow[candidates])
    )
    order = np.lexsort((events.tie[candidates], -scores, events.time[candidates]))
    rows = candidates[order]
    trades, free_time, cursor = [], -1, 0
    while cursor < len(rows):
        signal = int(events.time[rows[cursor]])
        group_end = cursor + 1
        while group_end < len(rows) and int(events.time[rows[group_end]]) == signal:
            group_end += 1
        if signal >= free_time:
            for position in range(cursor, group_end):
                row = rows[position]
                bar = int(events.bar[row])
                target_index = int(events.target[row])
                side = int(events.leader_side[row]) if config.family == "underreaction_continuation" else -int(events.leader_side[row])
                entry_index, timeout_index = bar + 1, bar + 1 + config.hold
                if (
                    timeout_index >= len(market.times)
                    or market.times[entry_index] != market.times[bar] + BAR_MS
                    or market.times[timeout_index] - market.times[entry_index] != config.hold * BAR_MS
                ):
                    continue
                entry = float(market.open[target_index, entry_index])
                current_atr = float(features.atr[target_index, bar])
                if not math.isfinite(entry) or not math.isfinite(current_atr) or entry <= 0 or current_atr <= 0:
                    continue
                distance = max(config.stop_atr * current_atr, entry * 0.0015)
                if distance > entry * 0.05:
                    continue
                stop = entry - side * distance
                exit_index = timeout_index
                exit_price = float(market.open[target_index, timeout_index])
                stopped = False
                valid = True
                for next_bar in range(entry_index, timeout_index):
                    open_price = float(market.open[target_index, next_bar])
                    high = float(market.high[target_index, next_bar])
                    low = float(market.low[target_index, next_bar])
                    if not all(math.isfinite(value) for value in (open_price, high, low)):
                        valid = False
                        break
                    if side > 0 and low <= stop:
                        exit_index, exit_price, stopped = next_bar, (open_price if open_price < stop else stop), True
                        break
                    if side < 0 and high >= stop:
                        exit_index, exit_price, stopped = next_bar, (open_price if open_price > stop else stop), True
                        break
                if not valid or not math.isfinite(exit_price):
                    continue
                exit_cost = costs.stop_exit if stopped else costs.normal_exit
                net_fraction = side * (exit_price / entry - 1) - (
                    costs.entry + exit_cost + costs.funding_buffer
                ) / 10_000
                planned_loss = distance / entry + (
                    costs.entry + costs.stop_exit + costs.funding_buffer
                ) / 10_000
                notional = min(0.01 / planned_loss, 5.0)
                score = (
                    events.leader_z[row]
                    + abs(events.gap_z[row])
                    + max(events.leader_flow[row], 0)
                    + abs(events.target_flow[row])
                )
                trades.append(Trade(
                    config.config_id,
                    config.family,
                    signal,
                    int(market.times[entry_index]),
                    int(market.times[exit_index] + BAR_MS),
                    SYMBOLS[int(events.leader[row])],
                    SYMBOLS[target_index],
                    side,
                    float(score),
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
                free_time = int(market.times[exit_index] + BAR_MS)
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
            "n": 0,
            "eligible_days": len(days),
            "trades_per_day": 0.0,
            "mean_net_r": None,
            "top10pct_removed_mean_r": None,
            "geometric_daily_return": 0.0,
            "ending_nav_multiple": 1.0,
            "max_drawdown": 0.0,
            "positive_month_fraction": 0.0,
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
        "single_trade_positive_profit_share": (
            float(positive.max() / positive_sum) if positive_sum > 0 else 1.0
        ),
        "target_contribution": frame.groupby("target").account_return.sum().to_dict(),
        "direction_contribution": frame.groupby("side").account_return.sum().to_dict(),
    }


def passes(summary: Mapping, minimum_trades: int = 100, minimum_frequency: float = 0.20) -> bool:
    def value(name: str, default: float = -math.inf) -> float:
        item = summary.get(name)
        return default if item is None else float(item)

    return (
        int(summary.get("n", 0)) >= minimum_trades
        and value("trades_per_day", 0) >= minimum_frequency
        and value("mean_net_r") > 0
        and value("top10pct_removed_mean_r") > 0
        and value("geometric_daily_return") > 0
        and value("positive_month_fraction", 0) >= 0.5
        and value("single_trade_positive_profit_share", 1) <= 0.2
    )


def stage_score(base: Mapping, stress: Mapping) -> float:
    keys = ("mean_net_r", "top10pct_removed_mean_r", "geometric_daily_return")
    values = [base.get(key) for key in keys] + [stress.get(key) for key in keys]
    return -1e9 if any(item is None for item in values) else float(min(float(item) for item in values))


def run(snapshot: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = snapshot / "DATASET_MANIFEST.json"
    dataset_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    market = load_market(snapshot)
    features = make_features(market)
    events = make_events(market, features)
    configurations = grid()
    selections, rows = [], []
    development_start, development_end = PERIODS["development_2023"]
    validation_start, validation_end = PERIODS["validation_2024"]
    confirmation_start, confirmation_end = PERIODS["confirmation_2025"]
    for family in (
        "underreaction_continuation",
        "overreaction_reversal",
        "flow_disagreement_reversal",
    ):
        ranked = []
        for configuration in (item for item in configurations if item.family == family):
            base_trades = simulate(
                market, features, events, configuration, Costs(),
                development_start, development_end,
            )
            stress_trades = simulate(
                market, features, events, configuration, Costs().scale(1.5),
                development_start, development_end,
            )
            base = metrics(base_trades, development_start, development_end)
            stress = metrics(stress_trades, development_start, development_end)
            score = stage_score(base, stress)
            rows.append({
                "config_id": configuration.config_id,
                **asdict(configuration),
                "development_score": score,
                **{f"dev_{key}": value for key, value in base.items() if not isinstance(value, dict)},
                **{f"dev_1p5x_{key}": value for key, value in stress.items() if not isinstance(value, dict)},
            })
            ranked.append((score, configuration, base, stress))
        ranked.sort(key=lambda item: (item[0], item[1].config_id), reverse=True)
        score, configuration, development, development_stress = ranked[0]
        development_pass = passes(development) and passes(development_stress)
        validation = validation_stress = None
        validation_pass = False
        if development_pass:
            validation = metrics(
                simulate(market, features, events, configuration, Costs(), validation_start, validation_end),
                validation_start,
                validation_end,
            )
            validation_stress = metrics(
                simulate(market, features, events, configuration, Costs().scale(1.5), validation_start, validation_end),
                validation_start,
                validation_end,
            )
            validation_pass = passes(validation) and passes(validation_stress)
        selections.append({
            "family": family,
            "config": asdict(configuration),
            "config_id": configuration.config_id,
            "development_score": score,
            "development_pass": development_pass,
            "validation_pass": validation_pass,
            "development": development,
            "development_1p5x": development_stress,
            "validation": validation,
            "validation_1p5x": validation_stress,
        })
        print(json.dumps({
            "family": family,
            "config_id": configuration.config_id,
            "development_pass": development_pass,
            "validation_pass": validation_pass,
        }), flush=True)
    pd.DataFrame(rows).sort_values(
        ["family", "development_score"], ascending=[True, False]
    ).to_csv(output / "DEVELOPMENT_GRID.csv", index=False)
    promoted = [selection for selection in selections if selection["validation_pass"]]
    confirmation = None
    champion_eligible = False
    reason = "No family passed development and independent validation at base and 1.5x costs."
    if promoted:
        promoted.sort(
            key=lambda selection: min(
                selection["validation"]["geometric_daily_return"],
                selection["validation_1p5x"]["geometric_daily_return"],
            ),
            reverse=True,
        )
        winner = promoted[0]
        configuration = Config(**winner["config"])
        confirmation_base = metrics(
            simulate(market, features, events, configuration, Costs(), confirmation_start, confirmation_end),
            confirmation_start,
            confirmation_end,
        )
        confirmation_stress = metrics(
            simulate(market, features, events, configuration, Costs().scale(1.5), confirmation_start, confirmation_end),
            confirmation_start,
            confirmation_end,
        )
        confirmation = {
            "family": winner["family"],
            "config_id": winner["config_id"],
            "base": confirmation_base,
            "cost_1p5x": confirmation_stress,
        }
        champion_eligible = (
            passes(confirmation_base)
            and passes(confirmation_stress)
            and confirmation_base["geometric_daily_return"] >= 0.01
        )
        reason = (
            "Winner passed the full contract including >=1% daily growth."
            if champion_eligible
            else "A family reached confirmation but failed the >=1% growth and robustness contract."
        )
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-1506-CROSS-ASSET-LEADLAG-001",
        "dataset_fingerprint": dataset_hash,
        "raw_event_count": len(events.time),
        "evaluation_contract": {
            "clock": "completed 5m bars; next-open entry",
            "universe": list(SYMBOLS),
            "global_parent_slots": 1,
            "costs_bps": {"entry": 6, "normal_exit": 6, "stop_exit": 8, "funding_buffer": 1},
            "stress_multiplier": 1.5,
            "risk_diagnostic": 0.01,
            "notional_cap": 5,
            "configurations": len(configurations),
        },
        "family_selections": selections,
        "confirmation": confirmation,
        "champion_eligible": champion_eligible,
        "champion_reason": reason,
    }
    result_path = output / "RESULT.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (output / "RESULT.sha256").write_text(
        hashlib.sha256(result_path.read_bytes()).hexdigest() + "  RESULT.json\n"
    )
    return result


def self_test() -> None:
    values = np.array([1_700_000_000_000, 1_700_000_000_000_123], dtype=np.int64)
    normalized, repaired = epoch_ms(values)
    assert repaired == 1
    assert np.array_equal(
        normalized,
        np.array([1_700_000_000_000, 1_700_000_000_000], dtype=np.int64),
    )
    x = np.arange(1.0, 30.0)
    y = 2 * x
    beta = prior_beta(x, y, 10, 5)
    baseline = beta[20]
    y[20] = 1e6
    changed = prior_beta(x, y, 10, 5)
    assert changed[20] == baseline and changed[21] != baseline

    times = np.arange(20) * BAR_MS
    shape = (4, 20)
    open_price = np.full(shape, 100.0)
    high = np.full(shape, 101.0)
    low = np.full(shape, 99.0)
    close = np.full(shape, 100.0)
    quote = np.full(shape, 1000.0)
    buy = np.full(shape, 500.0)
    open_price[2, 7], high[2, 7], low[2, 7], close[2, 7] = 95.0, 96.0, 94.0, 95.0
    market = Market(times, open_price, high, low, close, quote, buy)
    features = Features(
        np.full(shape, 0.01),
        np.full(shape, 1.0),
        {3: np.full(shape, np.nan)},
        {3: np.full(shape, np.nan)},
        {3: np.full(shape, np.nan)},
    )
    events = Events(
        np.array([times[5]]),
        np.array([2]),
        np.array([5]),
        np.array([0]),
        np.array([3]),
        np.array([1]),
        np.array([3.0]),
        np.array([2.0]),
        np.array([0.2]),
        np.array([0.3]),
        np.array([0.2]),
        np.array([1]),
    )
    config = Config("underreaction_continuation", 3, 1.5, 0.5, 0.0, 3, 1.5)
    trades = simulate(
        market,
        features,
        events,
        config,
        Costs(0, 0, 0, 0),
        pd.Timestamp(0, unit="ms", tz="UTC"),
        pd.Timestamp(times[-1] + BAR_MS, unit="ms", tz="UTC"),
    )
    assert len(trades) == 1
    assert trades[0].stopped and trades[0].stop > 95 and trades[0].exit == 95
    print("self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    download = subparsers.add_parser("download")
    download.add_argument("--destination", type=Path, required=True)
    download.add_argument("--start", default="2023-01")
    download.add_argument("--end", default="2025-12")
    experiment = subparsers.add_parser("run")
    experiment.add_argument("--snapshot", type=Path, required=True)
    experiment.add_argument("--output", type=Path, required=True)
    subparsers.add_parser("self-test")
    args = parser.parse_args()
    if args.command == "download":
        download_snapshot(args.destination, args.start, args.end)
    elif args.command == "run":
        result = run(args.snapshot, args.output)
        print(json.dumps({
            "champion_eligible": result["champion_eligible"],
            "reason": result["champion_reason"],
        }, indent=2))
    else:
        self_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
