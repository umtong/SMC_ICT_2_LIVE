from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FIT_END = pd.Timestamp("2023-09-01T00:00:00Z")
DEVELOP_END = pd.Timestamp("2023-11-01T00:00:00Z")
END = pd.Timestamp("2024-01-01T00:00:00Z")
RISK = 0.005
CAP = 3.0
COSTS = (13, 18, 24)
FEATURES = [
    "source_z", "flow_6h", "flow_24h", "max_share",
    "address_amount_hhi", "address_ratio", "event_count",
    "unique_addresses", "event_ret", "close_loc", "vol_z",
    "ret3", "ret12", "oi_change1h", "acct_buy_ratio",
    "buy_ratio_change1h", "funding_rate", "target_atr",
    "stop_atr", "direction",
]
BASELINE_FEATURES = ["target_atr", "stop_atr", "direction", "event_ret", "close_loc"]


def native(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [native(item) for item in value]
    return value


def add_asof(
    events: pd.DataFrame,
    root: Path,
    filename: str,
    columns: list[str],
    prefix: str,
) -> pd.DataFrame:
    state = pd.read_pickle(root / filename).copy()
    if "observed" in state.columns:
        state = state[state["observed"]]
    state = state.sort_values("available_at_ms")
    right = state[["available_at_ms", *columns]].rename(
        columns={column: f"{prefix}{column}" for column in columns}
    )
    current = pd.merge_asof(
        events.sort_values("available_ms"),
        right,
        left_on="available_ms",
        right_on="available_at_ms",
        direction="backward",
    ).drop(columns=["available_at_ms"])
    lookup = events[["source_hour_start", "available_ms"]].copy()
    lookup["lookup_ms"] = lookup["available_ms"] - 3_600_000
    previous = pd.merge_asof(
        lookup.sort_values("lookup_ms"),
        right,
        left_on="lookup_ms",
        right_on="available_at_ms",
        direction="backward",
    ).drop(columns=["available_at_ms", "lookup_ms"])
    previous = previous.rename(
        columns={f"{prefix}{column}": f"{prefix}{column}_prev1h" for column in columns}
    )
    return current.merge(previous, on=["source_hour_start", "available_ms"], how="left")


def build_actions(source_path: Path, canonical_root: Path) -> pd.DataFrame:
    source = pd.read_parquet(source_path).sort_values("source_hour_start").reset_index(drop=True)
    source["q90"] = source["amount_eth"].rolling(720, min_periods=720).quantile(0.9).shift(1)
    source["log_amount"] = np.log1p(source["amount_eth"])
    source["log_mean"] = source["log_amount"].rolling(720, min_periods=720).mean().shift(1)
    source["log_std"] = source["log_amount"].rolling(720, min_periods=720).std().shift(1)
    source["source_z"] = (source["log_amount"] - source["log_mean"]) / source["log_std"]
    source["flow_6h"] = (
        source["amount_eth"].rolling(6, min_periods=6).sum()
        / source["amount_eth"].shift(1).rolling(168, min_periods=48).mean()
        / 6
    )
    source["flow_24h"] = (
        source["amount_eth"].rolling(24, min_periods=24).sum()
        / source["amount_eth"].shift(1).rolling(720, min_periods=168).mean()
        / 24
    )
    source["max_share"] = source["max_amount_eth"] / source["amount_eth"]
    source["address_ratio"] = source["unique_addresses"] / source["event_count"]
    source = source[source["amount_eth"] >= source["q90"]].copy()

    hourly = pd.read_pickle(canonical_root / "bars_1h.pkl.gz")
    hourly = hourly[hourly["is_complete"] & hourly["close"].notna()].copy()
    hourly["time"] = pd.to_datetime(hourly["start_time_ms"], unit="ms", utc=True)
    hourly = hourly.set_index("time").sort_index()
    previous_close = hourly["close"].shift(1)
    hourly["prior24_high"] = hourly["high"].shift(1).rolling(24, min_periods=24).max()
    hourly["prior24_low"] = hourly["low"].shift(1).rolling(24, min_periods=24).min()
    true_range = pd.concat(
        [
            hourly["high"] - hourly["low"],
            (hourly["high"] - previous_close).abs(),
            (hourly["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    hourly["atr24"] = true_range.shift(1).rolling(24, min_periods=24).mean()
    hourly["event_ret"] = hourly["close"] / hourly["open"] - 1
    hourly["close_loc"] = (
        (hourly["close"] - hourly["low"])
        / (hourly["high"] - hourly["low"]).replace(0, np.nan)
    )
    hourly["vol_log"] = np.log1p(hourly["volume"])
    volume_mean = hourly["vol_log"].shift(1).rolling(168, min_periods=48).mean()
    volume_std = hourly["vol_log"].shift(1).rolling(168, min_periods=48).std()
    hourly["vol_z"] = (hourly["vol_log"] - volume_mean) / volume_std
    hourly["ret3"] = hourly["close"] / hourly["close"].shift(3) - 1
    hourly["ret12"] = hourly["close"] / hourly["close"].shift(12) - 1
    market_columns = [
        "open", "high", "low", "close", "volume", "prior24_high", "prior24_low",
        "atr24", "event_ret", "close_loc", "vol_z", "ret3", "ret12",
    ]
    source = source.merge(
        hourly[market_columns], left_on="source_hour_start", right_index=True, how="left"
    )
    source["available_ms"] = source["available_at"].map(
        lambda value: int(value.timestamp() * 1000)
    ).astype("int64")

    source = add_asof(
        source, canonical_root, "open_interest_5m.pkl.gz", ["open_interest"], "oi_"
    )
    source = add_asof(
        source,
        canonical_root,
        "account_ratio_5m.pkl.gz",
        ["buy_ratio", "sell_ratio"],
        "acct_",
    )
    funding = pd.read_pickle(canonical_root / "funding_events.pkl.gz").sort_values(
        "available_at_ms"
    )
    source = pd.merge_asof(
        source.sort_values("available_ms"),
        funding[["available_at_ms", "funding_rate"]],
        left_on="available_ms",
        right_on="available_at_ms",
        direction="backward",
    ).drop(columns=["available_at_ms"])
    source["oi_change1h"] = source["oi_open_interest"] / source["oi_open_interest_prev1h"] - 1
    source["buy_ratio_change1h"] = source["acct_buy_ratio"] - source["acct_buy_ratio_prev1h"]

    minute = pd.read_pickle(canonical_root / "bars_1m.pkl.gz")
    minute = (
        minute[minute["observed"] & minute["open"].notna()]
        .copy()
        .sort_values("start_time_ms")
        .reset_index(drop=True)
    )
    times = minute["start_time_ms"].to_numpy(np.int64)
    available = minute["available_at_ms"].to_numpy(np.int64)
    opens = minute["open"].to_numpy(float)
    highs = minute["high"].to_numpy(float)
    lows = minute["low"].to_numpy(float)
    closes = minute["close"].to_numpy(float)
    end_index = int(np.searchsorted(times, int(END.timestamp() * 1000), side="left"))

    funding = funding[
        (funding["timestamp_ms"] >= int(pd.Timestamp("2023-04-12T00:00:00Z").timestamp() * 1000))
        & (funding["timestamp_ms"] < int(END.timestamp() * 1000))
    ].copy()
    funding_price_index = (
        np.searchsorted(available, funding["timestamp_ms"].to_numpy(np.int64), side="right") - 1
    )
    funding["price"] = np.where(
        funding_price_index >= 0, closes[np.maximum(funding_price_index, 0)], np.nan
    )
    funding_timestamps = funding["timestamp_ms"].to_numpy(np.int64)
    funding_rates = funding["funding_rate"].to_numpy(float)
    funding_prices = funding["price"].to_numpy(float)

    rows: list[dict[str, Any]] = []
    for _, event in source.iterrows():
        if (
            not np.isfinite(event["prior24_high"])
            or not np.isfinite(event["atr24"])
            or event["atr24"] <= 0
        ):
            continue
        activation = int(event["available_ms"]) + 500
        entry_index = int(np.searchsorted(times, activation, side="left"))
        if entry_index >= end_index:
            continue
        entry = float(opens[entry_index])
        for direction in (1, -1):
            target = float(event["prior24_high"] if direction == 1 else event["prior24_low"])
            stop = float(event["low"] if direction == 1 else event["high"])
            if not ((stop < entry < target) if direction == 1 else (target < entry < stop)):
                continue
            later_open = opens[entry_index:end_index]
            later_high = highs[entry_index:end_index]
            later_low = lows[entry_index:end_index]
            if direction == 1:
                stop_hits = np.flatnonzero((later_open <= stop) | (later_low <= stop))
                target_hits = np.flatnonzero((later_open >= target) | (later_high >= target))
            else:
                stop_hits = np.flatnonzero((later_open >= stop) | (later_high >= stop))
                target_hits = np.flatnonzero((later_open <= target) | (later_low <= target))
            stop_offset = int(stop_hits[0]) if len(stop_hits) else 10**12
            target_offset = int(target_hits[0]) if len(target_hits) else 10**12
            if stop_offset == 10**12 and target_offset == 10**12:
                exit_index = end_index - 1
                exit_price = float(closes[exit_index])
                reason = "boundary_mark"
                resolved = False
            elif stop_offset <= target_offset:
                exit_index = entry_index + stop_offset
                exit_price = float(
                    min(opens[exit_index], stop)
                    if direction == 1
                    else max(opens[exit_index], stop)
                )
                reason = "stop"
                resolved = True
            else:
                exit_index = entry_index + target_offset
                exit_price = target
                reason = "target"
                resolved = True
            exit_ms = int(times[exit_index])
            funding_mask = (
                (funding_timestamps > int(times[entry_index]))
                & (funding_timestamps <= exit_ms)
            )
            funding_per_unit = float(
                np.nansum(
                    -direction
                    * funding_prices[funding_mask]
                    * funding_rates[funding_mask]
                )
            )
            gross = direction * (exit_price - entry) / entry
            record = event.to_dict()
            record.update(
                event_key=str(event["source_hour_start"]),
                direction=direction,
                action="long_absorption" if direction == 1 else "short_acceptance",
                entry_ms=int(times[entry_index]),
                entry=entry,
                target=target,
                stop=stop,
                exit_ms=exit_ms,
                exit=exit_price,
                reason=reason,
                resolved=resolved,
                gross=gross,
                funding_per_unit=funding_per_unit,
                target_atr=abs(target - entry) / event["atr24"],
                stop_atr=abs(entry - stop) / event["atr24"],
            )
            stop_fraction = abs(entry - stop) / entry
            for cost in COSTS:
                net_notional = gross - cost / 10000 + funding_per_unit / entry
                notional_multiple = min(RISK / (stop_fraction + cost / 10000), CAP)
                record[f"notional_mult_{cost}"] = notional_multiple
                record[f"net_notional_{cost}"] = net_notional
                record[f"account_return_{cost}"] = notional_multiple * net_notional
            rows.append(record)
    actions = pd.DataFrame(rows).sort_values(
        ["source_hour_start", "direction"]
    ).reset_index(drop=True)
    for column in FEATURES:
        actions[column] = pd.to_numeric(actions[column], errors="coerce")
    actions["exit_time"] = pd.to_datetime(actions["exit_ms"], unit="ms", utc=True)
    return actions


def fit_models(train: pd.DataFrame) -> tuple[list[HistGradientBoostingRegressor], Any]:
    groups = train["event_key"].unique()
    rng = np.random.default_rng(20260730)
    models: list[HistGradientBoostingRegressor] = []
    for iteration in range(8):
        sampled = rng.choice(groups, size=len(groups), replace=True)
        counts = pd.Series(sampled).value_counts()
        indices: list[int] = []
        for key, count in counts.items():
            indices.extend(train.index[train["event_key"] == key].tolist() * int(count))
        sample = train.loc[indices]
        model = HistGradientBoostingRegressor(
            loss="squared_error",
            max_iter=150,
            learning_rate=0.05,
            max_leaf_nodes=7,
            min_samples_leaf=20,
            l2_regularization=10,
            random_state=100 + iteration,
        ).fit(sample[FEATURES], sample["account_return_24"])
        models.append(model)
    ridge = make_pipeline(StandardScaler(), Ridge(alpha=10)).fit(
        train[BASELINE_FEATURES], train["account_return_24"]
    )
    return models, ridge


def score(actions: pd.DataFrame, models: list[Any], ridge: Any) -> pd.DataFrame:
    scored = actions.copy()
    predictions = np.vstack([model.predict(scored[FEATURES]) for model in models])
    scored["pred_mean"] = predictions.mean(axis=0)
    scored["pred_std"] = predictions.std(axis=0)
    scored["score"] = scored["pred_mean"] - 0.5 * scored["pred_std"]
    scored["baseline_score"] = ridge.predict(scored[BASELINE_FEATURES])
    return scored


def route(
    actions: pd.DataFrame,
    score_column: str,
    cost: int,
    *,
    exclude: set[str] | None = None,
    threshold: float = 0.0,
) -> tuple[pd.DataFrame, float]:
    excluded = exclude or set()
    candidates = actions[~actions["event_key"].isin(excluded)].copy()
    candidates = candidates[candidates[score_column] > threshold]
    candidates = (
        candidates.sort_values(["entry_ms", score_column], ascending=[True, False])
        .groupby("event_key", as_index=False)
        .head(1)
        .sort_values(["entry_ms", score_column], ascending=[True, False])
    )
    nav = 10_000.0
    busy_until = -1
    trades: list[dict[str, Any]] = []
    for _, candidate in candidates.iterrows():
        if int(candidate["entry_ms"]) <= busy_until:
            continue
        nav_before = nav
        account_return = float(candidate[f"account_return_{cost}"])
        nav *= max(0.0, 1.0 + account_return)
        trade = candidate.to_dict()
        trade.update(
            nav_before=nav_before,
            nav_after=nav,
            pnl=nav - nav_before,
            account_return=account_return,
        )
        trades.append(trade)
        busy_until = int(candidate["exit_ms"])
    return pd.DataFrame(trades), nav


def route_response(actions: pd.DataFrame, cost: int) -> tuple[pd.DataFrame, float]:
    selected = actions[
        ((actions["event_ret"] >= 0) & (actions["direction"] == 1))
        | ((actions["event_ret"] < 0) & (actions["direction"] == -1))
    ].copy()
    selected["response_score"] = 1.0
    return route(selected, "response_score", cost)


def summarize(trades: pd.DataFrame, nav: float) -> dict[str, Any]:
    if trades.empty:
        return {
            "trades": 0,
            "end_nav": nav,
            "total_return": nav / 10_000 - 1,
            "profit_factor": 0.0,
            "median_account_return": 0.0,
            "mean_account_return": 0.0,
            "top5_positive_pnl_share": 0.0,
            "targets": 0,
            "stops": 0,
        }
    positive = trades.loc[trades["pnl"] > 0, "pnl"].sort_values(ascending=False)
    gains = float(positive.sum())
    losses = float(-trades.loc[trades["pnl"] < 0, "pnl"].sum())
    return {
        "trades": int(len(trades)),
        "end_nav": float(nav),
        "total_return": float(nav / 10_000 - 1),
        "profit_factor": float(gains / losses) if losses > 0 else float("inf"),
        "median_account_return": float(trades["account_return"].median()),
        "mean_account_return": float(trades["account_return"].mean()),
        "top5_positive_pnl_share": float(positive.head(5).sum() / gains) if gains > 0 else 0.0,
        "targets": int((trades["reason"] == "target").sum()),
        "stops": int((trades["reason"] == "stop").sum()),
    }


def period_report(name: str, actions: pd.DataFrame, output: Path) -> dict[str, Any]:
    resolved = actions[actions["resolved"]].copy()
    report: dict[str, Any] = {
        "actions": int(len(actions)),
        "events": int(actions["event_key"].nunique()),
        "resolved_actions": int(len(resolved)),
        "prediction": {
            "spearman_score_vs_24bp_action_value": float(
                spearmanr(resolved["score"], resolved["account_return_24"]).statistic
            ),
            "mae": float(mean_absolute_error(resolved["account_return_24"], resolved["score"])),
            "zero_baseline_mae": float(np.mean(np.abs(resolved["account_return_24"]))),
        },
        "ml_policy": {},
        "linear_policy": {},
        "response_policy": {},
        "raw_actions": {},
    }
    for action_name, direction in (("long_absorption", 1), ("short_acceptance", -1)):
        subset = resolved[resolved["direction"] == direction]
        report["raw_actions"][action_name] = {
            "count": int(len(subset)),
            "gross_mean_bp": float(subset["gross"].mean() * 10_000),
            "gross_median_bp": float(subset["gross"].median() * 10_000),
            "target_rate": float((subset["reason"] == "target").mean()),
            "account_value": {
                str(cost): {
                    "mean_bp": float(subset[f"account_return_{cost}"].mean() * 10_000),
                    "median_bp": float(subset[f"account_return_{cost}"].median() * 10_000),
                    "positive_share": float((subset[f"account_return_{cost}"] > 0).mean()),
                }
                for cost in COSTS
            },
        }
    for cost in COSTS:
        ml_trades, ml_nav = route(actions, "score", cost)
        linear_trades, linear_nav = route(actions, "baseline_score", cost)
        response_trades, response_nav = route_response(actions, cost)
        report["ml_policy"][str(cost)] = summarize(ml_trades, ml_nav)
        report["linear_policy"][str(cost)] = summarize(linear_trades, linear_nav)
        report["response_policy"][str(cost)] = summarize(response_trades, response_nav)
        if not ml_trades.empty:
            ml_trades.to_csv(output / f"{name}_ML_{cost}bp_TRADES.csv", index=False)
        if not response_trades.empty:
            response_trades.to_csv(output / f"{name}_RESPONSE_{cost}bp_TRADES.csv", index=False)

    ml_24, _ = route(actions, "score", 24)
    if ml_24.empty:
        report["ml_24bp_winner_deleted"] = summarize(ml_24, 10_000.0)
        report["ml_24bp_winner_deleted"]["removed_event_keys"] = 0
    else:
        positive_count = int((ml_24["pnl"] > 0).sum())
        remove_count = min(max(1, math.ceil(0.1 * len(ml_24))), positive_count)
        removed = set(
            ml_24[ml_24["pnl"] > 0]
            .nlargest(remove_count, "pnl")["event_key"]
            .astype(str)
        )
        rerouted, rerouted_nav = route(actions, "score", 24, exclude=removed)
        report["ml_24bp_winner_deleted"] = summarize(rerouted, rerouted_nav)
        report["ml_24bp_winner_deleted"]["removed_event_keys"] = int(len(removed))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    actions = build_actions(args.source, args.canonical_root)
    train = actions[
        (actions["source_hour_start"] < FIT_END)
        & actions["resolved"]
        & (actions["exit_time"] < FIT_END)
    ].dropna(subset=[*FEATURES, "account_return_24"]).copy()
    develop = actions[
        (actions["source_hour_start"] >= FIT_END)
        & (actions["source_hour_start"] < DEVELOP_END)
    ].dropna(subset=FEATURES).copy()
    confirmation = actions[
        (actions["source_hour_start"] >= DEVELOP_END)
        & (actions["source_hour_start"] < END)
    ].dropna(subset=FEATURES).copy()

    models, ridge = fit_models(train)
    develop = score(develop, models, ridge)
    confirmation = score(confirmation, models, ridge)

    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260730-ETH-VALIDATOR-WITHDRAWAL-CORE-001",
        "result_id": "RES-20260730-ETH-VALIDATOR-WITHDRAWAL-ECONOMIC-001",
        "status": "RETIRED_PRE2024_ECONOMIC_FAILURE",
        "target_status": "NOT_OPENED",
        "source_status": "SOURCE_PASS_FULL_PRE2024_CHRONOLOGY",
        "market": "Bybit ETHUSDT linear perpetual",
        "source_period": ["2023-04-12", "2023-12-31"],
        "information_unit": {
            "source_event": (
                "completed UTC-hour validator-withdrawal amount in the prior-only "
                "rolling 30-day upper decile"
            ),
            "availability": "source hour completion plus fixed 180 seconds; order activation plus 500ms",
            "actions": ["long_absorption", "short_acceptance", "flat"],
            "long_geometry": "event-hour low invalidation and prior-only 24h high objective",
            "short_geometry": "event-hour high invalidation and prior-only 24h low objective",
            "risk_fraction": RISK,
            "notional_cap": CAP,
            "costs_bp": list(COSTS),
            "elapsed_time_liquidation": False,
            "official_2024_2026_opened": False,
        },
        "chronology": {
            "fit": ["2023-04-12", "2023-08-31"],
            "forward_development": ["2023-09-01", "2023-10-31"],
            "frozen_confirmation": ["2023-11-01", "2023-12-31"],
            "model_refit_after_fit": False,
        },
        "counts": {
            "shock_events": int(actions["event_key"].nunique()),
            "action_rows": int(len(actions)),
            "fit_resolved_actions": int(len(train)),
            "development_actions": int(len(develop)),
            "confirmation_actions": int(len(confirmation)),
        },
        "development": period_report("DEVELOP", develop, args.output),
        "confirmation": period_report("CONFIRMATION", confirmation, args.output),
        "decision": [
            "The source is complete and causal, but the fixed hourly supply-acceptance/absorption action map is not stable.",
            "The fixed response policy is positive in September-October at 24bp and collapses unchanged in November-December.",
            "The action-value ML policy loses in development and selects four confirmation trades, all structural stops.",
            "Long-only confirmation strength is a post-outcome regime observation and cannot authorize a long-only rescue because earlier fit/development long economics were negative.",
            "Do not tune the withdrawal threshold, confirmation delay, action geometry, cost, risk or leverage from these outcomes.",
            "Retire this exact information unit without opening 2024-2026.",
        ],
        "orders_submitted": False,
        "live_permission": False,
        "ranking_change": False,
    }
    actions.to_pickle(args.output / "ACTION_DATASET.pkl.gz", compression="gzip")
    develop.to_pickle(args.output / "DEVELOP_SCORED.pkl.gz", compression="gzip")
    confirmation.to_pickle(args.output / "CONFIRMATION_SCORED.pkl.gz", compression="gzip")
    (args.output / "RESULT.json").write_text(
        json.dumps(native(result), indent=2, sort_keys=True)
    )
    print(json.dumps(native(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
