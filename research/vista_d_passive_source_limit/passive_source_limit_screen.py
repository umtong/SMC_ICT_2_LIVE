#!/usr/bin/env python3
"""Purpose-fit short screen for a passive source-level limit after a direct-flow state.

This is a distinct execution hypothesis derived from the retired confirmed-retest
market-entry family. It reconstructs causal 15-minute external pools from public
Bybit trades, classifies the first five seconds after a pool raid, and posts a
resting limit at the consumed source after the state is fully known. The limit
fills only after one-tick penetration. It does not optimize thresholds, targets,
stops, or horizons.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests

BASE = "https://public.bybit.com/trading"
TICK = {"BTCUSDT": 0.1, "ETHUSDT": 0.01}
RISK = 0.03
MIN_NATURAL_R = 0.5
MAKER_ENTRY_BP = 2.0
WARMUP_DAYS = 7


@dataclass(frozen=True)
class Pool:
    pool_id: str
    side: int  # +1 high, -1 low
    price: float
    available_at_ms: int
    swing_time_ms: int


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    symbol: str
    window: str
    state: str
    side: int
    raid_time_ms: int
    decision_time_ms: int
    activation_time_ms: int
    source_pool_id: str
    source_price: float
    target_pool_id: str
    target: float
    stop: float
    state_outward_extreme: float
    signed_progress: float
    signed_flow: float
    outside_dwell: float


def parse_day(value: str) -> date:
    return date.fromisoformat(value)


def day_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def iter_days(start: date, end_inclusive: date) -> Iterable[date]:
    d = start
    while d <= end_inclusive:
        yield d
        d += timedelta(days=1)


def download(session: requests.Session, symbol: str, d: date, root: Path, timeout: int = 120) -> tuple[Path, dict]:
    name = f"{symbol}{d.isoformat()}.csv.gz"
    url = f"{BASE}/{symbol}/{name}"
    path = root / name
    last: Exception | None = None
    for attempt in range(5):
        try:
            h = hashlib.sha256()
            n = 0
            with session.get(url, timeout=timeout, stream=True) as response:
                if response.status_code == 404:
                    raise FileNotFoundError(url)
                response.raise_for_status()
                with path.open("wb") as handle:
                    for chunk in response.iter_content(1 << 20):
                        if chunk:
                            handle.write(chunk)
                            h.update(chunk)
                            n += len(chunk)
            return path, {"url": url, "bytes": n, "sha256": h.hexdigest()}
        except (requests.RequestException, OSError) as exc:
            last = exc
            path.unlink(missing_ok=True)
            if attempt < 4:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed {url}: {last}")


def aggregate_file(path: Path, chunksize: int = 1_000_000) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    reader = pd.read_csv(
        path,
        compression="gzip",
        usecols=["timestamp", "side", "size", "price"],
        dtype={"timestamp": "float64", "side": "string", "size": "float64", "price": "float64"},
        chunksize=chunksize,
        on_bad_lines="error",
    )
    for chunk in reader:
        if chunk.empty:
            continue
        ts = np.floor(chunk.timestamp.to_numpy(float) * 1000.0 + 1e-7).astype("int64")
        bucket = (ts // 500) * 500
        price = chunk.price.to_numpy(float)
        size = chunk["size"].to_numpy(float)
        turnover = price * size
        buy = chunk.side.astype("string").str.casefold().eq("buy").to_numpy()
        enriched = pd.DataFrame(
            {
                "start_time_ms": bucket,
                "price": price,
                "size": size,
                "turnover": turnover,
                "buy_turnover": np.where(buy, turnover, 0.0),
                "sell_turnover": np.where(~buy, turnover, 0.0),
            }
        )
        grouped = enriched.groupby("start_time_ms", sort=True, observed=True)
        parts.append(
            grouped.agg(
                open=("price", "first"),
                high=("price", "max"),
                low=("price", "min"),
                close=("price", "last"),
                volume=("size", "sum"),
                turnover=("turnover", "sum"),
                trade_count=("price", "size"),
                buy_turnover=("buy_turnover", "sum"),
                sell_turnover=("sell_turnover", "sum"),
            ).reset_index()
        )
    if not parts:
        return pd.DataFrame(
            columns=[
                "start_time_ms",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "turnover",
                "trade_count",
                "buy_turnover",
                "sell_turnover",
            ]
        )
    partial = pd.concat(parts, ignore_index=True)
    grouped = partial.groupby("start_time_ms", sort=True, observed=True)
    result = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        turnover=("turnover", "sum"),
        trade_count=("trade_count", "sum"),
        buy_turnover=("buy_turnover", "sum"),
        sell_turnover=("sell_turnover", "sum"),
    ).reset_index()
    result["available_at_ms"] = result.start_time_ms + 500
    return result


def aggregate_15m(micro: pd.DataFrame) -> pd.DataFrame:
    frame = micro.copy()
    frame["bar_ms"] = (frame.start_time_ms // 900_000) * 900_000
    grouped = frame.groupby("bar_ms", sort=True, observed=True)
    result = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        turnover=("turnover", "sum"),
        buckets=("close", "size"),
    ).reset_index()
    result["available_at_ms"] = result.bar_ms + 900_000
    return result


def make_pools(bars: pd.DataFrame, tick: float) -> list[Pool]:
    pools: list[Pool] = []
    highs = bars.high.to_numpy(float)
    lows = bars.low.to_numpy(float)
    for index in range(2, len(bars) - 2):
        available_at = int(bars.iloc[index + 2].available_at_ms)
        swing_time = int(bars.iloc[index].bar_ms)
        if highs[index] > max(highs[index - 2], highs[index - 1], highs[index + 1], highs[index + 2]):
            price = round(highs[index] / tick) * tick
            pools.append(Pool(f"H-{swing_time}-{price:.10g}", 1, float(price), available_at, swing_time))
        if lows[index] < min(lows[index - 2], lows[index - 1], lows[index + 1], lows[index + 2]):
            price = round(lows[index] / tick) * tick
            pools.append(Pool(f"L-{swing_time}-{price:.10g}", -1, float(price), available_at, swing_time))
    return sorted(pools, key=lambda pool: (pool.available_at_ms, pool.swing_time_ms, -pool.side))


def classify_state(micro: pd.DataFrame, index: int, source: float, raid_direction: int) -> dict | None:
    start = int(micro.iloc[index].start_time_ms)
    end = start + 5_000
    window = micro[(micro.start_time_ms >= start) & (micro.start_time_ms < end)]
    if window.empty or int(window.start_time_ms.max()) < end - 500:
        return None
    closes = window.close.to_numpy(float)
    signed_progress = raid_direction * (float(closes[-1]) - source)
    signed_flow = raid_direction * float((window.buy_turnover - window.sell_turnover).sum())
    outside_dwell = float(np.mean(raid_direction * (closes - source) > 0))
    outward_excursion = float(
        (window.high.max() - source) if raid_direction > 0 else (source - window.low.min())
    )
    outward_extreme = float(window.high.max() if raid_direction > 0 else window.low.min())
    if signed_progress > 0 and outside_dwell > 0.5 and signed_flow > 0:
        state = "ACCEPT"
    elif signed_progress <= 0 and outward_excursion > 0:
        state = "REJECT"
    else:
        state = "FLAT"
    return {
        "state": state,
        "decision_time_ms": end,
        "signed_progress": signed_progress,
        "signed_flow": signed_flow,
        "outside_dwell": outside_dwell,
        "outward_extreme": outward_extreme,
        "window": window,
    }


def generate_candidates(
    symbol: str,
    micro: pd.DataFrame,
    pools: list[Pool],
    eval_start_ms: int,
    eval_end_ms: int,
) -> list[Candidate]:
    tick = TICK[symbol]
    consumed: set[str] = set()
    candidates: list[Candidate] = []
    for index, bucket in micro.iterrows():
        timestamp = int(bucket.start_time_ms)
        close = float(bucket.close)
        available = [
            pool for pool in pools if pool.available_at_ms <= timestamp and pool.pool_id not in consumed
        ]
        crossed_high = [pool for pool in available if pool.side > 0 and float(bucket.high) > pool.price]
        crossed_low = [pool for pool in available if pool.side < 0 and float(bucket.low) < pool.price]
        if crossed_high and crossed_low:
            consumed.update(pool.pool_id for pool in crossed_high + crossed_low)
            continue
        if not crossed_high and not crossed_low:
            continue
        raid_direction = 1 if crossed_high else -1
        crossed = crossed_high if crossed_high else crossed_low
        source = min(crossed, key=lambda pool: abs(pool.price - close))
        active_before_retirement = [
            pool for pool in available if pool.pool_id not in {item.pool_id for item in crossed}
        ]
        same_direction = sorted(
            (
                pool
                for pool in active_before_retirement
                if pool.side == raid_direction and raid_direction * (pool.price - source.price) > 0
            ),
            key=lambda pool: raid_direction * pool.price,
        )
        consumed.update(pool.pool_id for pool in crossed)
        if timestamp < eval_start_ms or timestamp >= eval_end_ms:
            continue
        state = classify_state(micro, int(index), source.price, raid_direction)
        if not state or state["state"] == "FLAT":
            continue
        if state["state"] == "ACCEPT":
            side = raid_direction
            target_pool = same_direction[0] if same_direction else None
            stop = float(
                state["window"].low.min() - tick
                if side > 0
                else state["window"].high.max() + tick
            )
        else:
            side = -raid_direction
            opposite = [pool for pool in active_before_retirement if pool.side == -raid_direction]
            if side > 0:
                valid = [pool for pool in opposite if pool.price > source.price]
                target_pool = min(valid, key=lambda pool: pool.price) if valid else None
            else:
                valid = [pool for pool in opposite if pool.price < source.price]
                target_pool = max(valid, key=lambda pool: pool.price) if valid else None
            stop = float(
                state["outward_extreme"] + tick
                if raid_direction > 0
                else state["outward_extreme"] - tick
            )
        if not target_pool:
            continue
        target = float(target_pool.price)
        if side * (target - source.price) <= 0 or side * (source.price - stop) <= 0:
            continue
        candidate_id = hashlib.sha256(
            f"{symbol}|{timestamp}|{source.pool_id}|{state['state']}".encode()
        ).hexdigest()[:16]
        candidates.append(
            Candidate(
                candidate_id,
                symbol,
                "",
                state["state"],
                side,
                timestamp,
                int(state["decision_time_ms"]),
                int(state["decision_time_ms"] + 500),
                source.pool_id,
                float(source.price),
                target_pool.pool_id,
                target,
                stop,
                float(state["outward_extreme"]),
                float(state["signed_progress"]),
                float(state["signed_flow"]),
                float(state["outside_dwell"]),
            )
        )
    return candidates


def natural_geometry(candidate: Candidate, total_cost_bp: float) -> tuple[float, float] | None:
    entry = candidate.source_price
    entry_cost = entry * MAKER_ENTRY_BP / 10_000
    stop_exit_cost = candidate.stop * (total_cost_bp - MAKER_ENTRY_BP) / 10_000
    target_exit_cost = candidate.target * (total_cost_bp - MAKER_ENTRY_BP) / 10_000
    loss = abs(entry - candidate.stop) + entry_cost + stop_exit_cost
    reward = abs(candidate.target - entry) - entry_cost - target_exit_cost
    if loss <= 0 or reward <= 0:
        return None
    return reward / loss, loss


def simulate(candidate: Candidate, micro: pd.DataFrame, eval_end_ms: int, total_cost_bp: float) -> dict:
    tick = TICK[candidate.symbol]
    future = micro[micro.start_time_ms >= candidate.activation_time_ms]
    fill_index = None
    for index, bucket in future.iterrows():
        timestamp = int(bucket.start_time_ms)
        if timestamp >= eval_end_ms:
            break
        stop_hit = (
            float(bucket.low) <= candidate.stop
            if candidate.side > 0
            else float(bucket.high) >= candidate.stop
        )
        target_hit = (
            float(bucket.high) >= candidate.target
            if candidate.side > 0
            else float(bucket.low) <= candidate.target
        )
        penetration = (
            float(bucket.low) <= candidate.source_price - tick
            if candidate.side > 0
            else float(bucket.high) >= candidate.source_price + tick
        )
        if stop_hit or target_hit:
            return {
                "outcome": "UNFILLED_CANCELLED",
                "fill_time_ms": None,
                "exit_time_ms": timestamp,
                "entry": None,
                "exit": None,
                "net_per_unit": 0.0,
            }
        if penetration:
            fill_index = index
            break
    if fill_index is None:
        return {
            "outcome": "UNFILLED",
            "fill_time_ms": None,
            "exit_time_ms": eval_end_ms,
            "entry": None,
            "exit": None,
            "net_per_unit": 0.0,
        }
    entry = candidate.source_price
    fill_time = int(micro.loc[fill_index].start_time_ms)
    observed = micro[micro.start_time_ms < eval_end_ms]
    exit_price = float(observed.iloc[-1].close)
    exit_time = eval_end_ms
    outcome = "MARK"
    for _, bucket in micro.loc[fill_index:].iterrows():
        timestamp = int(bucket.start_time_ms)
        if timestamp >= eval_end_ms:
            break
        stop_hit = (
            float(bucket.low) <= candidate.stop
            if candidate.side > 0
            else float(bucket.high) >= candidate.stop
        )
        target_hit = (
            float(bucket.high) >= candidate.target
            if candidate.side > 0
            else float(bucket.low) <= candidate.target
        )
        if stop_hit:
            exit_price = float(
                min(candidate.stop, float(bucket.open))
                if candidate.side > 0
                else max(candidate.stop, float(bucket.open))
            )
            exit_time = timestamp
            outcome = "STOP"
            break
        if target_hit:
            exit_price = candidate.target
            exit_time = timestamp
            outcome = "TARGET"
            break
    gross = candidate.side * (exit_price - entry)
    fees = (
        entry * MAKER_ENTRY_BP / 10_000
        + exit_price * (total_cost_bp - MAKER_ENTRY_BP) / 10_000
    )
    return {
        "outcome": outcome,
        "fill_time_ms": fill_time,
        "exit_time_ms": exit_time,
        "entry": entry,
        "exit": exit_price,
        "net_per_unit": gross - fees,
    }


def account(
    candidates: list[Candidate],
    micro: pd.DataFrame,
    eval_end_ms: int,
    total_cost_bp: float,
) -> dict:
    nav = 10_000.0
    active_until = -1
    rows: list[dict] = []
    equity = [nav]
    for candidate in sorted(candidates, key=lambda item: (item.activation_time_ms, item.candidate_id)):
        geometry = natural_geometry(candidate, total_cost_bp)
        if not geometry or geometry[0] < MIN_NATURAL_R:
            continue
        if candidate.activation_time_ms < active_until:
            continue
        result = simulate(candidate, micro, eval_end_ms, total_cost_bp)
        if result["outcome"].startswith("UNFILLED"):
            rows.append(
                {
                    **asdict(candidate),
                    "natural_r": geometry[0],
                    **result,
                    "qty": 0.0,
                    "net_pnl": 0.0,
                    "nav_after": nav,
                }
            )
            active_until = max(active_until, int(result["exit_time_ms"]))
            continue
        quantity = nav * RISK / geometry[1]
        pnl = quantity * result["net_per_unit"]
        previous_nav = nav
        nav += pnl
        active_until = int(result["exit_time_ms"])
        equity.append(nav)
        rows.append(
            {
                **asdict(candidate),
                "natural_r": geometry[0],
                **result,
                "qty": quantity,
                "net_pnl": pnl,
                "nav_after": nav,
                "realized_r": pnl / previous_nav / RISK,
            }
        )
    completed = [row for row in rows if row["outcome"] in ("TARGET", "STOP")]
    gross_profit = sum(max(0.0, row["net_pnl"]) for row in completed)
    gross_loss = -sum(min(0.0, row["net_pnl"]) for row in completed)
    peak = equity[0]
    maximum_drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        maximum_drawdown = max(maximum_drawdown, (peak - value) / peak)
    return {
        "final_nav": nav,
        "total_return": nav / 10_000 - 1,
        "completed_trades": len(completed),
        "targets": sum(row["outcome"] == "TARGET" for row in completed),
        "stops": sum(row["outcome"] == "STOP" for row in completed),
        "unfilled": sum(row["outcome"].startswith("UNFILLED") for row in rows),
        "profit_factor": gross_profit / gross_loss if gross_loss else (math.inf if gross_profit else 0.0),
        "max_drawdown": maximum_drawdown,
        "rows": rows,
    }


def run_window(
    symbol: str,
    label: str,
    start: date,
    end: date,
    costs: list[float],
) -> dict:
    fetch_start = start - timedelta(days=WARMUP_DAYS)
    session = requests.Session()
    session.headers["User-Agent"] = "SMC-ICT-purpose-fit-screen/1"
    sources: list[dict] = []
    parts: list[pd.DataFrame] = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for current in iter_days(fetch_start, end):
            path, metadata = download(session, symbol, current, root)
            metadata["date"] = current.isoformat()
            sources.append(metadata)
            parts.append(aggregate_file(path))
            path.unlink(missing_ok=True)
    micro = (
        pd.concat(parts, ignore_index=True)
        .sort_values("start_time_ms")
        .drop_duplicates("start_time_ms", keep="last")
        .reset_index(drop=True)
    )
    bars = aggregate_15m(micro)
    pools = make_pools(bars, TICK[symbol])
    start_ms = day_ms(start)
    end_ms = day_ms(end + timedelta(days=1))
    candidates = [
        Candidate(**{**asdict(candidate), "window": label})
        for candidate in generate_candidates(symbol, micro, pools, start_ms, end_ms)
    ]
    output = {
        "window": label,
        "symbol": symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "source_files": sources,
        "microbar_rows": len(micro),
        "pool_count": len(pools),
        "candidate_count": len(candidates),
        "costs": {},
    }
    for cost in costs:
        result = account(candidates, micro, end_ms, cost)
        output["costs"][str(cost)] = result
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT", choices=sorted(TICK))
    parser.add_argument(
        "--window",
        action="append",
        required=True,
        help="LABEL:YYYY-MM-DD:YYYY-MM-DD",
    )
    parser.add_argument("--cost", action="append", type=float, default=[])
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    costs = arguments.cost or [12.0, 18.0, 24.0]
    arguments.output.mkdir(parents=True, exist_ok=True)
    summaries: list[dict] = []
    for specification in arguments.window:
        label, start, end = specification.split(":")
        result = run_window(arguments.symbol, label, parse_day(start), parse_day(end), costs)
        for cost, values in result["costs"].items():
            rows = values.pop("rows")
            pd.DataFrame(rows).to_csv(
                arguments.output / f"{label}_{cost}bp_trades.csv", index=False
            )
            summaries.append(
                {
                    "window": label,
                    "cost_bp": float(cost),
                    "candidate_count": result["candidate_count"],
                    **values,
                }
            )
        (arguments.output / f"{label}.json").write_text(
            json.dumps(result, indent=2, allow_nan=True), encoding="utf-8"
        )
    summary = pd.DataFrame(summaries)
    summary.to_csv(arguments.output / "summary.csv", index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
