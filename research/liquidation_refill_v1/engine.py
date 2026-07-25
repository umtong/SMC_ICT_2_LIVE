from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from core import (
    PriceSeries, ResearchError, TradeOutcome, candidate_id, inclusive_calendar_days,
    maximum_drawdown, month_starts, product_grid, top_removed_return,
)

def generate_candidates(prereg: Mapping[str, Any]) -> list[dict[str, Any]]:
    grid = prereg["candidate_grid"]
    common = {
        "liquidation_quantile": grid["liquidation_quantile"],
        "dominance_min": grid["dominance_min"],
        "target_r": grid["target_r"],
        "min_stop_bps": grid["min_stop_bps"],
    }
    candidates: list[dict[str, Any]] = []
    continuation_grid = dict(common)
    continuation_grid.update(grid["continuation"])
    for params in product_grid(continuation_grid):
        params["family"] = "continuation"
        params["candidate_id"] = candidate_id(params)
        candidates.append(params)
    reversal_grid = dict(common)
    reversal_grid.update(grid["reversal"])
    for params in product_grid(reversal_grid):
        params["family"] = "reversal"
        params["candidate_id"] = candidate_id(params)
        candidates.append(params)
    return candidates


def select_signals(
    features: pd.DataFrame,
    candidate: Mapping[str, Any],
    thresholds: Mapping[float, Mapping[str, float]],
) -> pd.DataFrame:
    q = float(candidate["liquidation_quantile"])
    threshold_map = thresholds[q]
    frame = features.copy()
    frame["threshold"] = frame["symbol"].map(threshold_map)
    base = (
        (frame["force_direction"] != 0)
        & (frame["dominant_notional"] >= frame["threshold"])
        & (frame["dominance"] >= float(candidate["dominance_min"]))
    )
    if candidate["family"] == "continuation":
        mask = (
            base
            & (frame["acceleration"] >= float(candidate["acceleration_min"]))
            & (frame["directional_return_bps"] >= float(candidate["impact_min_bps"]))
            & (frame["close_location"] >= float(candidate["close_location_min"]))
            & frame["entry_open_continuation"].notna()
        )
        out = frame.loc[mask].copy()
        out["entry_time"] = out["continuation_entry_time"]
        out["direction"] = out["force_direction"]
        out["event_high"] = out["event_high_continuation"]
        out["event_low"] = out["event_low_continuation"]
        out["decision_time"] = out["minute"]
    else:
        mask = (
            base
            & (frame["directional_return_bps"] >= float(candidate["event_move_min_bps"]))
            & (frame["deceleration"] <= float(candidate["deceleration_max"]))
            & (frame["recovery"] >= float(candidate["recovery_min"]))
            & frame["entry_open_reversal"].notna()
        )
        out = frame.loc[mask].copy()
        out["entry_time"] = out["reversal_entry_time"]
        out["direction"] = -out["force_direction"]
        out["event_high"] = out["event_high_reversal"]
        out["event_low"] = out["event_low_reversal"]
        out["decision_time"] = out["reversal_decision_time"]
    if out.empty:
        return out
    out = out.sort_values(["entry_time", "dominant_notional", "symbol"], ascending=[True, False, True])
    # A candidate can submit only one new entry at the same timestamp. Highest observed forced notional wins.
    out = out.drop_duplicates(["entry_time"], keep="first").copy()
    out["signal_id"] = [
        hashlib.sha256(
            f"{candidate['candidate_id']}|{row.symbol}|{row.minute.isoformat()}".encode("utf-8")
        ).hexdigest()[:20]
        for row in out.itertuples()
    ]
    out["family"] = str(candidate["family"])
    return out.reset_index(drop=True)


def resolve_signal(
    row: pd.Series,
    candidate: Mapping[str, Any],
    series: PriceSeries,
) -> TradeOutcome:
    entry_time = pd.Timestamp(row["entry_time"])
    entry = series.open_at(entry_time)
    signal_id = str(row["signal_id"])
    if entry is None or not math.isfinite(entry) or entry <= 0:
        return TradeOutcome(
            symbol=str(row["symbol"]),
            family=str(row["family"]),
            signal_id=signal_id,
            event_time=pd.Timestamp(row["minute"]),
            entry_time=entry_time,
            direction=int(row["direction"]),
            entry_price=float("nan"),
            stop_price=float("nan"),
            target_price=float("nan"),
            exit_time=None,
            exit_price=None,
            exit_reason="unresolved_missing_entry",
            resolved=False,
        )
    direction = int(row["direction"])
    buffer = entry * 2.0e-4
    if direction > 0:
        raw_stop = float(row["event_low"]) - buffer
        minimum_stop = entry * float(candidate["min_stop_bps"]) * 1e-4
        stop = min(raw_stop, entry - minimum_stop)
    else:
        raw_stop = float(row["event_high"]) + buffer
        minimum_stop = entry * float(candidate["min_stop_bps"]) * 1e-4
        stop = max(raw_stop, entry + minimum_stop)
    distance = abs(entry - stop)
    if not math.isfinite(distance) or distance <= 0:
        raise ResearchError(f"invalid stop distance for {signal_id}")
    target = entry + direction * float(candidate["target_r"]) * distance
    path_end = pd.Timestamp(row["minute"]).normalize() + pd.Timedelta(days=2)
    exit_time, exit_price, reason = series.resolve_oco(
        entry_time=entry_time,
        path_end=path_end,
        direction=direction,
        stop_price=stop,
        target_price=target,
    )
    return TradeOutcome(
        symbol=str(row["symbol"]),
        family=str(row["family"]),
        signal_id=signal_id,
        event_time=pd.Timestamp(row["minute"]),
        entry_time=entry_time,
        direction=direction,
        entry_price=float(entry),
        stop_price=float(stop),
        target_price=float(target),
        exit_time=exit_time,
        exit_price=exit_price,
        exit_reason=reason,
        resolved=exit_time is not None and exit_price is not None,
    )


