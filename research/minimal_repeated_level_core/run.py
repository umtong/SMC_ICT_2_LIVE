from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

SYMBOLS = ("BTCUSDT", "ETHUSDT")
COSTS_BPS = (12.0, 18.0, 24.0)
RISK_FRACTION = 0.005
NOTIONAL_CAP = 3.0
INTERACTION_TOLERANCE = 0.10
REARM_BARS = 4
REARM_RETREAT = 0.50
RETIRE_DISTANCE = 1.25
MODEL_PARAMS = {
    "max_iter": 240,
    "learning_rate": 0.035,
    "max_depth": 3,
    "min_samples_leaf": 80,
    "l2_regularization": 12.0,
    "random_state": 1729,
}
FEATURES = (
    "touch_number",
    "bars_since_prior_touch",
    "prior_max_penetration",
    "prior_max_rejection",
    "penetration",
    "close_location",
    "body_direction",
    "outward_wick",
    "approach_return_1h",
    "approach_return_3h",
    "approach_efficiency_3h",
    "compression_3h",
    "turnover_z_30d",
    "oi_change_5m",
    "oi_change_15m",
    "oi_change_1h",
    "account_ratio_change_5m",
    "account_ratio_change_15m",
    "account_ratio_change_1h",
    "latest_funding",
    "peer_return_1h",
    "peer_return_3h",
    "peer_range_location",
    "peer_oi_change_1h",
    "hour_sin",
    "hour_cos",
    "side_upper",
    "symbol_eth",
    "action_break",
)


@dataclass
class ActionOutcome:
    event_id: str
    action: str
    symbol: str
    decision_ms: int
    entry_ms: int
    exit_ms: int
    entry_price: float
    exit_price: float
    direction: int
    reason: str
    resolved: bool
    gross_return: float
    funding_return: float
    account_return: float
    notional_fraction: float
    stop_distance: float
    holding_hours: float


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_symbol(root: Path, symbol: str, end_exclusive_ms: int) -> dict[str, pd.DataFrame]:
    fifteen = pd.read_pickle(root / symbol / "bars_15m.pkl.gz", compression="gzip")
    one = pd.read_pickle(root / symbol / "bars_1m.pkl.gz", compression="gzip")
    oi = pd.read_pickle(root / symbol / "open_interest_5m.pkl.gz", compression="gzip")
    ratio = pd.read_pickle(root / symbol / "account_ratio_5m.pkl.gz", compression="gzip")
    funding = pd.read_pickle(root / symbol / "funding_events.pkl.gz", compression="gzip")

    fifteen = fifteen[(fifteen["start_time_ms"] < end_exclusive_ms) & fifteen["is_complete"].astype(bool)].copy()
    one = one[(one["start_time_ms"] < end_exclusive_ms) & one["observed"].astype(bool)].copy()
    oi = oi[(oi["timestamp_ms"] < end_exclusive_ms) & oi["observed"].astype(bool)].copy()
    ratio = ratio[(ratio["timestamp_ms"] < end_exclusive_ms) & ratio["observed"].astype(bool)].copy()
    funding = funding[funding["timestamp_ms"] < end_exclusive_ms].copy()

    for frame, key in ((fifteen, "start_time_ms"), (one, "start_time_ms"), (oi, "timestamp_ms"), (ratio, "timestamp_ms"), (funding, "timestamp_ms")):
        frame.sort_values(key, inplace=True)
        frame.drop_duplicates(key, keep="last", inplace=True)
        frame.reset_index(drop=True, inplace=True)

    return {"15m": fifteen, "1m": one, "oi": oi, "ratio": ratio, "funding": funding}


def merge_completed_state(fifteen: pd.DataFrame, oi: pd.DataFrame, ratio: pd.DataFrame) -> pd.DataFrame:
    df = fifteen.copy()
    df["available_at_ms"] = df["available_at_ms"].astype("int64")
    df = df.sort_values("available_at_ms")

    state = pd.DataFrame({"timestamp_ms": oi["timestamp_ms"].astype("int64"), "oi": oi["open_interest"].astype(float)})
    state = pd.merge_asof(
        state.sort_values("timestamp_ms"),
        ratio[["timestamp_ms", "buy_ratio"]].sort_values("timestamp_ms"),
        on="timestamp_ms",
        direction="backward",
    )
    state["oi_change_5m"] = state["oi"].pct_change()
    state["oi_change_15m"] = state["oi"].pct_change(3)
    state["oi_change_1h"] = state["oi"].pct_change(12)
    state["account_ratio_change_5m"] = state["buy_ratio"].pct_change()
    state["account_ratio_change_15m"] = state["buy_ratio"].pct_change(3)
    state["account_ratio_change_1h"] = state["buy_ratio"].pct_change(12)

    df = pd.merge_asof(
        df,
        state[[
            "timestamp_ms", "oi", "buy_ratio", "oi_change_5m", "oi_change_15m", "oi_change_1h",
            "account_ratio_change_5m", "account_ratio_change_15m", "account_ratio_change_1h",
        ]].sort_values("timestamp_ms"),
        left_on="available_at_ms",
        right_on="timestamp_ms",
        direction="backward",
        allow_exact_matches=True,
    )
    return df.drop(columns=["timestamp_ms"], errors="ignore")


