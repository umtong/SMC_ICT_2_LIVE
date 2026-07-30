#!/usr/bin/env python3
"""Direct forced-liquidation acceptance/rejection action-value fatal screen.

Readable reconstruction from the frozen claim contract and immutable event
ledger.  The missing historical evaluator bytes are not inferred or claimed.
This source has its own SHA and opens July 2022 only after its own semantic
self-tests pass.  September/November and all official dates remain sealed
unless the unchanged July policy passes every frozen gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

CLAIM_ID = "CLM-20260730-DIRECT-LIQUIDATION-ACTION-VALUE-001"
RESULT_ID = "RES-20260730-DIRECT-LIQUIDATION-ACTION-VALUE-001"
SOURCE_AUTHORITY = "RECONSTRUCTED_READABLE_AUTHORITY_FROM_FROZEN_CONTRACT"
FIT_DATES = ("2022-01-01", "2022-03-01", "2022-05-01")
DEV_DATES = ("2022-07-01",)
CONFIRM_DATES = ("2022-09-01", "2022-11-01")
DATE_ORDER = FIT_DATES + DEV_DATES + CONFIRM_DATES
COSTS_BPS = (12.0, 18.0, 24.0)
PRINCIPAL_COST_BPS = 24.0
PLANNED_LOSS_FRACTION = 0.005
NOTIONAL_CAP_X = 3.0
ACTIONS = ("CASCADE_CONTINUE", "EXHAUSTION_REJECT")
SYMBOLS = ("BTCUSDT", "ETHUSDT")

STRUCTURAL_FEATURES = (
    "raid_sign",
    "range_width_bps",
    "raid_depth_bps",
    "response_return_signed_bps",
    "flow_imbalance_1s_signed",
    "flow_imbalance_5s_signed",
    "mid_vs_mark_signed_bps",
    "mark_vs_index_signed_bps",
    "mark_acceptance_signed_bps",
    "oi_change_5s_signed",
    "bbo_imbalance_signed",
    "spread_bps",
)
LIQUIDATION_FEATURES = (
    "liq_log_notional_z",
    "liq_log_max_z",
    "liq_log_count_z",
    "liq_log_notional_per_range_bp_z",
    "liq_aligned_share",
    "liq_log_aligned_opposing_ratio",
)
RAW_LIQ_NORMALIZATION_COLUMNS = (
    "liq_log_notional",
    "liq_log_max",
    "liq_log_count",
    "liq_log_notional_per_range_bp",
)


@dataclass(frozen=True)
class RouteDefinition:
    action: str
    side: int
    entry_price: float
    stop_price: float
    target_price: float
    exit_price: float
    exit_time_us: int
    exit_reason: str
    unresolved_mark: bool


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def json_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_native(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if pd.isna(value):
        return None
    return value


def load_events(events_dir: Path) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    paths = sorted(events_dir.rglob("events_2022-*.csv"))
    if len(paths) != 6:
        raise RuntimeError(f"expected six immutable event files, found {len(paths)}")

    required = {
        "event_id", "date", "symbol", "raid_sign", "event_second",
        "decision_time_us", "entry_time_us", "entry_bid", "entry_ask",
        "lower_objective", "upper_objective",
        "upper_route_exit_time_us", "upper_route_exit_price", "upper_route_exit_reason",
        "lower_route_exit_time_us", "lower_route_exit_price", "lower_route_exit_reason",
        "funding_rate_at_entry", "source_end_time_us", "label_status",
    } | set(STRUCTURAL_FEATURES)

    frames: list[pd.DataFrame] = []
    manifest: list[dict[str, Any]] = []
    for path in paths:
        frame = pd.read_csv(path)
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise RuntimeError(f"{path.name} missing event columns: {missing}")
        frame["source_file"] = path.name
        frames.append(frame)
        manifest.append({
            "file": path.name,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "rows": int(len(frame)),
        })

    events = pd.concat(frames, ignore_index=True)
    events["date"] = events["date"].astype(str)
    events["symbol"] = events["symbol"].astype(str).str.upper()
    events = events[events["symbol"].isin(SYMBOLS)].copy()
    events = events.sort_values(["decision_time_us", "event_id"], kind="mergesort").reset_index(drop=True)

    if events["event_id"].duplicated().any():
        raise RuntimeError("duplicate immutable event_id")
    if set(events["date"].unique()) != set(DATE_ORDER):
        raise RuntimeError(f"unexpected event dates: {sorted(events['date'].unique())}")
    if not (pd.to_numeric(events["decision_time_us"]) >= pd.to_numeric(events["event_second"]) * 1_000_000).all():
        raise RuntimeError("decision precedes raid-second availability")
    if not (pd.to_numeric(events["entry_time_us"]) > pd.to_numeric(events["decision_time_us"])).all():
        raise RuntimeError("stored executable entry must be strictly later than decision")
    if not (pd.to_numeric(events["source_end_time_us"]) >= pd.to_numeric(events["entry_time_us"])).all():
        raise RuntimeError("source boundary precedes entry")
    return events, manifest


def _column_lookup(columns: Iterable[str], *names: str) -> str:
    lower = {str(c).lower(): str(c) for c in columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    raise RuntimeError(f"missing liquidation column among {names}; columns={list(columns)}")


def canonicalize_liquidation_chunk(raw: pd.DataFrame) -> pd.DataFrame:
    symbol_col = _column_lookup(raw.columns, "symbol")
    side_col = _column_lookup(raw.columns, "side")
    local_col = _column_lookup(raw.columns, "local_timestamp", "localtimestamp")
    price_col = _column_lookup(raw.columns, "price")
    amount_col = _column_lookup(raw.columns, "amount", "quantity", "size")
    frame = raw[[symbol_col, side_col, local_col, price_col, amount_col]].copy()
    frame.columns = ["symbol", "side", "local_timestamp", "price", "amount"]
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["side"] = frame["side"].astype(str).str.lower()
    frame = frame[frame["symbol"].isin(SYMBOLS) & frame["side"].isin(["buy", "sell"])].copy()
    for col in ("local_timestamp", "price", "amount"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["local_timestamp", "price", "amount"])
    if frame.empty:
        frame["notional"] = pd.Series(dtype=float)
        return frame
    median_ts = float(frame["local_timestamp"].median())
    if median_ts > 1e17:
        frame["local_timestamp"] = (frame["local_timestamp"] // 1_000).astype(np.int64)
    elif 1e9 < median_ts < 1e14:
        frame["local_timestamp"] = (frame["local_timestamp"] * 1_000_000).astype(np.int64)
    else:
        frame["local_timestamp"] = frame["local_timestamp"].astype(np.int64)
    frame["price"] = frame["price"].astype(float).abs()
    frame["amount"] = frame["amount"].astype(float).abs()
    frame = frame[(frame["price"] > 0) & (frame["amount"] > 0)].copy()
    frame["notional"] = frame["price"] * frame["amount"]
    return frame


def load_liquidations(liquidations_dir: Path) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    paths = sorted(liquidations_dir.rglob("liquidations_2022-*.csv.gz"))
    if len(paths) != 6:
        raise RuntimeError(f"expected six liquidation samples, found {len(paths)}")

    frames: list[pd.DataFrame] = []
    manifest: list[dict[str, Any]] = []
    for path in paths:
        date = path.name.replace("liquidations_", "").replace(".csv.gz", "")
        filtered_chunks: list[pd.DataFrame] = []
        raw_rows = 0
        for chunk in pd.read_csv(path, compression="gzip", chunksize=500_000):
            raw_rows += len(chunk)
            filtered = canonicalize_liquidation_chunk(chunk)
            if not filtered.empty:
                filtered_chunks.append(filtered)
        frame = pd.concat(filtered_chunks, ignore_index=True) if filtered_chunks else pd.DataFrame(
            columns=["symbol", "side", "local_timestamp", "price", "amount", "notional"]
        )
        frame["date"] = date
        frames.append(frame)
        manifest.append({
            "file": path.name,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "raw_rows": int(raw_rows),
            "btc_eth_rows": int(len(frame)),
        })

    liquidations = pd.concat(frames, ignore_index=True)
    liquidations = liquidations.sort_values(["date", "symbol", "local_timestamp"], kind="mergesort").reset_index(drop=True)
    return liquidations, manifest


def join_liquidation_state(events: pd.DataFrame, liquidations: pd.DataFrame) -> pd.DataFrame:
    grouped = {
        (str(date), str(symbol)): group.sort_values("local_timestamp", kind="mergesort").reset_index(drop=True)
        for (date, symbol), group in liquidations.groupby(["date", "symbol"], sort=False)
    }
    records: list[dict[str, Any]] = []
    for event in events.itertuples(index=False):
        group = grouped.get((str(event.date), str(event.symbol)))
        start_us = int(event.event_second) * 1_000_000
        end_us = int(event.decision_time_us)
        if group is None or group.empty:
            window = pd.DataFrame(columns=liquidations.columns)
        else:
            timestamps = group["local_timestamp"].to_numpy(np.int64)
            lo = int(np.searchsorted(timestamps, start_us, side="left"))
            hi = int(np.searchsorted(timestamps, end_us, side="right"))
            window = group.iloc[lo:hi]

        aligned_side = "buy" if float(event.raid_sign) > 0 else "sell"
        aligned = window[window["side"] == aligned_side]
        opposing = window[window["side"] != aligned_side]
        aligned_notional = float(aligned["notional"].sum())
        opposing_notional = float(opposing["notional"].sum())

        record = event._asdict()
        record.update({
            "liq_window_start_us": start_us,
            "liq_window_end_us": end_us,
            "liq_aligned_side": aligned_side,
            "liq_aligned_notional": aligned_notional,
            "liq_opposing_notional": opposing_notional,
            "liq_total_notional": aligned_notional + opposing_notional,
            "liq_aligned_count": int(len(aligned)),
            "liq_opposing_count": int(len(opposing)),
            "liq_total_count": int(len(window)),
            "liq_aligned_max_notional": float(aligned["notional"].max()) if len(aligned) else 0.0,
            "liq_aligned_share": aligned_notional / (aligned_notional + opposing_notional)
                if aligned_notional + opposing_notional > 0 else 0.0,
            "liq_log_aligned_opposing_ratio": math.log((aligned_notional + 1.0) / (opposing_notional + 1.0)),
        })
        records.append(record)

    joined = pd.DataFrame(records)
    joined = joined[(joined["liq_aligned_count"] > 0) & (joined["liq_aligned_notional"] > 0)].copy()
    joined["liq_log_notional"] = np.log1p(joined["liq_aligned_notional"].astype(float))
    joined["liq_log_max"] = np.log1p(joined["liq_aligned_max_notional"].astype(float))
    joined["liq_log_count"] = np.log1p(joined["liq_aligned_count"].astype(float))
    joined["liq_log_notional_per_range_bp"] = np.log1p(
        joined["liq_aligned_notional"].astype(float)
        / joined["range_width_bps"].astype(float).abs().clip(lower=1e-6)
    )
    return joined.sort_values(["decision_time_us", "event_id"], kind="mergesort").reset_index(drop=True)


def fit_symbol_normalizers(joined: pd.DataFrame) -> dict[str, dict[str, tuple[float, float]]]:
    fit = joined[joined["date"].isin(FIT_DATES)]
    normalizers: dict[str, dict[str, tuple[float, float]]] = {}
    for symbol, group in fit.groupby("symbol", sort=True):
        normalizers[str(symbol)] = {}
        for column in RAW_LIQ_NORMALIZATION_COLUMNS:
            mean = float(group[column].mean())
            std = float(group[column].std(ddof=0))
            normalizers[str(symbol)][column] = (
                mean if math.isfinite(mean) else 0.0,
                std if math.isfinite(std) and std > 1e-12 else 1.0,
            )
    if set(normalizers) != set(SYMBOLS):
        raise RuntimeError(f"fit liquidation normalizers missing symbols: {sorted(normalizers)}")
    return normalizers


def apply_symbol_normalizers(joined: pd.DataFrame, normalizers: Mapping[str, Mapping[str, tuple[float, float]]]) -> pd.DataFrame:
    output = joined.copy()
    for raw_column in RAW_LIQ_NORMALIZATION_COLUMNS:
        z_column = f"{raw_column}_z"
        output[z_column] = [
            (float(value) - normalizers[str(symbol)][raw_column][0]) / normalizers[str(symbol)][raw_column][1]
            for symbol, value in zip(output["symbol"], output[raw_column])
        ]
    return output


def count_funding_settlements(entry_time_us: int, exit_time_us: int) -> int:
    if exit_time_us <= entry_time_us:
        return 0
    interval_us = 8 * 60 * 60 * 1_000_000
    first = ((entry_time_us // interval_us) + 1) * interval_us
    if first > exit_time_us:
        return 0
    return int((exit_time_us - first) // interval_us) + 1


def route_for_action(row: pd.Series, action: str) -> RouteDefinition:
    raid_side = 1 if float(row["raid_sign"]) > 0 else -1
    if action == "CASCADE_CONTINUE":
        side = raid_side
    elif action == "EXHAUSTION_REJECT":
        side = -raid_side
    else:
        raise ValueError(f"unknown action {action}")

    lower = float(row["lower_objective"])
    upper = float(row["upper_objective"])
    entry_bid = float(row["entry_bid"])
    entry_ask = float(row["entry_ask"])
    if not (0 < lower < entry_bid <= entry_ask < upper):
        raise ValueError(f"invalid stored entry/objective geometry for {row['event_id']}")

    if side > 0:
        entry_price = entry_ask
        stop_price = lower
        target_price = upper
        exit_price = float(row["upper_route_exit_price"])
        exit_time_us = int(row["upper_route_exit_time_us"])
        exit_reason = str(row["upper_route_exit_reason"])
    else:
        entry_price = entry_bid
        stop_price = upper
        target_price = lower
        exit_price = float(row["lower_route_exit_price"])
        exit_time_us = int(row["lower_route_exit_time_us"])
        exit_reason = str(row["lower_route_exit_reason"])

    entry_time_us = int(row["entry_time_us"])
    if not (entry_price > 0 and stop_price > 0 and target_price > 0 and exit_price > 0):
        raise ValueError(f"nonpositive route price for {row['event_id']} {action}")
    if exit_time_us <= entry_time_us:
        raise ValueError(f"route exit does not follow entry for {row['event_id']} {action}")

    unresolved = "source_boundary" in exit_reason.lower() or "source_boundary" in str(row.get("label_status", "")).lower()
    return RouteDefinition(action, side, entry_price, stop_price, target_price, exit_price, exit_time_us, exit_reason, unresolved)


def account_return_from_route(row: pd.Series | Mapping[str, Any], cost_bps: float) -> dict[str, float]:
    cost_fraction = float(cost_bps) / 10_000.0
    risk_distance = float(row["risk_distance_fraction"])
    funding_rate = float(row["funding_rate_at_entry"] or 0.0)
    risk_per_notional = risk_distance + cost_fraction + abs(funding_rate)
    if not (risk_per_notional > 0 and math.isfinite(risk_per_notional)):
        raise ValueError("invalid risk-per-notional")
    exposure_x = min(NOTIONAL_CAP_X, PLANNED_LOSS_FRACTION / risk_per_notional)
    account_return = exposure_x * (float(row["gross_notional_return"]) + float(row["funding_notional_return"]) - cost_fraction)
    return {"cost_bps": float(cost_bps), "risk_per_notional": risk_per_notional, "exposure_x": exposure_x, "account_return": account_return}


def make_action_table(joined: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    records: list[dict[str, Any]] = []
    absent = {action: 0 for action in ACTIONS}
    for _, row in joined.iterrows():
        for action in ACTIONS:
            try:
                route = route_for_action(row, action)
            except ValueError:
                absent[action] += 1
                continue
            funding_rate = float(row.get("funding_rate_at_entry", 0.0) or 0.0)
            settlements = count_funding_settlements(int(row["entry_time_us"]), route.exit_time_us)
            gross = route.side * (route.exit_price - route.entry_price) / route.entry_price
            funding = -route.side * funding_rate * settlements
            risk_distance = abs(route.entry_price - route.stop_price) / route.entry_price
            record = row.to_dict()
            record.update({
                "action": action, "action_code": 1.0 if action == "CASCADE_CONTINUE" else -1.0,
                "side": route.side, "entry_price": route.entry_price, "stop_price": route.stop_price,
                "target_price": route.target_price, "exit_price": route.exit_price,
                "exit_time_us": route.exit_time_us, "exit_reason": route.exit_reason,
                "unresolved_mark": bool(route.unresolved_mark), "funding_settlement_count": settlements,
                "gross_notional_return": gross, "funding_notional_return": funding,
                "risk_distance_fraction": risk_distance,
            })
            record["account_return_24bp"] = account_return_from_route(record, 24.0)["account_return"]
            records.append(record)
    actions = pd.DataFrame(records)
    if actions.empty:
        raise RuntimeError("no valid action routes")
    return actions.sort_values(["entry_time_us", "event_id", "action"], kind="mergesort").reset_index(drop=True), absent


def model_matrix(frame: pd.DataFrame, include_liquidation: bool) -> pd.DataFrame:
    columns = list(STRUCTURAL_FEATURES) + (list(LIQUIDATION_FEATURES) if include_liquidation else [])
    matrix = frame[columns].astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0).copy()
    matrix["action_code"] = frame["action_code"].astype(float).to_numpy()
    for column in columns:
        matrix[f"action_x_{column}"] = matrix["action_code"] * matrix[column]
    return matrix


def fit_models(actions: pd.DataFrame) -> tuple[HistGradientBoostingRegressor, HistGradientBoostingRegressor]:
    train = actions[actions["date"].isin(FIT_DATES) & (~actions["unresolved_mark"].astype(bool))].copy()
    if len(train) < 40:
        raise RuntimeError(f"insufficient fit actions: {len(train)}")
    parameters = dict(max_iter=160, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=12, l2_regularization=2.0, random_state=20260730)
    target = train["account_return_24bp"].astype(float).to_numpy()
    full = HistGradientBoostingRegressor(**parameters)
    structural = HistGradientBoostingRegressor(**parameters)
    full.fit(model_matrix(train, True), target)
    structural.fit(model_matrix(train, False), target)
    return full, structural


def expanding_action_constants(actions: pd.DataFrame) -> pd.Series:
    result = pd.Series(index=actions.index, dtype=float)
    ordered_dates = list(DATE_ORDER)
    for date_index, date in enumerate(ordered_dates):
        prior_dates = ordered_dates[:date_index]
        prior = actions[actions["date"].isin(prior_dates) & (~actions["unresolved_mark"].astype(bool))]
        means = prior.groupby("action")["account_return_24bp"].mean().to_dict() if not prior.empty else {}
        mask = actions["date"] == date
        result.loc[mask] = actions.loc[mask, "action"].map(lambda action: float(means.get(str(action), 0.0)))
    return result.fillna(0.0)


def score_actions(actions: pd.DataFrame, full: HistGradientBoostingRegressor, structural: HistGradientBoostingRegressor) -> pd.DataFrame:
    scored = actions.copy()
    scored["pred_full"] = full.predict(model_matrix(scored, True))
    scored["pred_structural"] = structural.predict(model_matrix(scored, False))
    scored["pred_constant"] = expanding_action_constants(scored)
    return scored


def proposals_for_policy(scored: pd.DataFrame, policy: str, dates: Sequence[str]) -> pd.DataFrame:
    subset = scored[scored["date"].isin(dates)].copy()
    if subset.empty:
        return subset
    if policy in ("FULL_MODEL", "STRUCTURAL_MODEL", "EXPANDING_CONSTANT"):
        score_column = {"FULL_MODEL": "pred_full", "STRUCTURAL_MODEL": "pred_structural", "EXPANDING_CONSTANT": "pred_constant"}[policy]
        indices = subset.groupby("event_id", sort=False)[score_column].idxmax()
        proposals = subset.loc[indices].copy()
        proposals["policy_score"] = proposals[score_column].astype(float)
        proposals = proposals[proposals["policy_score"] > 0].copy()
    elif policy == "UNCONDITIONAL_CASCADE":
        proposals = subset[subset["action"] == "CASCADE_CONTINUE"].copy(); proposals["policy_score"] = 1.0
    elif policy == "UNCONDITIONAL_REJECT":
        proposals = subset[subset["action"] == "EXHAUSTION_REJECT"].copy(); proposals["policy_score"] = 1.0
    else:
        raise ValueError(f"unknown policy {policy}")
    proposals["policy"] = policy
    return proposals.sort_values(["entry_time_us", "policy_score", "event_id", "action"], ascending=[True, False, True, True], kind="mergesort").reset_index(drop=True)


def select_one_global_slot(proposals: pd.DataFrame, cost_bps: float, removed_event_ids: set[str] | None = None) -> pd.DataFrame:
    removed = removed_event_ids or set(); selected: list[dict[str, Any]] = []; busy_until = -1
    for _, row in proposals.iterrows():
        if str(row["event_id"]) in removed or int(row["entry_time_us"]) < busy_until:
            continue
        record = row.to_dict(); record.update(account_return_from_route(row, cost_bps)); selected.append(record)
        busy_until = int(row["exit_time_us"])
    return pd.DataFrame(selected) if selected else pd.DataFrame(columns=list(proposals.columns) + ["cost_bps", "risk_per_notional", "exposure_x", "account_return"])


def simulate_account(selected: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    nav = peak = 1.0; mdd = 0.0; records: list[dict[str, Any]] = []; completed: list[float] = []
    pos_sum = neg_sum = 0.0; date_nav: dict[str, float] = {}
    if not selected.empty:
        selected = selected.sort_values(["entry_time_us", "event_id"], kind="mergesort")
    for _, row in selected.iterrows():
        ret = max(float(row["account_return"]), -0.999999); before = nav; pnl = before * ret; nav = before + pnl
        peak = max(peak, nav); mdd = max(mdd, 1.0 - nav / peak); unresolved = bool(row["unresolved_mark"])
        if not unresolved:
            completed.append(ret); pos_sum += max(ret, 0.0); neg_sum += max(-ret, 0.0)
        record = row.to_dict(); record.update({"nav_before": before, "pnl": pnl, "nav_after": nav}); records.append(record)
        date_nav[str(row["date"])] = nav
    ledger = pd.DataFrame(records); unresolved_count = int(ledger["unresolved_mark"].astype(bool).sum()) if not ledger.empty else 0
    top_share = 0.0
    if not ledger.empty:
        positive = ledger[(~ledger["unresolved_mark"].astype(bool)) & (ledger["pnl"] > 0)]
        total = float(positive["pnl"].sum())
        if total > 0: top_share = float(positive.nlargest(5, "pnl")["pnl"].sum()) / total
    pf = pos_sum / neg_sum if neg_sum > 0 else (None if pos_sum > 0 else 0.0)
    metrics = {
        "selected_entry_count": int(len(ledger)), "completed_trade_count": len(completed),
        "unresolved_mark_count": unresolved_count, "positive_completed_trades": int(sum(x > 0 for x in completed)),
        "final_nav_multiple": nav, "total_return": nav - 1.0, "profit_factor": pf,
        "profit_factor_is_infinite": bool(neg_sum == 0 and pos_sum > 0),
        "median_completed_trade_return": float(np.median(completed)) if completed else 0.0,
        "mean_completed_trade_return": float(np.mean(completed)) if completed else 0.0,
        "maximum_drawdown": mdd, "top_five_positive_pnl_share": top_share, "date_end_nav": date_nav,
    }
    return metrics, ledger


def profit_factor_value(metrics: Mapping[str, Any]) -> float:
    return float("inf") if metrics.get("profit_factor_is_infinite") else float(metrics.get("profit_factor") or 0.0)


def evaluate_policy(scored: pd.DataFrame, policy: str, dates: Sequence[str]) -> dict[str, Any]:
    proposals = proposals_for_policy(scored, policy, dates); paths = {}; ledgers = {}
    for cost in COSTS_BPS:
        metrics, ledger = simulate_account(select_one_global_slot(proposals, cost)); paths[str(int(cost))] = metrics; ledgers[str(int(cost))] = ledger
    principal = ledgers["24"]
    positive = principal[(~principal["unresolved_mark"].astype(bool)) & (principal["pnl"] > 0)] if not principal.empty else principal
    removed = set(positive.nlargest(5, "pnl")["event_id"].astype(str)) if not positive.empty else set()
    winner_paths = {}; winner_ledgers = {}
    for cost in COSTS_BPS:
        metrics, ledger = simulate_account(select_one_global_slot(proposals, cost, removed)); winner_paths[str(int(cost))] = metrics; winner_ledgers[str(int(cost))] = ledger
    per_date = {}
    for date in dates:
        per_date[date] = {}
        p = proposals[proposals["date"] == date].copy()
        for cost in (18.0, 24.0):
            metrics, _ = simulate_account(select_one_global_slot(p, cost)); per_date[date][str(int(cost))] = metrics
    return {"policy": policy, "proposal_count": int(len(proposals)), "paths": paths, "winner_deleted_event_ids": sorted(removed),
            "winner_deleted_paths": winner_paths, "per_date_paths": per_date, "principal_ledger": principal,
            "winner_deleted_principal_ledger": winner_ledgers["24"]}


def gate(result: Mapping[str, Any]) -> tuple[bool, dict[str, bool]]:
    checks = {}
    for cost in ("18", "24"):
        path = result["paths"][cost]; winner = result["winner_deleted_paths"][cost]
        checks.update({
            f"{cost}_at_least_30_completed": path["completed_trade_count"] >= 30,
            f"{cost}_no_unresolved_marks": path["unresolved_mark_count"] == 0,
            f"{cost}_nav_positive": path["final_nav_multiple"] > 1.0,
            f"{cost}_pf_above_one": profit_factor_value(path) > 1.0,
            f"{cost}_median_positive": path["median_completed_trade_return"] > 0.0,
            f"{cost}_winner_deleted_nav_positive": winner["final_nav_multiple"] > 1.0,
            f"{cost}_winner_deleted_no_unresolved_marks": winner["unresolved_mark_count"] == 0,
        })
    return all(checks.values()), checks


def incremental_checks(full: Mapping[str, Any], baselines: Mapping[str, Mapping[str, Any]]) -> tuple[bool, dict[str, bool]]:
    checks = {}
    for name, baseline in baselines.items():
        for cost in ("18", "24"):
            checks[f"ordinary_{cost}_beats_{name}"] = full["paths"][cost]["final_nav_multiple"] > baseline["paths"][cost]["final_nav_multiple"]
            checks[f"winner_deleted_{cost}_beats_{name}"] = full["winner_deleted_paths"][cost]["final_nav_multiple"] > baseline["winner_deleted_paths"][cost]["final_nav_multiple"]
    return all(checks.values()), checks


def confirmation_date_checks(full: Mapping[str, Any]) -> tuple[bool, dict[str, bool]]:
    checks = {}
    for date in CONFIRM_DATES:
        for cost in ("18", "24"):
            path = full["per_date_paths"][date][cost]
            checks[f"{date}_{cost}_positive"] = path["final_nav_multiple"] > 1.0
            checks[f"{date}_{cost}_no_unresolved"] = path["unresolved_mark_count"] == 0
    return all(checks.values()), checks


def compact_policy(result: Mapping[str, Any]) -> dict[str, Any]:
    return {k: json_native(v) for k, v in result.items() if k not in ("principal_ledger", "winner_deleted_principal_ledger")}


def write_policy_ledgers(output: Path, stage: str, policies: Mapping[str, Mapping[str, Any]]) -> None:
    for name, result in policies.items():
        safe = name.lower(); result["principal_ledger"].to_csv(output / f"{stage}_{safe}_trades_24bp.csv", index=False, float_format="%.12g")
        result["winner_deleted_principal_ledger"].to_csv(output / f"{stage}_{safe}_winner_deleted_trades_24bp.csv", index=False, float_format="%.12g")


def run_self_tests() -> dict[str, Any]:
    assert count_funding_settlements(1, 2) == 0
    interval = 8 * 60 * 60 * 1_000_000
    assert count_funding_settlements(interval - 1, interval) == 1
    assert count_funding_settlements(interval - 1, 2 * interval) == 2
    base = {"event_id": "e1", "date": "2022-07-01", "symbol": "BTCUSDT", "raid_sign": 1,
            "entry_time_us": 1_000_000, "entry_bid": 99.9, "entry_ask": 100.0, "lower_objective": 99.0,
            "upper_objective": 102.0, "upper_route_exit_price": 102.0, "upper_route_exit_time_us": 2_000_000,
            "upper_route_exit_reason": "target", "lower_route_exit_price": 99.0, "lower_route_exit_time_us": 1_500_000,
            "lower_route_exit_reason": "target", "label_status": "upper_first", "funding_rate_at_entry": 0.0}
    long_route = route_for_action(pd.Series(base), "CASCADE_CONTINUE"); short_route = route_for_action(pd.Series(base), "EXHAUSTION_REJECT")
    assert long_route.side == 1 and long_route.stop_price == 99.0 and short_route.side == -1 and short_route.stop_price == 102.0
    proposals = pd.DataFrame([{**base, "action": "CASCADE_CONTINUE", "action_code": 1.0, "side": 1, "entry_price": 100.0,
                               "stop_price": 99.0, "target_price": 102.0, "exit_price": 102.0, "exit_time_us": 3_000_000,
                               "exit_reason": "target", "unresolved_mark": False, "gross_notional_return": 0.02,
                               "funding_notional_return": 0.0, "risk_distance_fraction": 0.01, "policy_score": 1.0, "policy": "TEST"},
                              {**base, "event_id": "e2", "entry_time_us": 2_000_000, "action": "CASCADE_CONTINUE", "action_code": 1.0,
                               "side": 1, "entry_price": 100.0, "stop_price": 99.0, "target_price": 102.0, "exit_price": 102.0,
                               "exit_time_us": 4_000_000, "exit_reason": "target", "unresolved_mark": False,
                               "gross_notional_return": 0.02, "funding_notional_return": 0.0, "risk_distance_fraction": 0.01,
                               "policy_score": 1.0, "policy": "TEST"},
                              {**base, "event_id": "e3", "entry_time_us": 3_000_000, "action": "CASCADE_CONTINUE", "action_code": 1.0,
                               "side": 1, "entry_price": 100.0, "stop_price": 99.0, "target_price": 102.0, "exit_price": 102.0,
                               "exit_time_us": 5_000_000, "exit_reason": "target", "unresolved_mark": False,
                               "gross_notional_return": 0.02, "funding_notional_return": 0.0, "risk_distance_fraction": 0.01,
                               "policy_score": 1.0, "policy": "TEST"}])
    selected = select_one_global_slot(proposals, 24.0); assert list(selected["event_id"]) == ["e1", "e3"]
    metrics, ledger = simulate_account(selected); assert metrics["completed_trade_count"] == 2 and (ledger["nav_after"] > ledger["nav_before"]).all()
    marked = selected.copy(); marked.loc[marked.index[0], "unresolved_mark"] = True
    marked_metrics, _ = simulate_account(marked); assert marked_metrics["completed_trade_count"] == 1 and marked_metrics["unresolved_mark_count"] == 1
    return {"status": "PASS", "tests": ["funding_settlement_clock", "action_route_direction_and_geometry", "global_slot_nonoverlap", "nav_compounding", "unresolved_mark_not_counted_as_completed"]}


def run_evaluation(events_dir: Path, liquidations_dir: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True); self_test = run_self_tests()
    events, event_manifest = load_events(events_dir); liquidations, liquidation_manifest = load_liquidations(liquidations_dir)
    joined = join_liquidation_state(events, liquidations); normalizers = fit_symbol_normalizers(joined)
    joined = apply_symbol_normalizers(joined, normalizers); actions, absent_routes = make_action_table(joined)
    full_model, structural_model = fit_models(actions); scored = score_actions(actions, full_model, structural_model)
    policy_names = ("FULL_MODEL", "STRUCTURAL_MODEL", "EXPANDING_CONSTANT", "UNCONDITIONAL_CASCADE", "UNCONDITIONAL_REJECT")
    development = {name: evaluate_policy(scored, name, DEV_DATES) for name in policy_names}
    full_gate, full_gate_checks = gate(development["FULL_MODEL"])
    baseline_map = {name: development[name] for name in policy_names if name != "FULL_MODEL"}
    incremental_pass, incremental_detail = incremental_checks(development["FULL_MODEL"], baseline_map)
    development_pass = bool(full_gate and incremental_pass)
    confirmation_opened = development_pass; confirmation = None; confirmation_gate_pass = confirmation_incremental_pass = confirmation_dates_pass = confirmation_pass = False
    confirmation_gate_checks = {}; confirmation_incremental_detail = {}; confirmation_date_detail = {}
    if confirmation_opened:
        confirmation = {name: evaluate_policy(scored, name, CONFIRM_DATES) for name in policy_names}
        confirmation_gate_pass, confirmation_gate_checks = gate(confirmation["FULL_MODEL"])
        confirmation_baselines = {name: confirmation[name] for name in policy_names if name != "FULL_MODEL"}
        confirmation_incremental_pass, confirmation_incremental_detail = incremental_checks(confirmation["FULL_MODEL"], confirmation_baselines)
        confirmation_dates_pass, confirmation_date_detail = confirmation_date_checks(confirmation["FULL_MODEL"])
        confirmation_pass = bool(confirmation_gate_pass and confirmation_incremental_pass and confirmation_dates_pass)
    status = "RETIRED_RECONSTRUCTED_DEVELOPMENT_BELOW_GATE_OR_BASELINE_INFERIOR" if not development_pass else (
        "RETIRED_RECONSTRUCTED_CONFIRMATION_BELOW_GATE_OR_BASELINE_INFERIOR" if not confirmation_pass else "PASS_SPARSE_PRE2024_SOURCE_SCREEN_NOT_RANK_ELIGIBLE")
    result = {"schema_version": 2, "claim_id": CLAIM_ID, "result_id": RESULT_ID, "source_authority": SOURCE_AUTHORITY,
              "status": status, "hard_validity_status": "PASS_RECONSTRUCTED_CAUSAL_SOURCE_EVENT_JOIN_FIXED_ACTION_ACCOUNT",
              "rank_eligible": False, "official_2024_2026_opened": False, "orders_submitted": False,
              "fit_dates": list(FIT_DATES), "development_dates": list(DEV_DATES), "confirmation_dates": list(CONFIRM_DATES),
              "immutable_event_rows": int(len(events)), "liquidation_present_event_rows": int(len(joined)),
              "stacked_action_rows": int(len(actions)), "absent_route_counts": absent_routes,
              "development": {name: compact_policy(value) for name, value in development.items()},
              "development_full_gate": full_gate, "development_full_gate_checks": full_gate_checks,
              "development_incremental_over_all_baselines": incremental_pass, "development_incremental_checks": incremental_detail,
              "development_pass": development_pass, "confirmation_opened": confirmation_opened,
              "confirmation": {name: compact_policy(value) for name, value in confirmation.items()} if confirmation else None,
              "confirmation_full_gate": confirmation_gate_pass, "confirmation_full_gate_checks": confirmation_gate_checks,
              "confirmation_incremental_over_all_baselines": confirmation_incremental_pass,
              "confirmation_incremental_checks": confirmation_incremental_detail,
              "confirmation_each_date_positive": confirmation_dates_pass, "confirmation_date_checks": confirmation_date_detail,
              "confirmation_pass": confirmation_pass,
              "model": {"family": "HistGradientBoostingRegressor", "symbol_identity_feature": False,
                        "full_features": list(STRUCTURAL_FEATURES + LIQUIDATION_FEATURES), "structural_features": list(STRUCTURAL_FEATURES),
                        "target": "direct_24bp_account_return"},
              "normalizers": {s: {c: [mu, sd] for c, (mu, sd) in m.items()} for s, m in normalizers.items()},
              "event_sources": event_manifest, "liquidation_sources": liquidation_manifest, "self_test": self_test}
    joined.to_csv(output / "JOINED_EVENTS.csv", index=False, float_format="%.12g")
    scored[["event_id", "date", "symbol", "action", "entry_time_us", "exit_time_us", "unresolved_mark", "account_return_24bp",
            "pred_full", "pred_structural", "pred_constant", "liq_aligned_notional", "liq_aligned_count", "liq_aligned_share"]].to_csv(
                output / "SCORED_ACTIONS.csv", index=False, float_format="%.12g")
    write_policy_ledgers(output, "development", development)
    if confirmation: write_policy_ledgers(output, "confirmation", confirmation)
    (output / "SELF_TEST.json").write_text(json.dumps(self_test, indent=2, sort_keys=True) + "\n")
    (output / "RESULT.json").write_text(json.dumps(json_native(result), indent=2, sort_keys=True, allow_nan=False) + "\n")
    dev24 = development["FULL_MODEL"]["paths"]["24"]
    (output / "REPORT.md").write_text("\n".join(["# Direct forced-liquidation action-value fatal screen", "",
        f"- source authority: `{SOURCE_AUTHORITY}`", f"- status: `{status}`", f"- immutable events: {len(events):,}",
        f"- liquidation-present events: {len(joined):,}", f"- stacked action rows: {len(actions):,}",
        f"- July full-model 24bp: `{json.dumps(json_native(dev24), sort_keys=True)}`", f"- development gate: `{development_pass}`",
        f"- confirmation opened: `{confirmation_opened}`", f"- confirmation pass: `{confirmation_pass}`",
        "- official 2024-2026: sealed", "- rank eligibility: false", "- credentials/orders: none", "",
        "The historical evaluator bytes were unrecoverable. This readable source is an independent implementation of the unchanged frozen contract and is not represented as byte-identical historical authority."]) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--events-dir", type=Path); parser.add_argument("--liquidations-dir", type=Path)
    parser.add_argument("--output", type=Path); parser.add_argument("--self-test", action="store_true"); args = parser.parse_args()
    if args.self_test:
        print(json.dumps(run_self_tests(), sort_keys=True)); return
    if args.events_dir is None or args.liquidations_dir is None or args.output is None:
        raise SystemExit("--events-dir, --liquidations-dir and --output are required")
    result = run_evaluation(args.events_dir, args.liquidations_dir, args.output)
    print(json.dumps({"status": result["status"], "development_pass": result["development_pass"],
                      "confirmation_opened": result["confirmation_opened"], "liquidation_present_events": result["liquidation_present_event_rows"]}, sort_keys=True))


if __name__ == "__main__":
    main()
