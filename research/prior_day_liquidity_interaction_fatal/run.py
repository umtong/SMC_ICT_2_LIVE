from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

SYMBOLS = ("BTCUSDT", "ETHUSDT")
YEARS = (2021, 2022, 2023)
COSTS_BPS = (12.0, 18.0, 24.0)
RISK = 0.005
CAP = 3.0
RR = 1.5


@dataclass
class EventCandidate:
    event_id: str
    symbol: str
    date: str
    side_level: str
    action: str
    direction: int
    level: float
    midpoint: float
    decision_5m_idx: int
    decision_ms: int
    entry_ms: int
    stop_price: float
    target_price: float
    score: float
    penetration_atr: float
    close_depth_atr: float
    excursion_extreme: float
    state_fail_type: str


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_member(path: Path, member: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        table = pq.read_table(io.BytesIO(archive.read(member)))
    return table.to_pandas()


def source_path(root: Path, symbol: str, year: int) -> Path:
    return root / f"DS-BYBIT-LINEAR-{symbol}-PRE_2024_{year}-CANONICAL-V1.zip"


def load_market(root: Path) -> dict[str, dict[str, pd.DataFrame]]:
    output: dict[str, dict[str, pd.DataFrame]] = {}
    for symbol in SYMBOLS:
        parts: dict[str, list[pd.DataFrame]] = {"1m": [], "5m": [], "funding": []}
        for year in YEARS:
            path = source_path(root, symbol, year)
            if not path.is_file():
                raise FileNotFoundError(path)
            parts["1m"].append(load_member(path, "trade_bars/1m.parquet"))
            parts["5m"].append(load_member(path, "trade_bars/5m.parquet"))
            parts["funding"].append(load_member(path, "streams/funding_events.parquet"))
        one = pd.concat(parts["1m"], ignore_index=True)
        five = pd.concat(parts["5m"], ignore_index=True)
        funding = pd.concat(parts["funding"], ignore_index=True)
        one = one.sort_values("start_time_ms").drop_duplicates("start_time_ms").reset_index(drop=True)
        five = five.sort_values("start_time_ms").drop_duplicates("start_time_ms").reset_index(drop=True)
        funding = funding.sort_values("timestamp_ms").drop_duplicates("timestamp_ms").reset_index(drop=True)
        output[symbol] = {"1m": one, "5m": five, "funding": funding}
    return output


def prepare_5m(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame[frame["is_complete"].astype(bool)].copy()
    df["dt"] = pd.to_datetime(df["start_time_ms"], unit="ms", utc=True)
    df["date"] = df["dt"].dt.floor("D")
    daily = df.groupby("date").agg(
        day_high=("high", "max"),
        day_low=("low", "min"),
        bars=("close", "size"),
    )
    daily = daily[daily["bars"] == 288].copy()
    daily["mid"] = (daily["day_high"] + daily["day_low"]) / 2.0
    prev = daily[["day_high", "day_low", "mid"]].shift(1).rename(
        columns={"day_high": "prev_high", "day_low": "prev_low", "mid": "prev_mid"}
    )
    df = df.join(prev, on="date")
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr20"] = tr.shift(1).rolling(20, min_periods=20).mean()
    return df.reset_index(drop=True)


def build_candidates(symbol: str, frame: pd.DataFrame) -> list[EventCandidate]:
    output: list[EventCandidate] = []
    for date, group in frame.groupby("date", sort=True):
        if len(group) != 288:
            continue
        upper = float(group["prev_high"].iloc[0])
        lower = float(group["prev_low"].iloc[0])
        midpoint = float(group["prev_mid"].iloc[0])
        if not (
            np.isfinite(upper)
            and np.isfinite(lower)
            and np.isfinite(midpoint)
            and upper > midpoint > lower
        ):
            continue

        for level_side in ("upper", "lower"):
            level = upper if level_side == "upper" else lower
            crossed = (
                group["high"].to_numpy(float) >= level
                if level_side == "upper"
                else group["low"].to_numpy(float) <= level
            )
            positions = np.flatnonzero(crossed)
            if len(positions) == 0:
                continue
            start = int(positions[0])
            outside_streak = 0
            extreme = -np.inf if level_side == "upper" else np.inf
            action: str | None = None
            decision_position: int | None = None

            for position in range(start, len(group)):
                row = group.iloc[position]
                extreme = (
                    max(extreme, float(row["high"]))
                    if level_side == "upper"
                    else min(extreme, float(row["low"]))
                )
                outside = (
                    float(row["close"]) > level
                    if level_side == "upper"
                    else float(row["close"]) < level
                )
                if outside:
                    outside_streak += 1
                    if outside_streak >= 2:
                        action = "ACCEPT"
                        decision_position = position
                        break
                else:
                    action = "REJECT"
                    decision_position = position
                    break

            if action is None or decision_position is None:
                continue
            row = group.iloc[decision_position]
            atr = float(row["atr20"])
            if not np.isfinite(atr) or atr <= 0:
                continue
            decision_ms = int(row["available_at_ms"])
            entry_ms = decision_ms + 60_000

            if action == "REJECT":
                direction = -1 if level_side == "upper" else 1
                stop = (
                    extreme * (1.0 + 0.0001)
                    if level_side == "upper"
                    else extreme * (1.0 - 0.0001)
                )
                target = midpoint
                close_depth = (
                    (level - float(row["close"])) / atr
                    if level_side == "upper"
                    else (float(row["close"]) - level) / atr
                )
                penetration = (
                    (extreme - level) / atr
                    if level_side == "upper"
                    else (level - extreme) / atr
                )
                state_fail = "CLOSE_OUTSIDE"
            else:
                direction = 1 if level_side == "upper" else -1
                segment = group.iloc[start : decision_position + 1]
                if level_side == "upper":
                    stop = float(segment["low"].min()) * (1.0 - 0.0001)
                    close_depth = (float(row["close"]) - level) / atr
                    penetration = (extreme - level) / atr
                else:
                    stop = float(segment["high"].max()) * (1.0 + 0.0001)
                    close_depth = (level - float(row["close"])) / atr
                    penetration = (level - extreme) / atr
                target = float("nan")
                state_fail = "CLOSE_INSIDE"

            output.append(
                EventCandidate(
                    event_id=f"{symbol}-{date.date()}-{level_side}-{action}",
                    symbol=symbol,
                    date=str(date.date()),
                    side_level=level_side,
                    action=action,
                    direction=direction,
                    level=level,
                    midpoint=midpoint,
                    decision_5m_idx=int(row.name),
                    decision_ms=decision_ms,
                    entry_ms=entry_ms,
                    stop_price=float(stop),
                    target_price=float(target),
                    score=float(penetration + max(close_depth, 0.0)),
                    penetration_atr=float(penetration),
                    close_depth_atr=float(close_depth),
                    excursion_extreme=float(extreme),
                    state_fail_type=state_fail,
                )
            )
    return output


def arrays(market: dict[str, dict[str, pd.DataFrame]], prepared: dict[str, pd.DataFrame]) -> dict[str, dict[str, np.ndarray]]:
    result: dict[str, dict[str, np.ndarray]] = {}
    for symbol in SYMBOLS:
        one = market[symbol]["1m"]
        funding = market[symbol]["funding"]
        five = prepared[symbol]
        result[symbol] = {
            "t": one["start_time_ms"].to_numpy(np.int64),
            "open": one["open"].to_numpy(float),
            "high": one["high"].to_numpy(float),
            "low": one["low"].to_numpy(float),
            "close": one["close"].to_numpy(float),
            "observed": one["observed"].to_numpy(bool),
            "ft": funding["timestamp_ms"].to_numpy(np.int64),
            "fr": funding["funding_rate"].to_numpy(float),
            "five_available": five["available_at_ms"].to_numpy(np.int64),
            "five_close": five["close"].to_numpy(float),
        }
    return result


def funding_fraction(data: dict[str, np.ndarray], entry_ms: int, exit_ms: int, entry: float, side: int) -> float:
    lo = int(np.searchsorted(data["ft"], entry_ms, side="right"))
    hi = int(np.searchsorted(data["ft"], exit_ms, side="right"))
    if hi <= lo:
        return 0.0
    times = data["ft"][lo:hi]
    rates = data["fr"][lo:hi]
    indices = np.clip(
        np.searchsorted(data["t"], times, side="right") - 1,
        0,
        len(data["t"]) - 1,
    )
    marks = data["close"][indices]
    return float(np.sum(-side * rates * (marks / entry)))


def state_exit_ms(candidate: EventCandidate, data: dict[str, np.ndarray]) -> int | None:
    index = int(np.searchsorted(data["five_available"], candidate.decision_ms, side="right"))
    closes = data["five_close"][index:]
    if candidate.action == "ACCEPT":
        condition = (
            closes < candidate.level
            if candidate.side_level == "upper"
            else closes > candidate.level
        )
    else:
        condition = (
            closes > candidate.level
            if candidate.side_level == "upper"
            else closes < candidate.level
        )
    hits = np.flatnonzero(condition)
    if len(hits) == 0:
        return None
    return int(data["five_available"][index + int(hits[0])] + 60_000)


def simulate(candidate: EventCandidate, data: dict[str, np.ndarray]) -> dict[str, object] | None:
    entry_index = int(np.searchsorted(data["t"], candidate.entry_ms, side="left"))
    if (
        entry_index >= len(data["t"])
        or int(data["t"][entry_index]) != candidate.entry_ms
        or not bool(data["observed"][entry_index])
    ):
        return None
    entry = float(data["open"][entry_index])
    stop = float(candidate.stop_price)
    if candidate.direction == 1:
        if not stop < entry:
            return None
        target = (
            float(candidate.target_price)
            if np.isfinite(candidate.target_price)
            else entry + RR * (entry - stop)
        )
        if not target > entry:
            return None
    else:
        if not stop > entry:
            return None
        target = (
            float(candidate.target_price)
            if np.isfinite(candidate.target_price)
            else entry - RR * (stop - entry)
        )
        if not target < entry:
            return None

    failure_ms = state_exit_ms(candidate, data)
    failure_index = (
        int(np.searchsorted(data["t"], failure_ms, side="left"))
        if failure_ms is not None
        else None
    )
    search_end = min(failure_index, len(data["t"])) if failure_index is not None else len(data["t"])
    highs = data["high"][entry_index:search_end]
    lows = data["low"][entry_index:search_end]
    if candidate.direction == 1:
        stops = np.flatnonzero(lows <= stop)
        targets = np.flatnonzero(highs >= target)
    else:
        stops = np.flatnonzero(highs >= stop)
        targets = np.flatnonzero(lows <= target)
    stop_hit = int(stops[0]) if len(stops) else None
    target_hit = int(targets[0]) if len(targets) else None

    if stop_hit is not None and (target_hit is None or stop_hit <= target_hit):
        exit_index = entry_index + stop_hit
        opened = float(data["open"][exit_index])
        exit_price = min(stop, opened) if candidate.direction == 1 else max(stop, opened)
        reason = "STOP_FIRST_AMBIGUOUS" if stop_hit == target_hit else "STOP"
        completed = True
        exit_ms = int(data["t"][exit_index])
    elif target_hit is not None:
        exit_index = entry_index + target_hit
        exit_price = target
        reason = "TARGET"
        completed = True
        exit_ms = int(data["t"][exit_index])
    elif failure_index is not None and failure_index < len(data["t"]) and bool(data["observed"][failure_index]):
        exit_index = failure_index
        exit_price = float(data["open"][exit_index])
        reason = "STATE_FAILURE"
        completed = True
        exit_ms = int(data["t"][exit_index])
    else:
        exit_index = len(data["t"]) - 1
        exit_price = float(data["close"][exit_index])
        reason = "MARK_END"
        completed = False
        exit_ms = int(data["t"][exit_index] + 60_000)

    gross = candidate.direction * (exit_price / entry - 1.0)
    funding = funding_fraction(data, candidate.entry_ms, exit_ms, entry, candidate.direction)
    return {
        **asdict(candidate),
        "entry_price": entry,
        "stop_price_actual": stop,
        "target_price_actual": target,
        "exit_ms": exit_ms,
        "exit_price": exit_price,
        "exit_reason": reason,
        "completed": completed,
        "gross_fraction": float(gross),
        "funding_fraction": float(funding),
        "stop_fraction": abs(entry - stop) / entry,
        "holding_min": (exit_ms - candidate.entry_ms) / 60_000.0,
    }


def route(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    frame = frame.sort_values(
        ["entry_ms", "score", "symbol", "event_id"],
        ascending=[True, False, True, True],
    )
    selected: list[pd.Series] = []
    free_ms = -1
    for entry_ms, group in frame.groupby("entry_ms", sort=True):
        if int(entry_ms) < free_ms:
            continue
        row = group.sort_values(
            ["score", "symbol", "event_id"],
            ascending=[False, True, True],
        ).iloc[0]
        selected.append(row)
        free_ms = int(row["exit_ms"]) + 60_000
    return pd.DataFrame(selected)


def replay(frame: pd.DataFrame, cost_bps: float) -> tuple[dict[str, float | int], pd.DataFrame]:
    nav = 10_000.0
    peak = nav
    drawdown = 0.0
    ledger: list[dict[str, object]] = []
    cost = cost_bps / 10_000.0
    for _, row in frame.sort_values("entry_ms").iterrows():
        leverage = min(CAP, RISK / max(float(row["stop_fraction"]) + cost, 1e-9))
        account_return = leverage * (
            float(row["gross_fraction"]) + float(row["funding_fraction"]) - cost
        )
        account_return = max(account_return, -1.0)
        before = nav
        nav *= 1.0 + account_return
        peak = max(peak, nav)
        drawdown = max(drawdown, 1.0 - nav / peak)
        ledger.append(
            {
                **row.to_dict(),
                "leverage": leverage,
                "account_return": account_return,
                "nav_before": before,
                "nav_after": nav,
                "pnl": nav - before,
            }
        )
    led = pd.DataFrame(ledger)
    if led.empty:
        return {
            "trades": 0, "end_nav": nav, "multiple": 1.0, "pf": 0.0,
            "median": float("nan"), "mdd": 0.0,
        }, led
    positive = float(led.loc[led["pnl"] > 0, "pnl"].sum())
    negative = float(-led.loc[led["pnl"] < 0, "pnl"].sum())
    return {
        "trades": len(led),
        "end_nav": nav,
        "multiple": nav / 10_000.0,
        "pf": positive / negative if negative > 0 else float("inf"),
        "median": float(led["account_return"].median()),
        "mdd": drawdown,
    }, led


def evaluate(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for action in ("ACCEPT", "REJECT"):
        for year in YEARS:
            source = outcomes[
                (outcomes["action"] == action)
                & (outcomes["entry_year"] == year)
                & outcomes["completed"].astype(bool)
            ].copy()
            for cost in COSTS_BPS:
                selected = route(source)
                metrics, ledger = replay(selected, cost)
                positive = ledger[ledger["pnl"] > 0].sort_values("pnl", ascending=False)
                removed_count = math.ceil(0.10 * len(positive)) if len(positive) else 0
                removed = set(positive.head(removed_count)["event_id"])
                rerouted = route(source[~source["event_id"].isin(removed)])
                winner_removed, _ = replay(rerouted, cost)
                rows.append(
                    {
                        "action": action,
                        "year": year,
                        "cost": int(cost),
                        **metrics,
                        "winner_removed_multiple": winner_removed["multiple"],
                        "winner_removed_trades": winner_removed["trades"],
                        "removed_positive_events": removed_count,
                    }
                )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("/mnt/data"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    market = load_market(args.data_root)
    prepared = {symbol: prepare_5m(market[symbol]["5m"]) for symbol in SYMBOLS}
    data = arrays(market, prepared)
    candidates: list[EventCandidate] = []
    for symbol in SYMBOLS:
        candidates.extend(build_candidates(symbol, prepared[symbol]))

    outcomes = [
        result
        for candidate in candidates
        if (result := simulate(candidate, data[candidate.symbol])) is not None
    ]
    frame = pd.DataFrame(outcomes)
    frame["entry_dt"] = pd.to_datetime(frame["entry_ms"], unit="ms", utc=True)
    frame["entry_year"] = frame["entry_dt"].dt.year
    grid = evaluate(frame)
    grid.to_csv(args.output / "ACTION_YEAR_COST_GRID.csv", index=False)

    raw = frame.groupby(["action", "entry_year"]).agg(
        events=("event_id", "count"),
        gross_mean=("gross_fraction", "mean"),
        gross_median=("gross_fraction", "median"),
        funding_mean=("funding_fraction", "mean"),
        stop_median=("stop_fraction", "median"),
        hold_median_min=("holding_min", "median"),
    ).reset_index()
    raw.to_csv(args.output / "RAW_ACTION_STATS.csv", index=False)

    result = {
        "schema_version": 1,
        "result_id": "RES-20260730-PRIOR-DAY-LIQUIDITY-INTERACTION-FATAL-001",
        "claim_id": "CLM-20260729-ML-LIQUIDITY-INTERACTION-AV-001",
        "status": "RETIRED_EXACT_PRIOR_DAY_INTERACTION_FATAL_SCREEN",
        "candidate_counts": {
            "generated": len(candidates),
            "evaluable": len(frame),
        },
        "grid": grid.to_dict(orient="records"),
        "data": {
            f"{symbol}_{year}": {
                "file": source_path(args.data_root, symbol, year).name,
                "sha256": sha256(source_path(args.data_root, symbol, year)),
            }
            for symbol in SYMBOLS for year in YEARS
        },
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    (args.output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