def simulate_account(
    signals: pd.DataFrame,
    candidate: Mapping[str, Any],
    price_series: Mapping[str, PriceSeries],
    *,
    initial_nav: float,
    risk_fraction: float,
    cost_bps: float,
    calendar_days: int,
    observed_days: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    nav = float(initial_nav)
    nav_path = [nav]
    open_until: pd.Timestamp | None = None
    returns: list[float] = []
    pnl_values: list[float] = []
    trade_rows: list[dict[str, Any]] = []
    unresolved = 0
    skipped_global_slot = 0

    for _, row in signals.sort_values(["entry_time", "dominant_notional"], ascending=[True, False]).iterrows():
        entry_time = pd.Timestamp(row["entry_time"])
        if open_until is not None and entry_time <= open_until:
            skipped_global_slot += 1
            continue
        outcome = resolve_signal(row, candidate, price_series[str(row["symbol"])])
        if not outcome.resolved:
            unresolved += 1
            trade_rows.append(
                {
                    **outcome.__dict__,
                    "nav_before": nav,
                    "nav_after": nav,
                    "pnl": 0.0,
                    "account_return": 0.0,
                    "cost_bps": cost_bps,
                }
            )
            # Without a strategy-logic exit the global slot remains occupied. Do not jump over the data gap.
            break
        assert outcome.exit_time is not None and outcome.exit_price is not None
        open_until = outcome.exit_time
        half_cost = cost_bps * 0.5e-4
        planned_per_unit_loss = (
            abs(outcome.entry_price - outcome.stop_price)
            + outcome.entry_price * half_cost
            + outcome.stop_price * half_cost
        )
        if planned_per_unit_loss <= 0:
            raise ResearchError("non-positive planned per-unit loss")
        qty = nav * risk_fraction / planned_per_unit_loss
        pnl = qty * outcome.direction * (outcome.exit_price - outcome.entry_price)
        pnl -= qty * (outcome.entry_price + outcome.exit_price) * half_cost
        nav_before = nav
        nav += pnl
        if nav <= 0:
            raise ResearchError("account NAV became non-positive")
        account_return = pnl / nav_before
        returns.append(account_return)
        pnl_values.append(pnl)
        nav_path.append(nav)
        trade_rows.append(
            {
                **outcome.__dict__,
                "qty": qty,
                "nav_before": nav_before,
                "nav_after": nav,
                "pnl": pnl,
                "account_return": account_return,
                "cost_bps": cost_bps,
            }
        )

    trades = pd.DataFrame(trade_rows)
    wins = [p for p in pnl_values if p > 0]
    losses = [p for p in pnl_values if p < 0]
    profit_factor = float(sum(wins) / abs(sum(losses))) if losses else (float("inf") if wins else 0.0)
    total_return = nav / initial_nav - 1.0
    geometric_daily = (nav / initial_nav) ** (1.0 / max(calendar_days, 1)) - 1.0
    observed_daily = (nav / initial_nav) ** (1.0 / max(observed_days, 1)) - 1.0
    asset_share = 0.0
    active_days = 0
    if not trades.empty and "resolved" in trades:
        resolved = trades.loc[trades["resolved"] == True]  # noqa: E712
        if not resolved.empty:
            asset_share = float(resolved["symbol"].value_counts(normalize=True).max())
            active_days = int(pd.to_datetime(resolved["entry_time"], utc=True).dt.date.nunique())
    metrics = {
        "cost_bps": float(cost_bps),
        "trade_count": int(len(returns)),
        "unresolved_count": int(unresolved),
        "skipped_global_slot": int(skipped_global_slot),
        "active_days": int(active_days),
        "ending_nav": float(nav),
        "total_return": float(total_return),
        "geometric_daily_growth_calendar": float(geometric_daily),
        "geometric_daily_growth_observed_days": float(observed_daily),
        "profit_factor": float(profit_factor),
        "median_trade_return": float(np.median(returns)) if returns else 0.0,
        "maximum_drawdown": maximum_drawdown(nav_path),
        "top1_removed_return": top_removed_return(returns, 0.01),
        "top5_removed_return": top_removed_return(returns, 0.05),
        "top10_removed_return": top_removed_return(returns, 0.10),
        "maximum_single_asset_trade_share": float(asset_share),
    }
    return metrics, trades


def flatten_metrics(prefix: str, metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {f"{prefix}_{key}": value for key, value in metrics.items()}


def gate_candidate(row: Mapping[str, Any], gate: Mapping[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    checks = [
        (row["dev18_trade_count"] >= gate["minimum_trades"], "minimum_trades"),
        (row["dev18_active_days"] >= gate["minimum_active_days"], "minimum_active_days"),
        (
            row["dev18_profit_factor"] >= gate["minimum_profit_factor_18bps"],
            "profit_factor_18bps",
        ),
        (
            row["dev18_median_trade_return"] > gate["minimum_median_trade_return_18bps"],
            "median_trade_return_18bps",
        ),
        (
            row["dev18_total_return"] > gate["minimum_total_return_18bps"],
            "total_return_18bps",
        ),
        (
            row["dev24_total_return"] >= gate["minimum_total_return_24bps"],
            "total_return_24bps",
        ),
        (
            row["dev18_top10_removed_return"] > gate["minimum_top10_removed_return_18bps"],
            "top10_removed_return_18bps",
        ),
        (
            row["dev18_maximum_drawdown"] <= gate["maximum_drawdown_18bps"],
            "maximum_drawdown_18bps",
        ),
        (
            row["dev18_maximum_single_asset_trade_share"]
            <= gate["maximum_single_asset_trade_share"],
            "single_asset_share",
        ),
        (row["dev18_unresolved_count"] <= gate["maximum_unresolved"], "unresolved"),
    ]
    if gate.get("fit_must_be_positive_18bps", False):
        checks.append((row["fit18_total_return"] > 0, "fit_total_return_18bps"))
    if gate.get("fit_top10_removed_must_be_positive_18bps", False):
        checks.append((row["fit18_top10_removed_return"] > 0, "fit_top10_removed_18bps"))
    for passed, name in checks:
        if not bool(passed):
            failures.append(name)
    return not failures, failures


def evaluate_candidates(
    candidates: Sequence[Mapping[str, Any]],
    fit_features: pd.DataFrame,
    dev_features: pd.DataFrame,
    thresholds: Mapping[float, Mapping[str, float]],
    price_series: Mapping[str, PriceSeries],
    prereg: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    account = prereg["account"]
    periods = prereg["periods"]
    costs = [float(x) for x in account["cost_stress_round_trip_bps"]]
    primary = float(account["primary_cost_bps"])
    rows: list[dict[str, Any]] = []
    best_trades: dict[str, pd.DataFrame] = {}
    best_primary_growth = -float("inf")

    for idx, candidate in enumerate(candidates, start=1):
        fit_signals = select_signals(fit_features, candidate, thresholds)
        dev_signals = select_signals(dev_features, candidate, thresholds)
        row: dict[str, Any] = dict(candidate)
        candidate_trade_sets: dict[str, pd.DataFrame] = {}
        for label, signals, period in (
            ("fit", fit_signals, periods["fit"]),
            ("dev", dev_signals, periods["development"]),
        ):
            calendar_days = inclusive_calendar_days(period)
            observed_days = len(month_starts(period["from"], period["to"]))
            for cost in costs:
                metrics, trades = simulate_account(
                    signals,
                    candidate,
                    price_series,
                    initial_nav=float(account["initial_nav"]),
                    risk_fraction=float(account["risk_fraction"]),
                    cost_bps=cost,
                    calendar_days=calendar_days,
                    observed_days=observed_days,
                )
                cost_tag = str(int(cost)) if float(cost).is_integer() else str(cost).replace(".", "p")
                prefix = f"{label}{cost_tag}"
                row.update(flatten_metrics(prefix, metrics))
                if cost == primary:
                    candidate_trade_sets[label] = trades
        passed, failures = gate_candidate(row, prereg["development_gate"])
        row["development_gate_pass"] = bool(passed)
        row["development_gate_failures"] = ";".join(failures)
        row["selection_score"] = (
            float(row["dev18_geometric_daily_growth_observed_days"])
            + 0.25 * float(row["dev24_geometric_daily_growth_observed_days"])
            - 0.25 * max(0.0, -float(row["dev18_top10_removed_return"]))
        )
        rows.append(row)
        growth = float(row["dev18_geometric_daily_growth_observed_days"])
        if growth > best_primary_growth:
            best_primary_growth = growth
            best_trades = candidate_trade_sets
        if idx % 50 == 0:
            print(json.dumps({"evaluated_candidates": idx, "total": len(candidates)}, sort_keys=True), flush=True)

    result = pd.DataFrame(rows)
    result = result.sort_values(
        ["development_gate_pass", "selection_score", "dev18_trade_count"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    result["rank"] = np.arange(1, len(result) + 1)
    return result, best_trades
