from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import orjson
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

import run_parent_order_ml as base

COINS = base.COINS
COIN_PRIORITY = base.COIN_PRIORITY
SIDE = base.SIDE
COSTS_BPS = (12.0, 18.0, 24.0)
INITIAL_NAV = 10_000.0
RISK_FRACTION = 0.01
NOTIONAL_CAP_MULTIPLE = 3.0
DECISION_COST_BP = 18.0
MINIMUM_PREDICTED_EDGE_BP = 2.0
TARGET_CLIP_BP = 200.0
PARTITION_BY_DATE = {
    "2025-07-27": "warmup_only",
    "2025-07-28": "train",
    "2025-07-29": "train",
    "2025-07-30": "train",
    "2025-07-31": "train",
    "2025-08-01": "train",
    "2025-08-02": "confirmation",
    "2025-08-03": "confirmation",
    "2025-08-04": "confirmation",
    "2025-08-05": "validation",
    "2025-08-06": "validation",
}
PREVALIDATION_PARTITIONS = {"train", "confirmation"}
VALIDATION_PARTITIONS = {"validation"}
FEATURE_COLUMNS = (
    "same_cloid_three",
    "mean_cadence_error_seconds",
    "log_total_child_notional",
    "log_third_to_first_notional_ratio",
    "directional_run_displacement_bp",
    "directional_market_return_30s_bp",
    "directional_market_return_120s_bp",
    "directional_taker_imbalance_60s",
    "log_parent_notional_share_60s",
)
MODEL_PARAMS = {
    "loss": "squared_error",
    "learning_rate": 0.05,
    "max_iter": 160,
    "max_leaf_nodes": 15,
    "max_depth": 3,
    "min_samples_leaf": 30,
    "l2_regularization": 1.0,
    "random_state": 20260726,
}


class ScreenError(RuntimeError):
    pass


@dataclass(frozen=True)
class SliceChild:
    wallet: str
    coin: str
    side: int
    oid: str
    start_ms: int
    end_ms: int
    price: float
    notional: float
    cloid: str | None


@dataclass(frozen=True)
class SliceEvent:
    event_key: str
    date: str
    partition: str
    coin: str
    side: int
    detection_ms: int
    entry_ms: int
    logical_exit_ms: int
    exit_ms: int
    source_end_ms: int
    entry_price: float
    exit_price: float
    stop_price: float
    stop_distance_bp: float
    gross_return_bp: float
    has_fourth_child: bool
    outcome: str
    unresolved: bool
    features: tuple[float, ...]


@dataclass(frozen=True)
class SliceAction:
    event: SliceEvent
    predicted_gross_bp: float


def write_json(path: Path, value: Any) -> None:
    base.write_json(path, value)


def first_after_unbounded(
    times: np.ndarray, prices: np.ndarray, target_ms: int, tolerance_ms: int = 5000
) -> tuple[int, float, int] | None:
    return base.first_after(times, prices, target_ms, tolerance_ms=tolerance_ms)


def market_volume(
    times: np.ndarray,
    absolute: np.ndarray,
    start_ms: int,
    end_ms: int,
) -> float | None:
    left = int(np.searchsorted(times, start_ms, side="left"))
    right = int(np.searchsorted(times, end_ms, side="left"))
    if right <= left:
        return None
    total = float(np.sum(absolute[left:right]))
    return total if total > 0 else None


def stop_or_state_exit(
    times: np.ndarray,
    prices: np.ndarray,
    entry_index: int,
    side: int,
    stop_price: float,
    logical_exit_ms: int,
    source_end_ms: int,
) -> tuple[str, int, float, bool]:
    index = entry_index
    while index < len(times):
        timestamp = int(times[index])
        if timestamp > min(logical_exit_ms, source_end_ms):
            break
        end = index + 1
        while end < len(times) and int(times[end]) == timestamp:
            end += 1
        group = prices[index:end]
        hit_stop = float(np.min(group)) <= stop_price if side > 0 else float(np.max(group)) >= stop_price
        if hit_stop:
            candidates = group[group <= stop_price] if side > 0 else group[group >= stop_price]
            exit_price = float(candidates[0]) if len(candidates) else stop_price
            return "structural_stop", timestamp, exit_price, False
        index = end
    if logical_exit_ms > source_end_ms:
        return "source_boundary", source_end_ms, stop_price, True
    state_exit = first_after_unbounded(times, prices, logical_exit_ms, tolerance_ms=5000)
    if state_exit is None or state_exit[0] > source_end_ms:
        return "source_boundary", source_end_ms, stop_price, True
    return "parent_state_exit", int(state_exit[0]), float(state_exit[1]), False