def prepare_symbol(data: dict[str, pd.DataFrame], symbol: str) -> pd.DataFrame:
    df = merge_completed_state(data["15m"], data["oi"], data["ratio"])
    df["dt"] = pd.to_datetime(df["start_time_ms"], unit="ms", utc=True)
    df["date"] = df["dt"].dt.floor("D")
    daily = df.groupby("date").agg(day_high=("high", "max"), day_low=("low", "min"), bars=("close", "size"))
    daily = daily[daily["bars"] == 96]
    daily["range"] = daily["day_high"] - daily["day_low"]
    prev = daily[["day_high", "day_low", "range"]].shift(1).rename(
        columns={"day_high": "prev_high", "day_low": "prev_low", "range": "prev_range"}
    )
    df = df.join(prev, on="date")
    df["scale"] = df["prev_range"] / 4.0
    df["return_1h"] = df["close"].pct_change(4)
    df["return_3h"] = df["close"].pct_change(12)
    path = df["close"].diff().abs().rolling(12, min_periods=12).sum().shift(1)
    displacement = (df["close"].shift(1) - df["close"].shift(13)).abs()
    df["efficiency_3h"] = displacement / path.replace(0.0, np.nan)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["compression_3h"] = tr.shift(1).rolling(12, min_periods=12).mean() / tr.shift(13).rolling(96, min_periods=96).median()
    log_turnover = np.log(df["turnover"].where(df["turnover"] > 0))
    prior_mean = log_turnover.shift(1).rolling(96 * 30, min_periods=96 * 10).mean()
    prior_std = log_turnover.shift(1).rolling(96 * 30, min_periods=96 * 10).std()
    df["turnover_z_30d"] = (log_turnover - prior_mean) / prior_std.replace(0.0, np.nan)
    funding = data["funding"].sort_values("available_at_ms")
    df = pd.merge_asof(
        df.sort_values("available_at_ms"),
        funding[["available_at_ms", "funding_rate"]].rename(columns={"funding_rate": "latest_funding"}),
        on="available_at_ms",
        direction="backward",
    )
    df["symbol"] = symbol
    return df.reset_index(drop=True)