def parse_day(
    records: Sequence[base.SourceFile], raw_root: Path, output: Path
) -> tuple[list[SliceEvent], dict[str, Any]]:
    import pyarrow.parquet as pq

    date = records[0].date
    partition = PARTITION_BY_DATE[date]
    source_end_ms = int(np.datetime64(f"{date}T15:59:59.999").astype("datetime64[ms]").astype(np.int64))
    child_accumulator: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    market_raw: dict[str, dict[int, list[Any]]] = {coin: {} for coin in COINS}
    flow_raw: dict[str, list[tuple[int, float, float]]] = {coin: [] for coin in COINS}
    stats: Counter[str] = Counter()

    for record in sorted(records, key=lambda item: item.hour):
        parquet = pq.ParquetFile(raw_root / record.path)
        if "events" not in parquet.schema_arrow.names:
            raise ScreenError(f"missing events column: {record.path}")
        for batch in parquet.iter_batches(batch_size=25_000, columns=["events"]):
            for raw in batch.column(0).to_pylist():
                stats["block_rows"] += 1
                if raw is None:
                    continue
                try:
                    events = orjson.loads(raw)
                except Exception:
                    stats["json_errors"] += 1
                    continue
                if not isinstance(events, list):
                    stats["shape_errors"] += 1
                    continue
                for event in events:
                    stats["event_items"] += 1
                    if (
                        not isinstance(event, list)
                        or len(event) != 2
                        or not isinstance(event[0], str)
                        or not isinstance(event[1], dict)
                    ):
                        stats["shape_errors"] += 1
                        continue
                    wallet, fill = event[0].lower(), event[1]
                    coin = fill.get("coin")
                    if coin not in COINS:
                        continue
                    side = SIDE.get(str(fill.get("side", "")).upper())
                    try:
                        price = float(fill["px"])
                        size = float(fill["sz"])
                        timestamp = int(fill["time"])
                        tid = int(fill["tid"])
                    except Exception:
                        stats["numeric_errors"] += 1
                        continue
                    if not (price > 0 and size > 0 and math.isfinite(price) and math.isfinite(size)):
                        stats["numeric_errors"] += 1
                        continue
                    notional = price * size
                    stats["valid_market_fills"] += 1
                    market_entry = market_raw[str(coin)].get(tid)
                    if market_entry is None:
                        market_raw[str(coin)][tid] = [timestamp, [price]]
                    else:
                        market_entry[0] = min(int(market_entry[0]), timestamp)
                        market_entry[1].append(price)
                    crossed = fill.get("crossed") is True
                    if crossed and side is not None:
                        flow_raw[str(coin)].append((timestamp, side * notional, notional))
                    if not crossed or side is None or base.is_liquidation(fill):
                        continue
                    oid = base.normalize_identifier(fill.get("oid"))
                    if oid is None:
                        stats["invalid_oid"] += 1
                        continue
                    stats["retained_parent_fills"] += 1
                    key = (wallet, str(coin), side, oid)
                    child = child_accumulator.get(key)
                    cloid = base.normalize_identifier(fill.get("cloid"))
                    if child is None:
                        child_accumulator[key] = {
                            "start_ms": timestamp,
                            "end_ms": timestamp,
                            "size": size,
                            "notional": notional,
                            "price_size": price * size,
                            "cloids": Counter([cloid]) if cloid else Counter(),
                        }
                    else:
                        child["start_ms"] = min(int(child["start_ms"]), timestamp)
                        child["end_ms"] = max(int(child["end_ms"]), timestamp)
                        child["size"] += size
                        child["notional"] += notional
                        child["price_size"] += price * size
                        if cloid:
                            child["cloids"][cloid] += 1
                        stats["collapsed_partial_fills"] += 1

    market: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    flow: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for coin in COINS:
        rows = [
            (int(value[0]), int(tid), float(statistics.median(value[1])))
            for tid, value in market_raw[coin].items()
        ]
        rows.sort(key=lambda item: (item[0], item[1]))
        market[coin] = (
            np.asarray([row[0] for row in rows], dtype=np.int64),
            np.asarray([row[2] for row in rows], dtype=np.float64),
        )
        flows = sorted(flow_raw[coin], key=lambda item: item[0])
        flow[coin] = (
            np.asarray([item[0] for item in flows], dtype=np.int64),
            np.asarray([item[1] for item in flows], dtype=np.float64),
            np.asarray([item[2] for item in flows], dtype=np.float64),
        )

    children: list[SliceChild] = []
    for (wallet, coin, side, oid), item in child_accumulator.items():
        size = float(item["size"])
        notional = float(item["notional"])
        if size <= 0 or notional <= 0:
            continue
        cloids: Counter[str] = item["cloids"]
        cloid = cloids.most_common(1)[0][0] if cloids else None
        children.append(
            SliceChild(
                wallet=wallet,
                coin=coin,
                side=side,
                oid=oid,
                start_ms=int(item["start_ms"]),
                end_ms=int(item["end_ms"]),
                price=float(item["price_size"]) / size,
                notional=notional,
                cloid=cloid,
            )
        )
    children.sort(key=lambda row: (row.wallet, row.coin, row.start_ms, row.oid, row.side))
    grouped: dict[tuple[str, str], list[SliceChild]] = defaultdict(list)
    for child in children:
        grouped[(child.wallet, child.coin)].append(child)

    output_events: list[SliceEvent] = []
    candidate_runs = 0
    for (wallet, coin), orders in grouped.items():
        orders.sort(key=lambda row: (row.start_ms, row.oid, row.side))
        for index in range(2, len(orders)):
            first, second, third = orders[index - 2], orders[index - 1], orders[index]
            if not (
                first.side == second.side == third.side
                and 20_000 <= second.start_ms - first.start_ms <= 40_000
                and 20_000 <= third.start_ms - second.start_ms <= 40_000
            ):
                continue
            if index >= 3:
                predecessor = orders[index - 3]
                if (
                    predecessor.side == first.side
                    and 20_000 <= first.start_ms - predecessor.start_ms <= 40_000
                ):
                    continue
            candidate_runs += 1
            detection_ms = third.end_ms
            expiry_ms = third.start_ms + 40_000
            seconds = (detection_ms // 1000) % 86_400
            if seconds < 12 * 3600 + 20 * 60 or seconds >= 15 * 3600 + 50 * 60:
                stats["outside_decision_window"] += 1
                continue
            if detection_ms + 2_000 >= expiry_ms:
                stats["third_child_completed_after_action_window"] += 1
                continue
            fourth: SliceChild | None = None
            if index + 1 < len(orders):
                candidate = orders[index + 1]
                if (
                    candidate.side == third.side
                    and 20_000 <= candidate.start_ms - third.start_ms <= 40_000
                ):
                    fourth = candidate
            times, prices = market[coin]
            entry = first_after_unbounded(times, prices, detection_ms + 2_000)
            if entry is None:
                stats["entry_unavailable"] += 1
                continue
            entry_ms, entry_price, entry_index = entry
            if entry_ms >= expiry_ms:
                stats["entry_after_cadence_expiry"] += 1
                continue
            if fourth is not None and entry_ms >= fourth.start_ms:
                stats["entry_after_fourth_started"] += 1
                continue
            if third.side > 0:
                stop_price = min(first.price, second.price, third.price) * math.exp(-2 / 10_000)
                stop_distance = 10_000 * math.log(entry_price / stop_price)
                geometry_valid = stop_price < entry_price
            else:
                stop_price = max(first.price, second.price, third.price) * math.exp(2 / 10_000)
                stop_distance = 10_000 * math.log(stop_price / entry_price)
                geometry_valid = entry_price < stop_price
            if not geometry_valid or not (0 < stop_distance <= 300):
                stats["invalid_stop_geometry"] += 1
                continue
            price30 = base.last_before(times, prices, detection_ms - 30_000)
            price120 = base.last_before(times, prices, detection_ms - 120_000)
            flow_times, flow_signed, flow_absolute = flow[coin]
            imbalance = base.flow_imbalance(
                flow_times,
                flow_signed,
                flow_absolute,
                detection_ms - 60_000,
                detection_ms,
                third.side,
            )
            absolute_flow = market_volume(
                flow_times, flow_absolute, detection_ms - 60_000, detection_ms
            )
            if price30 is None or price120 is None or imbalance is None or absolute_flow is None:
                stats["history_unavailable"] += 1
                continue
            total_parent_notional = first.notional + second.notional + third.notional
            gaps = (second.start_ms - first.start_ms, third.start_ms - second.start_ms)
            same_cloid = float(
                first.cloid is not None and first.cloid == second.cloid == third.cloid
            )
            features = (
                same_cloid,
                float(np.mean([abs(gap / 1000 - 30) for gap in gaps])),
                math.log1p(total_parent_notional),
                math.log((third.notional + 1.0) / (first.notional + 1.0)),
                third.side * 10_000 * math.log(third.price / first.price),
                third.side * 10_000 * math.log(entry_price / price30),
                third.side * 10_000 * math.log(entry_price / price120),
                imbalance,
                math.log1p(total_parent_notional / absolute_flow),
            )
            if not all(math.isfinite(value) for value in features):
                stats["nonfinite_feature"] += 1
                continue
            logical_exit_ms = (fourth.end_ms + 2_000) if fourth is not None else (expiry_ms + 2_000)
            outcome, exit_ms, exit_price, unresolved = stop_or_state_exit(
                times,
                prices,
                entry_index,
                third.side,
                stop_price,
                logical_exit_ms,
                source_end_ms,
            )
            gross_return = (
                -stop_distance
                if unresolved
                else third.side * 10_000 * math.log(exit_price / entry_price)
            )
            event_key = f"{date}|{coin}|{wallet}|{third.start_ms}|{third.oid}"
            output_events.append(
                SliceEvent(
                    event_key=event_key,
                    date=date,
                    partition=partition,
                    coin=coin,
                    side=third.side,
                    detection_ms=detection_ms,
                    entry_ms=entry_ms,
                    logical_exit_ms=logical_exit_ms,
                    exit_ms=exit_ms,
                    source_end_ms=source_end_ms,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    stop_price=stop_price,
                    stop_distance_bp=stop_distance,
                    gross_return_bp=gross_return,
                    has_fourth_child=fourth is not None,
                    outcome=outcome,
                    unresolved=unresolved,
                    features=features,
                )
            )

    report = {
        "date": date,
        "partition": partition,
        "files": [item.path for item in records],
        "stats": dict(stats),
        "retained_child_orders": len(children),
        "causal_three_child_run_starts": candidate_runs,
        "eligible_events": len(output_events),
        "events_with_fourth_child": sum(event.has_fourth_child for event in output_events),
        "unresolved_events": sum(event.unresolved for event in output_events),
        "market_trade_count": {coin: len(market[coin][0]) for coin in COINS},
    }
    write_json(output / f"PARSE_{date}.json", report)
    print(json.dumps({"parsed_date": date, "events": len(output_events), "runs": candidate_runs}), flush=True)
    return output_events, report


def parse_dates(
    records: Sequence[base.SourceFile], raw_root: Path, output: Path
) -> tuple[list[SliceEvent], dict[str, Any]]:
    grouped: dict[str, list[base.SourceFile]] = defaultdict(list)
    for item in records:
        grouped[item.date].append(item)
    events: list[SliceEvent] = []
    reports: dict[str, Any] = {}
    for date in sorted(grouped):
        day_events, report = parse_day(grouped[date], raw_root, output)
        events.extend(day_events)
        reports[date] = report
    events.sort(key=lambda event: (event.entry_ms, event.event_key))
    return events, reports


def matrix(events: Sequence[SliceEvent]) -> np.ndarray:
    return np.asarray([event.features for event in events], dtype=np.float64)


def fit_model(train: Sequence[SliceEvent]) -> HistGradientBoostingRegressor:
    if len(train) < 500:
        raise ScreenError(f"insufficient training events: {len(train)}/500")
    target = np.clip(
        np.asarray([event.gross_return_bp for event in train], dtype=np.float64),
        -TARGET_CLIP_BP,
        TARGET_CLIP_BP,
    )
    model = HistGradientBoostingRegressor(**MODEL_PARAMS)
    model.fit(matrix(train), target)
    return model


def predictions(model: HistGradientBoostingRegressor, events: Sequence[SliceEvent]) -> np.ndarray:
    if not events:
        return np.asarray([], dtype=np.float64)
    return np.asarray(model.predict(matrix(events)), dtype=np.float64)


def predictive_metrics(
    model: HistGradientBoostingRegressor,
    train: Sequence[SliceEvent],
    events: Sequence[SliceEvent],
    minimum_rows: int,
) -> dict[str, Any]:
    if len(events) < minimum_rows:
        raise ScreenError(f"insufficient prediction rows: {len(events)}/{minimum_rows}")
    actual = np.asarray([event.gross_return_bp for event in events], dtype=np.float64)
    predicted = predictions(model, events)
    baseline_value = float(np.mean([event.gross_return_bp for event in train]))
    baseline = np.full(len(actual), baseline_value, dtype=np.float64)
    correlation = float(spearmanr(predicted, actual).statistic)
    if not math.isfinite(correlation):
        correlation = 0.0
    model_mae = float(mean_absolute_error(actual, predicted))
    baseline_mae = float(mean_absolute_error(actual, baseline))
    model_rmse = float(math.sqrt(mean_squared_error(actual, predicted)))
    baseline_rmse = float(math.sqrt(mean_squared_error(actual, baseline)))
    return {
        "rows": len(events),
        "actual_mean_gross_bp": float(np.mean(actual)),
        "actual_median_gross_bp": float(np.median(actual)),
        "predicted_mean_gross_bp": float(np.mean(predicted)),
        "spearman_correlation": correlation,
        "r2": float(r2_score(actual, predicted)),
        "model_mae": model_mae,
        "baseline_mae": baseline_mae,
        "mae_skill": 1.0 - model_mae / baseline_mae if baseline_mae > 0 else -math.inf,
        "model_rmse": model_rmse,
        "baseline_rmse": baseline_rmse,
        "rmse_skill": 1.0 - model_rmse / baseline_rmse if baseline_rmse > 0 else -math.inf,
        "fourth_child_rate": float(np.mean([event.has_fourth_child for event in events])),
    }


def authorize(
    model: HistGradientBoostingRegressor, events: Sequence[SliceEvent]
) -> list[SliceAction]:
    predicted = predictions(model, events)
    threshold = DECISION_COST_BP + MINIMUM_PREDICTED_EDGE_BP
    return [
        SliceAction(event, float(value))
        for event, value in zip(events, predicted, strict=True)
        if float(value) > threshold
    ]


def replay(
    actions: Sequence[SliceAction],
    cost_bps: float,
    excluded: set[str] | None = None,
    calendar_dates: Sequence[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    excluded = excluded or set()
    ordered = sorted(
        (action for action in actions if action.event.event_key not in excluded),
        key=lambda action: (
            action.event.entry_ms,
            -action.predicted_gross_bp,
            -int(action.event.features[0]),
            COIN_PRIORITY[action.event.coin],
            action.event.event_key,
        ),
    )
    nav = INITIAL_NAV
    peak = nav
    maximum_drawdown = 0.0
    occupied_until = -1
    accepted: list[dict[str, Any]] = []
    for action in ordered:
        event = action.event
        if occupied_until >= 0 and event.entry_ms <= occupied_until:
            continue
        budget_fraction = (event.stop_distance_bp + cost_bps) / 10_000
        if budget_fraction <= 0:
            continue
        notional = min(nav * RISK_FRACTION / budget_fraction, nav * NOTIONAL_CAP_MULTIPLE)
        net_return_bp = event.gross_return_bp - cost_bps
        pnl = notional * net_return_bp / 10_000
        nav_before = nav
        nav += pnl
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, 1.0 - nav / peak if peak > 0 else 1.0)
        occupied_until = event.exit_ms
        accepted.append({
            "event_key": event.event_key,
            "date": event.date,
            "coin": event.coin,
            "side": event.side,
            "entry_ms": event.entry_ms,
            "exit_ms": event.exit_ms,
            "has_fourth_child": event.has_fourth_child,
            "outcome": event.outcome,
            "unresolved": event.unresolved,
            "predicted_gross_bp": action.predicted_gross_bp,
            "stop_distance_bp": event.stop_distance_bp,
            "gross_return_bp": event.gross_return_bp,
            "cost_bps": cost_bps,
            "net_return_bp": net_return_bp,
            "notional": notional,
            "pnl": pnl,
            "nav_before": nav_before,
            "nav_after": nav,
        })
        if nav <= 0:
            break
    positive_pnl = sorted((row["pnl"] for row in accepted if row["pnl"] > 0), reverse=True)
    gross_profit = sum(positive_pnl)
    gross_loss = -sum(row["pnl"] for row in accepted if row["pnl"] < 0)
    dates = sorted(set(calendar_dates or (action.event.date for action in actions)))
    date_returns: dict[str, float] = {}
    for date in dates:
        rows = [row for row in accepted if row["date"] == date]
        if not rows:
            date_returns[date] = 0.0
        else:
            start = rows[0]["nav_before"]
            end = rows[-1]["nav_after"]
            date_returns[date] = end / start - 1.0 if start > 0 else -1.0
    metrics = {
        "cost_bps": cost_bps,
        "trade_count": len(accepted),
        "final_nav": nav,
        "total_return": nav / INITIAL_NAV - 1.0,
        "geometric_sample_day_growth": (
            (nav / INITIAL_NAV) ** (1.0 / len(dates)) - 1.0 if dates and nav > 0 else -1.0
        ),
        "mean_net_trade_bp": float(np.mean([row["net_return_bp"] for row in accepted])) if accepted else None,
        "median_net_trade_bp": float(np.median([row["net_return_bp"] for row in accepted])) if accepted else None,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0),
        "maximum_drawdown": maximum_drawdown,
        "top_five_positive_pnl_share": sum(positive_pnl[:5]) / gross_profit if gross_profit > 0 else 0.0,
        "unresolved_trade_fraction": sum(row["unresolved"] for row in accepted) / len(accepted) if accepted else 0.0,
        "positive_date_count": sum(value > 0 for value in date_returns.values()),
        "date_returns": date_returns,
    }
    return accepted, metrics


def top_winner_exclusions(trades_12: Sequence[dict[str, Any]]) -> set[str]:
    winners = sorted(
        (row for row in trades_12 if row["pnl"] > 0),
        key=lambda row: (-row["pnl"], row["event_key"]),
    )
    if not winners:
        return set()
    count = max(1, int(math.ceil(0.10 * len(winners))))
    return {row["event_key"] for row in winners[:count]}


def evaluate(
    model: HistGradientBoostingRegressor,
    train: Sequence[SliceEvent],
    events: Sequence[SliceEvent],
    stage: str,
) -> dict[str, Any]:
    minimum_rows = 150 if stage == "confirmation" else 60
    prediction = predictive_metrics(model, train, events, minimum_rows)
    actions = authorize(model, events)
    calendar_dates = sorted({event.date for event in events})
    paths: dict[str, Any] = {}
    ledgers: dict[str, list[dict[str, Any]]] = {}
    for cost in COSTS_BPS:
        trades, metrics = replay(actions, cost, calendar_dates=calendar_dates)
        paths[str(int(cost))] = metrics
        ledgers[str(int(cost))] = trades
    exclusions = top_winner_exclusions(ledgers["12"])
    counter_trades, counter_metrics = replay(actions, 18.0, exclusions, calendar_dates)
    paths["18_top10pct_winners_removed"] = counter_metrics
    if stage == "confirmation":
        checks = {
            "spearman_at_least_0_05": prediction["spearman_correlation"] >= 0.05,
            "positive_mae_skill": prediction["mae_skill"] > 0,
            "at_least_60_trades_at_18bp": paths["18"]["trade_count"] >= 60,
            "positive_mean_at_24bp": (paths["24"]["mean_net_trade_bp"] or -math.inf) > 0,
            "positive_median_at_24bp": (paths["24"]["median_net_trade_bp"] or -math.inf) > 0,
            "positive_return_at_24bp": paths["24"]["total_return"] > 0,
            "positive_winner_removed_return_at_18bp": counter_metrics["total_return"] > 0,
            "at_least_two_positive_dates_at_18bp": paths["18"]["positive_date_count"] >= 2,
            "top_five_share_at_most_0_50": paths["18"]["top_five_positive_pnl_share"] <= 0.50,
            "unresolved_fraction_at_most_0_10": paths["18"]["unresolved_trade_fraction"] <= 0.10,
            "sample_day_growth_at_24bp_at_least_0_0025": paths["24"]["geometric_sample_day_growth"] >= 0.0025,
        }
    else:
        checks = {
            "at_least_30_trades_at_18bp": paths["18"]["trade_count"] >= 30,
            "positive_mean_at_24bp": (paths["24"]["mean_net_trade_bp"] or -math.inf) > 0,
            "positive_median_at_24bp": (paths["24"]["median_net_trade_bp"] or -math.inf) > 0,
            "positive_return_at_24bp": paths["24"]["total_return"] > 0,
            "positive_winner_removed_return_at_18bp": counter_metrics["total_return"] > 0,
            "both_dates_positive_at_18bp": paths["18"]["positive_date_count"] >= 2,
            "top_five_share_at_most_0_50": paths["18"]["top_five_positive_pnl_share"] <= 0.50,
            "unresolved_fraction_at_most_0_10": paths["18"]["unresolved_trade_fraction"] <= 0.10,
        }
    return {
        "prediction": prediction,
        "authorized_action_count": len(actions),
        "paths": paths,
        "top_winner_exclusion_count": len(exclusions),
        "gate_checks": checks,
        "gate_passed": all(checks.values()),
        "ledgers": ledgers,
        "counterfactual_18bp_ledger": counter_trades,
    }


def write_event_csv(path: Path, events: Sequence[SliceEvent], predicted: np.ndarray) -> None:
    fields = [
        "event_key", "date", "partition", "coin", "side", "detection_ms", "entry_ms",
        "logical_exit_ms", "exit_ms", "has_fourth_child", "outcome", "unresolved",
        "entry_price", "exit_price", "stop_price", "stop_distance_bp", "gross_return_bp",
        "predicted_gross_bp", *FEATURE_COLUMNS,
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for event, value in zip(events, predicted, strict=True):
            row = {
                "event_key": event.event_key,
                "date": event.date,
                "partition": event.partition,
                "coin": event.coin,
                "side": event.side,
                "detection_ms": event.detection_ms,
                "entry_ms": event.entry_ms,
                "logical_exit_ms": event.logical_exit_ms,
                "exit_ms": event.exit_ms,
                "has_fourth_child": event.has_fourth_child,
                "outcome": event.outcome,
                "unresolved": event.unresolved,
                "entry_price": event.entry_price,
                "exit_price": event.exit_price,
                "stop_price": event.stop_price,
                "stop_distance_bp": event.stop_distance_bp,
                "gross_return_bp": event.gross_return_bp,
                "predicted_gross_bp": float(value),
            }
            row.update({name: event.features[index] for index, name in enumerate(FEATURE_COLUMNS)})
            writer.writerow(row)


def write_trade_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("event_key\n", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def model_contract() -> dict[str, Any]:
    return {
        "one_model_family": True,
        "model_family": "HistGradientBoostingRegressor",
        "hyperparameters": MODEL_PARAMS,
        "feature_columns": FEATURE_COLUMNS,
        "label": "directional gross return from post-detection entry to fourth-child completion or causal 40-second cadence invalidation, with structural stop",
        "direction_lock": True,
        "one_economic_decision_rule": True,
        "decision_cost_bp": DECISION_COST_BP,
        "minimum_predicted_edge_bp": MINIMUM_PREDICTED_EDGE_BP,
        "target_clip_bp_for_model_fit": TARGET_CLIP_BP,
        "cost_paths_bp": COSTS_BPS,
        "one_global_slot": True,
        "elapsed_time_liquidation": False,
        "cadence_expiry_is_signal_invalidation": True,
    }


def strip_ledgers(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {key: item for key, item in value.items() if key not in {"ledgers", "counterfactual_18bp_ledger"}}


def run(
    selection_path: Path,
    prereg_path: Path,
    work_dir: Path,
    output: Path,
    workers: int,
) -> dict[str, Any]:
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    if prereg.get("experiment_id") != "HL-PARENT-SLICE-IMPACT-ML-V1":
        raise ScreenError("unexpected preregistration")
    output.mkdir(parents=True, exist_ok=True)
    raw_root = work_dir / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    source = base.resolve_manifest(selection, output)
    pre_files = [item for item in source if PARTITION_BY_DATE[item.date] in PREVALIDATION_PARTITIONS]
    validation_files = [item for item in source if PARTITION_BY_DATE[item.date] in VALIDATION_PARTITIONS]
    base.download_files(pre_files, selection, raw_root, output / "prevalidation_download", workers)
    pre_events, pre_reports = parse_dates(pre_files, raw_root, output / "prevalidation_parse")
    train = [event for event in pre_events if event.partition == "train"]
    confirmation = [event for event in pre_events if event.partition == "confirmation"]
    try:
        model = fit_model(train)
        confirmation_result = evaluate(model, train, confirmation, "confirmation")
    except ScreenError as exc:
        report = {
            "schema_version": 1,
            "result_id": "RES-20260726-HL-PARENT-SLICE-ML-001",
            "claim_id": "CLM-20260726-1040-HL-WALLET-FLOW-001",
            "experiment_id": "HL-PARENT-SLICE-IMPACT-ML-V1",
            "status": "SAMPLE_OR_MODEL_GATE_INSUFFICIENT",
            "hard_validity": "PASS_PRE_2026_SAMPLE_OR_MODEL_GATE",
            "economic_status": "BELOW_GATE",
            "failure_reason": str(exc),
            "train_event_count": len(train),
            "confirmation_event_count": len(confirmation),
            "prevalidation_reports": pre_reports,
            "validation_file_count_read": 0,
            "validation": None,
            "model_family_count": 1,
            "hyperparameter_grid": False,
            "direction_reversal_allowed": False,
            "one_global_slot": True,
            "strategy_pnl_computed": False,
            "bybit_execution_opened": False,
            "official_2024_2026_opened": False,
            "rank_eligible": False,
            "orders_submitted": False,
            "decision": "RETIRE_PARENT_SLICE_IMPACT_DEPENDENCY_FOR_SAMPLE_OR_MODEL_GATE",
        }
        write_json(output / "RESULT.json", report)
        write_json(output / "MODEL_CONTRACT.json", model_contract())
        return report

    confirmation_predictions = predictions(model, confirmation)
    write_event_csv(output / "CONFIRMATION_EVENTS.csv", confirmation, confirmation_predictions)
    for cost in ("12", "18", "24"):
        write_trade_csv(output / f"CONFIRMATION_TRADES_{cost}BPS.csv", confirmation_result["ledgers"][cost])
    write_trade_csv(
        output / "CONFIRMATION_TRADES_18BPS_TOP10_REMOVED.csv",
        confirmation_result["counterfactual_18bp_ledger"],
    )

    validation_result: dict[str, Any] | None = None
    validation_reports: dict[str, Any] | None = None
    validation_file_count_read = 0
    if confirmation_result["gate_passed"]:
        base.download_files(validation_files, selection, raw_root, output / "validation_download", workers)
        validation_events, validation_reports = parse_dates(
            validation_files, raw_root, output / "validation_parse"
        )
        try:
            validation_result = evaluate(model, train, validation_events, "validation")
        except ScreenError as exc:
            validation_result = {
                "status": "VALIDATION_SAMPLE_OR_MODEL_GATE_INSUFFICIENT",
                "failure_reason": str(exc),
                "gate_passed": False,
            }
        validation_predictions = predictions(model, validation_events)
        write_event_csv(output / "VALIDATION_EVENTS.csv", validation_events, validation_predictions)
        if "ledgers" in validation_result:
            for cost in ("12", "18", "24"):
                write_trade_csv(
                    output / f"VALIDATION_TRADES_{cost}BPS.csv",
                    validation_result["ledgers"][cost],
                )
        validation_file_count_read = len(validation_files)

    validation_passed = bool(validation_result and validation_result.get("gate_passed"))
    report = {
        "schema_version": 1,
        "result_id": "RES-20260726-HL-PARENT-SLICE-ML-001",
        "claim_id": "CLM-20260726-1040-HL-WALLET-FLOW-001",
        "experiment_id": "HL-PARENT-SLICE-IMPACT-ML-V1",
        "status": "VALIDATION_SURVIVOR_REQUIRES_BYBIT_REPLAY" if validation_passed else "TESTED_BELOW_GATE",
        "hard_validity": "PASS_PRE_2026_SAME_VENUE_FATAL_SCREEN",
        "economic_status": "SURVIVOR" if validation_passed else "BELOW_GATE",
        "source_revision": selection["source"]["revision"],
        "source_manifest_sha256": selection["expected_canonical_manifest_sha256"],
        "prevalidation_file_count": len(pre_files),
        "prevalidation_reports": pre_reports,
        "train_event_count": len(train),
        "confirmation_event_count": len(confirmation),
        "confirmation": strip_ledgers(confirmation_result),
        "validation_file_count_read": validation_file_count_read,
        "validation_reports": validation_reports,
        "validation": strip_ledgers(validation_result),
        "model_family_count": 1,
        "hyperparameter_grid": False,
        "feature_count": len(FEATURE_COLUMNS),
        "direction_reversal_allowed": False,
        "one_global_slot": True,
        "bybit_execution_opened": False,
        "official_2024_2026_opened": False,
        "rank_eligible": False,
        "orders_submitted": False,
        "decision": (
            "OPEN_EXACT_BYBIT_BBO_REPLAY_FOR_PARENT_SLICE_IMPACT"
            if validation_passed
            else "RETIRE_PARENT_SLICE_IMPACT_DEPENDENCY_WITHOUT_ADJACENT_TUNING"
        ),
    }
    write_json(output / "RESULT.json", report)
    write_json(output / "MODEL_CONTRACT.json", model_contract())
    print(json.dumps({
        "status": report["status"],
        "confirmation_gate": confirmation_result["gate_passed"],
        "validation_opened": validation_file_count_read > 0,
        "validation_passed": validation_passed,
        "decision": report["decision"],
    }, sort_keys=True), flush=True)
    return report


def self_test() -> None:
    times = np.asarray([1000, 2000, 3000, 4000], dtype=np.int64)
    prices = np.asarray([100.0, 99.0, 101.0, 102.0], dtype=np.float64)
    outcome, exit_ms, exit_price, unresolved = stop_or_state_exit(
        times, prices, 0, 1, 99.5, 3500, 5000
    )
    assert outcome == "structural_stop" and exit_ms == 2000 and exit_price == 99.0 and not unresolved
    assert model_contract()["one_model_family"] is True
    assert model_contract()["direction_lock"] is True
    assert model_contract()["one_economic_decision_rule"] is True
    print("HL_PARENT_SLICE_ML_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--preregistration", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--download-workers", type=int, default=4)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (args.selection, args.preregistration, args.work_dir, args.output)
    if any(value is None for value in required):
        parser.error("run mode requires selection, preregistration, work-dir and output")
    run(args.selection, args.preregistration, args.work_dir, args.output, args.download_workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