def add_peer_state(prepared: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for symbol in SYMBOLS:
        peer = SYMBOLS[1] if symbol == SYMBOLS[0] else SYMBOLS[0]
        left = prepared[symbol].sort_values("available_at_ms").copy()
        right = prepared[peer][["available_at_ms", "return_1h", "return_3h", "close", "prev_low", "prev_high", "oi_change_1h"]].copy()
        right["peer_range_location"] = (right["close"] - right["prev_low"]) / (right["prev_high"] - right["prev_low"])
        right = right.rename(
            columns={
                "return_1h": "peer_return_1h",
                "return_3h": "peer_return_3h",
                "oi_change_1h": "peer_oi_change_1h",
            }
        )
        right = right[["available_at_ms", "peer_return_1h", "peer_return_3h", "peer_range_location", "peer_oi_change_1h"]]
        result[symbol] = pd.merge_asof(left, right.sort_values("available_at_ms"), on="available_at_ms", direction="backward")
    return result


def build_events(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    events: list[dict[str, Any]] = []
    for date, group in df.groupby("date", sort=True):
        group = group.sort_values("start_time_ms").reset_index(drop=True)
        if len(group) != 96:
            continue
        upper = float(group["prev_high"].iloc[0])
        lower = float(group["prev_low"].iloc[0])
        scale = float(group["scale"].iloc[0])
        if not (np.isfinite(upper) and np.isfinite(lower) and np.isfinite(scale) and scale > 0):
            continue
        for side, level in (("upper", upper), ("lower", lower)):
            touch_number = 0
            last_touch: int | None = None
            rearmed = True
            prior_max_penetration = 0.0
            prior_max_rejection = 0.0
            retired = False
            for i, row in group.iterrows():
                close = float(row["close"])
                if side == "upper" and close >= level + RETIRE_DISTANCE * scale:
                    retired = True
                if side == "lower" and close <= level - RETIRE_DISTANCE * scale:
                    retired = True
                if retired:
                    break

                # Rearming may only use already completed bars before the current candidate.
                if last_touch is not None and not rearmed and i - last_touch >= REARM_BARS:
                    history = group.iloc[last_touch + 1 : i]
                    if len(history):
                        if side == "upper" and float(history["low"].min()) <= level - REARM_RETREAT * scale:
                            rearmed = True
                        elif side == "lower" and float(history["high"].max()) >= level + REARM_RETREAT * scale:
                            rearmed = True

                reached = float(row["high"]) >= level - INTERACTION_TOLERANCE * scale if side == "upper" else float(row["low"]) <= level + INTERACTION_TOLERANCE * scale
                if not reached or not rearmed:
                    continue

                touch_number += 1
                bars_since = 999 if last_touch is None else i - last_touch
                current_penetration = max(0.0, (float(row["high"]) - level) / scale) if side == "upper" else max(0.0, (level - float(row["low"])) / scale)
                current_rejection = max(0.0, (level - float(row["close"])) / scale) if side == "upper" else max(0.0, (float(row["close"]) - level) / scale)
                body_range = max(float(row["high"]) - float(row["low"]), 1e-12)
                close_location = (float(row["close"]) - float(row["low"])) / body_range
                if side == "upper":
                    outward_wick = (float(row["high"]) - max(float(row["open"]), float(row["close"]))) / body_range
                else:
                    outward_wick = (min(float(row["open"]), float(row["close"])) - float(row["low"])) / body_range
                hour = pd.Timestamp(row["dt"]).hour + pd.Timestamp(row["dt"]).minute / 60.0
                base = {
                    "event_id": f"{symbol}-{date.date()}-{side}-t{touch_number}",
                    "symbol": symbol,
                    "date": str(date.date()),
                    "year": int(pd.Timestamp(date).year),
                    "side": side,
                    "level": level,
                    "scale": scale,
                    "touch_number": touch_number,
                    "bars_since_prior_touch": bars_since,
                    "prior_max_penetration": prior_max_penetration,
                    "prior_max_rejection": prior_max_rejection,
                    "penetration": current_penetration,
                    "close_location": close_location if side == "upper" else 1.0 - close_location,
                    "body_direction": np.sign(float(row["close"]) - float(row["open"])),
                    "outward_wick": outward_wick,
                    "decision_ms": int(row["available_at_ms"]),
                    "approach_return_1h": float(row["return_1h"]),
                    "approach_return_3h": float(row["return_3h"]),
                    "approach_efficiency_3h": float(row["efficiency_3h"]),
                    "compression_3h": float(row["compression_3h"]),
                    "turnover_z_30d": float(row["turnover_z_30d"]),
                    "oi_change_5m": float(row["oi_change_5m"]),
                    "oi_change_15m": float(row["oi_change_15m"]),
                    "oi_change_1h": float(row["oi_change_1h"]),
                    "account_ratio_change_5m": float(row["account_ratio_change_5m"]),
                    "account_ratio_change_15m": float(row["account_ratio_change_15m"]),
                    "account_ratio_change_1h": float(row["account_ratio_change_1h"]),
                    "latest_funding": float(row["latest_funding"]),
                    "peer_return_1h": float(row["peer_return_1h"]),
                    "peer_return_3h": float(row["peer_return_3h"]),
                    "peer_range_location": float(row["peer_range_location"]),
                    "peer_oi_change_1h": float(row["peer_oi_change_1h"]),
                    "hour_sin": math.sin(2 * math.pi * hour / 24.0),
                    "hour_cos": math.cos(2 * math.pi * hour / 24.0),
                    "side_upper": 1.0 if side == "upper" else 0.0,
                    "symbol_eth": 1.0 if symbol == "ETHUSDT" else 0.0,
                }
                events.append(base)
                prior_max_penetration = max(prior_max_penetration, current_penetration)
                prior_max_rejection = max(prior_max_rejection, current_rejection)
                last_touch = i
                rearmed = False
    return pd.DataFrame(events)


def action_geometry(event: pd.Series, action: str) -> tuple[int, float, float]:
    level = float(event["level"])
    scale = float(event["scale"])
    if event["side"] == "upper":
        return (1, level - scale, level + scale) if action == "BREAK" else (-1, level + scale, level - scale)
    return (-1, level + scale, level - scale) if action == "BREAK" else (1, level - scale, level + scale)


def funding_return(funding: pd.DataFrame, entry_ms: int, exit_ms: int, direction: int) -> float:
    relevant = funding[(funding["timestamp_ms"] > entry_ms) & (funding["timestamp_ms"] <= exit_ms)]
    return float((-direction * relevant["funding_rate"]).sum()) if len(relevant) else 0.0


def simulate_action(event: pd.Series, action: str, symbol_data: dict[str, pd.DataFrame], boundary_ms: int) -> ActionOutcome | None:
    one = symbol_data["1m"]
    activation = int(event["decision_ms"]) + 500
    entry_idx = int(np.searchsorted(one["start_time_ms"].to_numpy(np.int64), activation, side="right"))
    if entry_idx >= len(one):
        return None
    entry_row = one.iloc[entry_idx]
    entry_ms = int(entry_row["start_time_ms"])
    entry = float(entry_row["open"])
    direction, stop, target = action_geometry(event, action)
    if direction == 1 and not stop < entry < target:
        return None
    if direction == -1 and not target < entry < stop:
        return None

    stop_distance = abs(entry - stop) / entry
    full_cost = max(COSTS_BPS) / 10_000.0
    risk_unit = stop_distance + full_cost
    if risk_unit <= 0:
        return None
    notional_fraction = min(NOTIONAL_CAP, RISK_FRACTION / risk_unit)
    times = one["start_time_ms"].to_numpy(np.int64)
    end_idx = int(np.searchsorted(times, boundary_ms, side="left"))
    highs = one["high"].to_numpy(float)[entry_idx:end_idx]
    lows = one["low"].to_numpy(float)[entry_idx:end_idx]
    opens = one["open"].to_numpy(float)[entry_idx:end_idx]
    if direction == 1:
        stops = np.flatnonzero(lows <= stop)
        targets = np.flatnonzero(highs >= target)
    else:
        stops = np.flatnonzero(highs >= stop)
        targets = np.flatnonzero(lows <= target)
    stop_hit = int(stops[0]) if len(stops) else None
    target_hit = int(targets[0]) if len(targets) else None

    if stop_hit is not None and (target_hit is None or stop_hit <= target_hit):
        offset = stop_hit
        open_at = float(opens[offset])
        exit_price = min(open_at, stop) if direction == 1 else max(open_at, stop)
        reason, resolved = "STOP", True
    elif target_hit is not None:
        offset = target_hit
        exit_price = target
        reason, resolved = "TARGET", True
    else:
        if end_idx <= entry_idx:
            return None
        offset = end_idx - entry_idx - 1
        exit_price = float(one.iloc[end_idx - 1]["close"])
        reason, resolved = "BOUNDARY_MARK", False
    exit_ms = int(times[entry_idx + offset])
    gross = direction * (exit_price / entry - 1.0)
    fund = funding_return(symbol_data["funding"], entry_ms, exit_ms, direction)
    return ActionOutcome(
        event_id=str(event["event_id"]),
        action=action,
        symbol=str(event["symbol"]),
        decision_ms=int(event["decision_ms"]),
        entry_ms=entry_ms,
        exit_ms=exit_ms,
        entry_price=entry,
        exit_price=exit_price,
        direction=direction,
        reason=reason,
        resolved=resolved,
        gross_return=gross,
        funding_return=fund,
        account_return=0.0,
        notional_fraction=notional_fraction,
        stop_distance=stop_distance,
        holding_hours=(exit_ms - entry_ms) / 3_600_000.0,
    )


def outcome_rows(events: pd.DataFrame, data: dict[str, dict[str, pd.DataFrame]], years: tuple[int, ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, event in events[events["year"].isin(years)].iterrows():
        boundary_ms = int(pd.Timestamp(f"{int(event['year'])+1}-01-01T00:00:00Z").timestamp() * 1000)
        for action in ("BREAK", "REJECT"):
            out = simulate_action(event, action, data[str(event["symbol"])], boundary_ms)
            if out is None:
                continue
            row = asdict(out)
            for cost_bps in COSTS_BPS:
                net_instrument = out.gross_return + out.funding_return - cost_bps / 10_000.0
                row[f"account_return_{int(cost_bps)}"] = out.notional_fraction * net_instrument
            rows.append(row)
    return pd.DataFrame(rows)


def feature_frame(events: pd.DataFrame, action: str) -> pd.DataFrame:
    frame = events[list(FEATURES[:-1])].copy()
    frame["action_break"] = 1.0 if action == "BREAK" else 0.0
    return frame.replace([np.inf, -np.inf], np.nan)


def fit_predict(events: pd.DataFrame, outcomes: pd.DataFrame) -> tuple[HistGradientBoostingRegressor, pd.DataFrame]:
    outcome_index = outcomes.set_index(["event_id", "action"])
    train_events = events[events["year"] == 2021]
    test_events = events[events["year"] == 2022]
    x_parts, y_parts = [], []
    for action in ("BREAK", "REJECT"):
        x = feature_frame(train_events, action)
        y = []
        keep = []
        for i, event_id in enumerate(train_events["event_id"]):
            key = (event_id, action)
            if key not in outcome_index.index:
                continue
            o = outcome_index.loc[key]
            if isinstance(o, pd.DataFrame):
                o = o.iloc[0]
            if not bool(o["resolved"]):
                continue
            keep.append(i)
            y.append(float(o["account_return_24"]))
        x_parts.append(x.iloc[keep])
        y_parts.extend(y)
    x_train = pd.concat(x_parts, ignore_index=True)
    y_train = np.asarray(y_parts, float)
    model = HistGradientBoostingRegressor(**MODEL_PARAMS)
    model.fit(x_train, y_train)

    predictions: list[dict[str, Any]] = []
    for action in ("BREAK", "REJECT"):
        scores = model.predict(feature_frame(test_events, action))
        for event_id, score in zip(test_events["event_id"], scores):
            predictions.append({"event_id": event_id, "action": action, "predicted_account_return_24": float(score)})
    return model, pd.DataFrame(predictions)


def select_account(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    year: int,
    cost_bps: float,
    policy: str,
    predictions: pd.DataFrame | None = None,
    removed_event_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    removed_event_ids = removed_event_ids or set()
    event_year = events[events["year"] == year].copy()
    outcome_index = outcomes.set_index(["event_id", "action"])
    pred_index = predictions.set_index(["event_id", "action"]) if predictions is not None else None
    candidates: list[dict[str, Any]] = []
    for _, event in event_year.iterrows():
        if event["event_id"] in removed_event_ids:
            continue
        if policy in ("BREAK", "REJECT"):
            action, score = policy, float(event["penetration"] + event["touch_number"] * 1e-6)
        elif policy == "MODEL":
            scores = {}
            for action_name in ("BREAK", "REJECT"):
                key = (event["event_id"], action_name)
                if key in pred_index.index:
                    p = pred_index.loc[key]
                    if isinstance(p, pd.DataFrame):
                        p = p.iloc[0]
                    scores[action_name] = float(p["predicted_account_return_24"])
            if not scores:
                continue
            action, score = max(scores.items(), key=lambda x: (x[1], x[0] == "BREAK"))
            if score <= 0:
                continue
        elif policy == "ORACLE":
            scores = {}
            for action_name in ("BREAK", "REJECT"):
                key = (event["event_id"], action_name)
                if key in outcome_index.index:
                    o = outcome_index.loc[key]
                    if isinstance(o, pd.DataFrame):
                        o = o.iloc[0]
                    if bool(o["resolved"]):
                        scores[action_name] = float(o[f"account_return_{int(cost_bps)}"])
            if not scores:
                continue
            action, score = max(scores.items(), key=lambda x: (x[1], x[0] == "BREAK"))
            if score <= 0:
                continue
        else:
            raise ValueError(policy)
        key = (event["event_id"], action)
        if key not in outcome_index.index:
            continue
        outcome = outcome_index.loc[key]
        if isinstance(outcome, pd.DataFrame):
            outcome = outcome.iloc[0]
        candidates.append(
            {
                "event_id": str(event["event_id"]),
                "symbol": str(event["symbol"]),
                "side": str(event["side"]),
                "touch_number": int(event["touch_number"]),
                "decision_ms": int(event["decision_ms"]),
                "entry_ms": int(outcome["entry_ms"]),
                "exit_ms": int(outcome["exit_ms"]),
                "action": action,
                "score": float(score),
                "resolved": bool(outcome["resolved"]),
                "reason": str(outcome["reason"]),
                "account_return": float(outcome[f"account_return_{int(cost_bps)}"]),
                "holding_hours": float(outcome["holding_hours"]),
            }
        )

    candidates.sort(key=lambda x: (x["decision_ms"], -x["score"], x["symbol"], x["side"]))
    trades: list[dict[str, Any]] = []
    busy_until = -1
    index = 0
    while index < len(candidates):
        decision_ms = candidates[index]["decision_ms"]
        simultaneous: list[dict[str, Any]] = []
        while index < len(candidates) and candidates[index]["decision_ms"] == decision_ms:
            simultaneous.append(candidates[index])
            index += 1
        if decision_ms < busy_until:
            continue
        chosen = max(simultaneous, key=lambda x: (x["score"], x["symbol"] == "BTCUSDT", x["side"] == "upper"))
        trades.append(chosen)
        busy_until = chosen["exit_ms"] + 1
    return trades


def account_metrics(trades: list[dict[str, Any]], stage_start_ms: int, stage_end_ms: int) -> dict[str, Any]:
    if not trades:
        return {
            "trade_count": 0,
            "completed_trade_count": 0,
            "final_multiple": 1.0,
            "total_return": 0.0,
            "profit_factor": None,
            "median_completed_return": None,
            "mean_completed_return": None,
            "maximum_drawdown": 0.0,
            "top5_positive_share": None,
            "holding_hours_median": None,
            "slot_occupancy": 0.0,
        }
    nav = 1.0
    peak = 1.0
    mdd = 0.0
    completed_returns: list[float] = []
    all_returns: list[float] = []
    holding: list[float] = []
    occupied_ms = 0
    for trade in trades:
        r = float(trade["account_return"])
        all_returns.append(r)
        nav *= 1.0 + r
        peak = max(peak, nav)
        mdd = max(mdd, 1.0 - nav / peak)
        if trade["resolved"]:
            completed_returns.append(r)
        holding.append(float(trade["holding_hours"]))
        occupied_ms += max(0, min(int(trade["exit_ms"]), stage_end_ms) - max(int(trade["entry_ms"]), stage_start_ms))
    cr = np.asarray(completed_returns, float)
    positives = cr[cr > 0]
    negatives = -cr[cr < 0]
    pf_infinite = bool(len(positives) and (not len(negatives) or negatives.sum() <= 0))
    pf = float(positives.sum() / negatives.sum()) if len(negatives) and negatives.sum() > 0 else None
    top5 = float(np.sort(positives)[-5:].sum() / positives.sum()) if len(positives) and positives.sum() > 0 else None
    return {
        "trade_count": len(trades),
        "completed_trade_count": len(completed_returns),
        "final_multiple": float(nav),
        "total_return": float(nav - 1.0),
        "profit_factor": pf,
        "profit_factor_infinite": pf_infinite,
        "median_completed_return": float(np.median(cr)) if len(cr) else None,
        "mean_completed_return": float(np.mean(cr)) if len(cr) else None,
        "maximum_drawdown": float(mdd),
        "top5_positive_share": top5,
        "holding_hours_median": float(np.median(holding)) if holding else None,
        "slot_occupancy": float(occupied_ms / max(1, stage_end_ms - stage_start_ms)),
        "positive_completed": int((cr > 0).sum()) if len(cr) else 0,
        "negative_completed": int((cr < 0).sum()) if len(cr) else 0,
    }


def lower_tail_diagnostics(trades: list[dict[str, Any]], seed: int = 1729, draws: int = 100_000) -> dict[str, Any]:
    """Deterministic diagnostics only; never used for model or policy selection."""
    completed = [t for t in trades if bool(t["resolved"])]
    if not completed:
        return {
            "seed": seed,
            "draws": draws,
            "monthly_block": None,
            "event_bootstrap": None,
        }
    rng = np.random.default_rng(seed)
    returns = np.asarray([float(t["account_return"]) for t in completed], dtype=float)
    logs = np.log1p(returns)
    months = pd.to_datetime([int(t["entry_ms"]) for t in completed], unit="ms", utc=True).tz_localize(None).to_period("M")
    month_index = pd.period_range("2022-01", "2022-12", freq="M")
    monthly_logs = np.asarray([logs[np.asarray(months == m)].sum() for m in month_index], dtype=float)

    month_draws = rng.choice(monthly_logs, size=(draws, len(monthly_logs)), replace=True).sum(axis=1)
    event_draws = rng.choice(logs, size=(draws, len(logs)), replace=True).sum(axis=1)

    def summarize(samples: np.ndarray) -> dict[str, float]:
        return {
            "q01_log_growth": float(np.quantile(samples, 0.01)),
            "q01_multiple": float(np.exp(np.quantile(samples, 0.01))),
            "q05_log_growth": float(np.quantile(samples, 0.05)),
            "q05_multiple": float(np.exp(np.quantile(samples, 0.05))),
            "median_log_growth": float(np.median(samples)),
            "median_multiple": float(np.exp(np.median(samples))),
            "probability_positive": float(np.mean(samples > 0.0)),
        }

    return {
        "seed": seed,
        "draws": draws,
        "ordinary_log_growth": float(logs.sum()),
        "ordinary_multiple": float(np.exp(logs.sum())),
        "monthly_log_returns": [float(x) for x in monthly_logs],
        "monthly_block": summarize(month_draws),
        "event_bootstrap": summarize(event_draws),
        "interpretation": "Diagnostic only. Negative lower-tail multiples cannot select or retune the policy.",
    }

def winner_removed_account(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    predictions: pd.DataFrame,
    year: int,
    cost_bps: float,
    ordinary_trades: list[dict[str, Any]],
) -> tuple[set[str], list[dict[str, Any]], dict[str, Any]]:
    positive = [t for t in ordinary_trades if t["resolved"] and t["account_return"] > 0]
    count = max(1, int(math.ceil(0.10 * len(positive)))) if positive else 0
    removed = {t["event_id"] for t in sorted(positive, key=lambda x: x["account_return"], reverse=True)[:count]}
    rerouted = select_account(events, outcomes, year, cost_bps, "MODEL", predictions, removed)
    start = int(pd.Timestamp(f"{year}-01-01T00:00:00Z").timestamp() * 1000)
    end = int(pd.Timestamp(f"{year+1}-01-01T00:00:00Z").timestamp() * 1000)
    return removed, rerouted, account_metrics(rerouted, start, end)


def test_semantics() -> None:
    # Geometry is symmetric and action directions invert at lower levels.
    upper = pd.Series({"side": "upper", "level": 100.0, "scale": 10.0})
    lower = pd.Series({"side": "lower", "level": 100.0, "scale": 10.0})
    assert action_geometry(upper, "BREAK") == (1, 90.0, 110.0)
    assert action_geometry(upper, "REJECT") == (-1, 110.0, 90.0)
    assert action_geometry(lower, "BREAK") == (-1, 110.0, 90.0)
    assert action_geometry(lower, "REJECT") == (1, 90.0, 110.0)

    # Activation must use the first strictly later minute, never the decision minute.
    times = np.array([0, 60_000, 120_000], dtype=np.int64)
    activation = 60_000 + 500
    assert int(np.searchsorted(times, activation, side="right")) == 2

    # A wide bar cannot both establish retreat and fire a rearmed touch in the same completed bar.
    synthetic = pd.DataFrame(
        {
            "date": [pd.Timestamp("2022-01-02", tz="UTC")] * 6,
            "prev_high": [100.0] * 6,
            "prev_low": [60.0] * 6,
            "scale": [10.0] * 6,
            "open": [95.0, 98.0, 98.0, 98.0, 98.0, 97.0],
            "high": [101.0, 99.0, 99.0, 99.0, 101.0, 98.0],
            "low": [94.0, 96.0, 96.0, 96.0, 93.0, 96.0],
            "close": [100.0, 98.0, 97.0, 96.0, 94.0, 97.0],
            "available_at_ms": np.arange(6) * 900_000 + 900_000,
            "return_1h": [0.0] * 6,
            "return_3h": [0.0] * 6,
            "efficiency_3h": [0.0] * 6,
            "compression_3h": [0.0] * 6,
            "turnover_z_30d": [0.0] * 6,
            "oi_change_5m": [0.0] * 6,
            "oi_change_15m": [0.0] * 6,
            "oi_change_1h": [0.0] * 6,
            "account_ratio_change_5m": [0.0] * 6,
            "account_ratio_change_15m": [0.0] * 6,
            "account_ratio_change_1h": [0.0] * 6,
            "latest_funding": [0.0] * 6,
            "peer_return_1h": [0.0] * 6,
            "peer_return_3h": [0.0] * 6,
            "peer_range_location": [0.5] * 6,
            "peer_oi_change_1h": [0.0] * 6,
            "hour_sin": [0.0] * 6,
            "hour_cos": [1.0] * 6,
        }
    )
    # Fill to a complete 96-row day with inert bars; only the first event should fire.
    tail = pd.concat([synthetic.iloc[[-1]].copy() for _ in range(90)], ignore_index=True)
    tail["available_at_ms"] = np.arange(6, 96) * 900_000 + 900_000
    synthetic = pd.concat([synthetic, tail], ignore_index=True)
    rearm_events = build_events("BTCUSDT", synthetic)
    assert len(rearm_events[rearm_events["side"] == "upper"]) == 1

    # Winner deletion removes at least one event only when a positive winner exists.
    dummy = [
        {"resolved": True, "account_return": 0.01, "event_id": "a"},
        {"resolved": True, "account_return": -0.01, "event_id": "b"},
    ]
    positives = [x for x in dummy if x["resolved"] and x["account_return"] > 0]
    assert max(1, int(math.ceil(0.1 * len(positives)))) == 1


def run(root: Path, output: Path, end_year: int) -> dict[str, Any]:
    end_exclusive_ms = int(pd.Timestamp(f"{end_year+1}-01-01T00:00:00Z").timestamp() * 1000)
    market = {symbol: load_symbol(root, symbol, end_exclusive_ms) for symbol in SYMBOLS}
    prepared = {symbol: prepare_symbol(market[symbol], symbol) for symbol in SYMBOLS}
    prepared = add_peer_state(prepared)
    events = pd.concat([build_events(symbol, prepared[symbol]) for symbol in SYMBOLS], ignore_index=True)
    events = events.replace([np.inf, -np.inf], np.nan)
    outcomes = outcome_rows(events, market, tuple(range(2021, end_year + 1)))
    _, predictions_2022 = fit_predict(events, outcomes)

    train_events = events[events["year"] == 2021]
    outcome_index = outcomes.set_index(["event_id", "action"])
    y_train = []
    for action in ("BREAK", "REJECT"):
        for event_id in train_events["event_id"]:
            key = (event_id, action)
            if key in outcome_index.index:
                outcome = outcome_index.loc[key]
                if isinstance(outcome, pd.DataFrame):
                    outcome = outcome.iloc[0]
                if bool(outcome["resolved"]):
                    y_train.append(float(outcome["account_return_24"]))

    predicted_rows = []
    test_events = events[events["year"] == 2022]
    pred_index = predictions_2022.set_index(["event_id", "action"])
    for action in ("BREAK", "REJECT"):
        for event_id in test_events["event_id"]:
            key = (event_id, action)
            if key not in pred_index.index or key not in outcome_index.index:
                continue
            p = pred_index.loc[key]
            outcome = outcome_index.loc[key]
            if isinstance(p, pd.DataFrame):
                p = p.iloc[0]
            if isinstance(outcome, pd.DataFrame):
                outcome = outcome.iloc[0]
            if not bool(outcome["resolved"]):
                continue
            predicted_rows.append((float(p["predicted_account_return_24"]), float(outcome["account_return_24"]), action))
    pred = np.asarray([x[0] for x in predicted_rows], float)
    actual = np.asarray([x[1] for x in predicted_rows], float)
    actions = np.asarray([x[2] for x in predicted_rows], object)
    train_action_means: dict[str, float] = {}
    train_outcome_index = outcomes.set_index(["event_id", "action"])
    for action in ("BREAK", "REJECT"):
        vals = []
        for event_id in train_events["event_id"]:
            key = (event_id, action)
            if key in train_outcome_index.index:
                o = train_outcome_index.loc[key]
                if isinstance(o, pd.DataFrame):
                    o = o.iloc[0]
                if bool(o["resolved"]):
                    vals.append(float(o["account_return_24"]))
        train_action_means[action] = float(np.mean(vals)) if vals else 0.0
    constant = np.asarray([train_action_means[a] for a in actions], float)
    rho = float(spearmanr(pred, actual, nan_policy="omit").statistic) if len(actual) > 1 else None
    positive_mask = pred > 0
    model_diagnostics = {
        "train_resolved_actions": int(len(y_train)),
        "test_resolved_actions": int(len(actual)),
        "model_mae": float(mean_absolute_error(actual, pred)) if len(actual) else None,
        "constant_mae": float(mean_absolute_error(actual, constant)) if len(actual) else None,
        "model_mse": float(mean_squared_error(actual, pred)) if len(actual) else None,
        "constant_mse": float(mean_squared_error(actual, constant)) if len(actual) else None,
        "spearman": rho,
        "positive_prediction_count": int(positive_mask.sum()),
        "positive_prediction_realized_mean": float(actual[positive_mask].mean()) if positive_mask.any() else None,
        "positive_prediction_win_rate": float((actual[positive_mask] > 0).mean()) if positive_mask.any() else None,
        "train_action_means": train_action_means,
    }

    accounts: dict[str, Any] = {}
    year = 2022
    stage_start_ms = int(pd.Timestamp("2022-01-01T00:00:00Z").timestamp() * 1000)
    stage_end_ms = int(pd.Timestamp("2023-01-01T00:00:00Z").timestamp() * 1000)
    for policy in ("BREAK", "REJECT", "MODEL", "ORACLE"):
        accounts[policy] = {}
        for cost in COSTS_BPS:
            trades = select_account(events, outcomes, year, cost, policy, predictions_2022 if policy == "MODEL" else None)
            metrics = account_metrics(trades, stage_start_ms, stage_end_ms)
            accounts[policy][str(int(cost))] = {"metrics": metrics, "trades": trades}

    ordinary_model_24 = accounts["MODEL"]["24"]["trades"]
    removed_ids, rerouted_trades, rerouted_metrics = winner_removed_account(
        events, outcomes, predictions_2022, 2022, 24.0, ordinary_model_24
    )
    lower_tail = lower_tail_diagnostics(ordinary_model_24)

    model_18 = accounts["MODEL"]["18"]["metrics"]
    model_24 = accounts["MODEL"]["24"]["metrics"]
    gate = {
        "at_least_100_completed_trades": model_24["completed_trade_count"] >= 100,
        "positive_18bp": model_18["final_multiple"] > 1.0,
        "positive_24bp": model_24["final_multiple"] > 1.0,
        "pf_above_one": model_24["profit_factor"] is not None and model_24["profit_factor"] > 1.0,
        "positive_median": model_24["median_completed_return"] is not None and model_24["median_completed_return"] > 0.0,
        "winner_removed_positive": rerouted_metrics["final_multiple"] > 1.0,
    }
    gate["passed"] = all(gate.values())

    summary = {
        "schema_version": 1,
        "result_id": "RES-20260730-MINIMAL-REPEATED-LEVEL-CORE-001",
        "claim_id": "CLM-20260730-MINIMAL-REPEATED-LEVEL-CORE-001",
        "evaluated_through": "2022-12-31T23:59:59Z",
        "opened_2023": False,
        "opened_official_2024_2026": False,
        "event_counts": events.groupby(["year", "symbol", "side"])["event_id"].count().rename("count").reset_index().to_dict("records"),
        "touch_counts_2022": events[events["year"] == 2022].groupby("touch_number")["event_id"].count().to_dict(),
        "action_outcomes": int(len(outcomes)),
        "model_diagnostics": model_diagnostics,
        "accounts": {
            policy: {cost: payload["metrics"] for cost, payload in costs.items()}
            for policy, costs in accounts.items()
        },
        "winner_removal_24bp": {
            "removed_event_ids": sorted(removed_ids),
            "removed_count": len(removed_ids),
            "metrics": rerouted_metrics,
        },
        "gate": gate,
        "status": "PRE2024_2022_GATE_PASS" if gate["passed"] else "RETIRED_PRE2024_SPARSE_MODEL_ONLY_EDGE_NOT_CORE",
        "lower_tail_diagnostics_24bp": lower_tail,
        "programization_notes": [
            "Every rolling feature ends at the completed interaction bar; no current incomplete bar or post-event field is used.",
            "The 500 ms activation uses the first strictly later one-minute open, never the decision timestamp.",
            "Both actions share the same entry and fixed symmetric level geometry; no future best action enters features.",
            "Unresolved year-boundary exposure is marked rather than strategy-closed and is excluded from later training labels.",
            "2023 and official 2024-2026 remain unopened unless the frozen 2022 gate passes.",
            "Rearm retreat must be established by a prior completed bar; the interaction bar cannot self-rearm from unknown intrabar ordering.",
            "Prior penetration/rejection history excludes the current interaction, preventing duplicate current-state leakage.",
            "Lower-tail bootstraps are diagnostic only and never feed policy selection or thresholds.",
        ],
    }

    output.mkdir(parents=True, exist_ok=True)
    events.to_csv(output / "EVENTS_2021_2022.csv.gz", index=False, compression="gzip")
    outcomes.to_csv(output / "ACTION_OUTCOMES_2021_2022.csv.gz", index=False, compression="gzip")
    predictions_2022.to_csv(output / "PREDICTIONS_2022.csv", index=False)
    pd.DataFrame(accounts["MODEL"]["24"]["trades"]).to_csv(output / "MODEL_TRADES_2022_24BP.csv", index=False)
    pd.DataFrame(rerouted_trades).to_csv(output / "MODEL_TRADES_2022_24BP_WINNER_REMOVED.csv", index=False)
    (output / "RESULT.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--end-year", type=int, default=2022)
    args = parser.parse_args()
    test_semantics()
    summary = run(args.root, args.output, args.end_year)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
