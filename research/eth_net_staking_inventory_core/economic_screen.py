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
STREAMS = {
    "net": ("net_locked_eth", "two_sided"),
    "deposit": ("deposit_eth", "upper"),
    "release": ("principal_release_eth", "upper"),
}
FEATURES = [
    "source_value",
    "source_z",
    "source_abs_z",
    "source_sign",
    "source_6h_norm",
    "source_24h_norm",
    "deposit_eth",
    "principal_release_eth",
    "net_locked_eth",
    "deposit_event_count",
    "principal_event_count",
    "deposit_unique_pubkeys",
    "principal_unique_validators",
    "deposit_amount_share",
    "deposit_to_release_ratio_log",
    "event_ret",
    "close_loc",
    "vol_z",
    "ret3",
    "ret12",
    "oi_change1h",
    "acct_buy_ratio",
    "buy_ratio_change1h",
    "funding_rate",
    "target_atr",
    "stop_atr",
    "direction",
]
BASELINE_FEATURES = [
    "source_z",
    "source_sign",
    "target_atr",
    "stop_atr",
    "direction",
    "event_ret",
    "close_loc",
]


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


def stage_end(timestamp: pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(timestamp)
    if timestamp < FIT_END:
        return FIT_END
    if timestamp < DEVELOP_END:
        return DEVELOP_END
    return END


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
    previous_lookup = events[["source_hour_start", "available_ms"]].copy()
    previous_lookup["lookup_ms"] = previous_lookup["available_ms"] - 3_600_000
    previous = pd.merge_asof(
        previous_lookup.sort_values("lookup_ms"),
        right,
        left_on="lookup_ms",
        right_on="available_at_ms",
        direction="backward",
    ).drop(columns=["available_at_ms", "lookup_ms"])
    previous = previous.rename(
        columns={f"{prefix}{column}": f"{prefix}{column}_prev1h" for column in columns}
    )
    return current.merge(previous, on=["source_hour_start", "available_ms"], how="left")


def prepare_events(source_path: Path, stream: str) -> pd.DataFrame:
    value_column, tail_mode = STREAMS[stream]
    source = pd.read_parquet(source_path).copy()
    source["source_hour_start"] = pd.to_datetime(source["source_hour_start"], utc=True)
    source["available_at"] = pd.to_datetime(source["available_at"], utc=True)
    source = source.sort_values("source_hour_start").reset_index(drop=True)
    source["source_value"] = pd.to_numeric(source[value_column], errors="coerce")
    prior_mean = source["source_value"].shift(1).rolling(720, min_periods=720).mean()
    prior_std = source["source_value"].shift(1).rolling(720, min_periods=720).std()
    source["source_z"] = (source["source_value"] - prior_mean) / prior_std
    source["source_abs_z"] = source["source_z"].abs()
    source["source_sign"] = np.sign(source["source_value"])
    source["source_6h_norm"] = (
        source["source_value"].rolling(6, min_periods=6).sum()
        / (prior_std * np.sqrt(6))
    )
    source["source_24h_norm"] = (
        source["source_value"].rolling(24, min_periods=24).sum()
        / (prior_std * np.sqrt(24))
    )
    source["q10"] = source["source_value"].shift(1).rolling(720, min_periods=720).quantile(0.1)
    source["q90"] = source["source_value"].shift(1).rolling(720, min_periods=720).quantile(0.9)
    if tail_mode == "two_sided":
        keep = (source["source_value"] <= source["q10"]) | (
            source["source_value"] >= source["q90"]
        )
    else:
        keep = (source["source_value"] > 0) & (
            source["source_value"] >= source["q90"]
        )
    source = source[keep & source["source_z"].notna()].copy()
    source["stream"] = stream
    source["deposit_event_count"] = pd.to_numeric(
        source["deposit_event_count"], errors="coerce"
    ).fillna(0)
    source["principal_event_count"] = pd.to_numeric(
        source["principal_event_count"], errors="coerce"
    ).fillna(0)
    source["deposit_unique_pubkeys"] = pd.to_numeric(
        source["deposit_unique_pubkeys"], errors="coerce"
    ).fillna(0)
    source["principal_unique_validators"] = pd.to_numeric(
        source["principal_unique_validators"], errors="coerce"
    ).fillna(0)
    source["deposit_amount_share"] = pd.to_numeric(
        source["deposit_amount_share"], errors="coerce"
    ).fillna(0.5)
    ratio = pd.to_numeric(source["deposit_to_release_ratio"], errors="coerce")
    source["deposit_to_release_ratio_log"] = np.log1p(ratio.clip(lower=0)).replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0)
    return source


def add_market_state(events: pd.DataFrame, canonical_root: Path) -> pd.DataFrame:
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
    log_volume = np.log1p(hourly["volume"])
    volume_mean = log_volume.shift(1).rolling(168, min_periods=48).mean()
    volume_std = log_volume.shift(1).rolling(168, min_periods=48).std()
    hourly["vol_z"] = (log_volume - volume_mean) / volume_std
    hourly["ret3"] = hourly["close"] / hourly["close"].shift(3) - 1
    hourly["ret12"] = hourly["close"] / hourly["close"].shift(12) - 1
    columns = [
        "open",
        "high",
        "low",
        "close",
        "prior24_high",
        "prior24_low",
        "atr24",
        "event_ret",
        "close_loc",
        "vol_z",
        "ret3",
        "ret12",
    ]
    events = events.merge(
        hourly[columns], left_on="source_hour_start", right_index=True, how="left"
    )
    events["available_ms"] = events["available_at"].map(
        lambda value: int(pd.Timestamp(value).timestamp() * 1000)
    ).astype("int64")
    events = add_asof(
        events, canonical_root, "open_interest_5m.pkl.gz", ["open_interest"], "oi_"
    )
    events = add_asof(
        events,
        canonical_root,
        "account_ratio_5m.pkl.gz",
        ["buy_ratio", "sell_ratio"],
        "acct_",
    )
    funding = pd.read_pickle(canonical_root / "funding_events.pkl.gz").sort_values(
        "available_at_ms"
    )
    events = pd.merge_asof(
        events.sort_values("available_ms"),
        funding[["available_at_ms", "funding_rate"]],
        left_on="available_ms",
        right_on="available_at_ms",
        direction="backward",
    ).drop(columns=["available_at_ms"])
    events["oi_change1h"] = events["oi_open_interest"] / events["oi_open_interest_prev1h"] - 1
    events["buy_ratio_change1h"] = events["acct_buy_ratio"] - events["acct_buy_ratio_prev1h"]
    return events


def build_actions(source_path: Path, canonical_root: Path, stream: str) -> pd.DataFrame:
    events = add_market_state(prepare_events(source_path, stream), canonical_root)
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

    funding = pd.read_pickle(canonical_root / "funding_events.pkl.gz").copy()
    funding = funding[
        (funding["timestamp_ms"] >= int(pd.Timestamp("2023-04-12T00:00:00Z").timestamp() * 1000))
        & (funding["timestamp_ms"] < int(END.timestamp() * 1000))
    ].sort_values("timestamp_ms")
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
    for _, event in events.iterrows():
        if (
            not np.isfinite(event["prior24_high"])
            or not np.isfinite(event["atr24"])
            or event["atr24"] <= 0
        ):
            continue
        activation = int(event["available_ms"]) + 500
        entry_index = int(np.searchsorted(times, activation, side="left"))
        boundary = stage_end(pd.Timestamp(event["source_hour_start"]))
        end_index = int(np.searchsorted(times, int(boundary.timestamp() * 1000), side="left"))
        if entry_index >= end_index or end_index <= 0:
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
                    -direction * funding_prices[funding_mask] * funding_rates[funding_mask]
                )
            )
            gross = direction * (exit_price - entry) / entry
            record = event.to_dict()
            record.update(
                event_key=f"{stream}:{pd.Timestamp(event['source_hour_start']).isoformat()}",
                direction=direction,
                action="long" if direction == 1 else "short",
                label_boundary=boundary,
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
    actions = pd.DataFrame(rows)
    if actions.empty:
        return actions
    actions = actions.sort_values(["source_hour_start", "direction"]).reset_index(drop=True)
    for column in FEATURES:
        actions[column] = pd.to_numeric(actions[column], errors="coerce")
    actions[FEATURES] = actions[FEATURES].replace([np.inf, -np.inf], np.nan)
    actions["exit_time"] = pd.to_datetime(actions["exit_ms"], unit="ms", utc=True)
    return actions


def fit_models(train: pd.DataFrame) -> tuple[list[HistGradientBoostingRegressor], Any]:
    groups = train["event_key"].unique()
    if len(groups) < 20:
        raise ValueError(f"insufficient training events: {len(groups)}")
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


def route_source_sign(actions: pd.DataFrame, stream: str, cost: int) -> tuple[pd.DataFrame, float]:
    if stream == "net":
        selected = actions[
            ((actions["source_sign"] > 0) & (actions["direction"] == 1))
            | ((actions["source_sign"] < 0) & (actions["direction"] == -1))
        ].copy()
    elif stream == "deposit":
        selected = actions[actions["direction"] == 1].copy()
    else:
        selected = actions[actions["direction"] == -1].copy()
    selected["source_policy_score"] = 1.0
    return route(selected, "source_policy_score", cost)


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
            "boundary_marks": 0,
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
        "boundary_marks": int((trades["reason"] == "boundary_mark").sum()),
    }


def safe_spearman(x: pd.Series, y: pd.Series) -> float:
    value = spearmanr(x, y).statistic
    return float(value) if np.isfinite(value) else 0.0


def period_report(
    stream: str, name: str, actions: pd.DataFrame, output: Path
) -> dict[str, Any]:
    resolved = actions[actions["resolved"]].copy()
    report: dict[str, Any] = {
        "actions": int(len(actions)),
        "events": int(actions["event_key"].nunique()),
        "resolved_actions": int(len(resolved)),
        "prediction": {
            "spearman_score_vs_24bp_action_value": safe_spearman(
                resolved["score"], resolved["account_return_24"]
            ),
            "mae": float(mean_absolute_error(resolved["account_return_24"], resolved["score"])),
            "zero_baseline_mae": float(np.mean(np.abs(resolved["account_return_24"]))),
        },
        "ml_policy": {},
        "linear_policy": {},
        "response_policy": {},
        "source_sign_policy": {},
        "raw_actions": {},
    }
    for action_name, direction in (("long", 1), ("short", -1)):
        subset = resolved[resolved["direction"] == direction]
        report["raw_actions"][action_name] = {
            "count": int(len(subset)),
            "gross_mean_bp": float(subset["gross"].mean() * 10_000),
            "gross_median_bp": float(subset["gross"].median() * 10_000),
            "target_rate": float((subset["reason"] == "target").mean()),
            "account_value_24bp": {
                "mean_bp": float(subset["account_return_24"].mean() * 10_000),
                "median_bp": float(subset["account_return_24"].median() * 10_000),
                "positive_share": float((subset["account_return_24"] > 0).mean()),
            },
        }
    for cost in COSTS:
        ml_trades, ml_nav = route(actions, "score", cost)
        linear_trades, linear_nav = route(actions, "baseline_score", cost)
        response_trades, response_nav = route_response(actions, cost)
        source_trades, source_nav = route_source_sign(actions, stream, cost)
        report["ml_policy"][str(cost)] = summarize(ml_trades, ml_nav)
        report["linear_policy"][str(cost)] = summarize(linear_trades, linear_nav)
        report["response_policy"][str(cost)] = summarize(response_trades, response_nav)
        report["source_sign_policy"][str(cost)] = summarize(source_trades, source_nav)
        if not ml_trades.empty:
            ml_trades.to_csv(output / f"{stream.upper()}_{name}_ML_{cost}bp_TRADES.csv", index=False)

    ml_24, _ = route(actions, "score", 24)
    completed_positive = ml_24[(ml_24["pnl"] > 0) & ml_24["resolved"]] if not ml_24.empty else ml_24
    if completed_positive.empty:
        removed: set[str] = set()
    else:
        remove_count = min(
            max(1, math.ceil(0.1 * len(ml_24))), int(len(completed_positive))
        )
        removed = set(
            completed_positive.nlargest(remove_count, "pnl")["event_key"].astype(str)
        )
    rerouted, rerouted_nav = route(actions, "score", 24, exclude=removed)
    report["ml_24bp_winner_deleted"] = summarize(rerouted, rerouted_nav)
    report["ml_24bp_winner_deleted"]["removed_event_keys"] = int(len(removed))
    return report


def evaluate_stream(
    source_path: Path, canonical_root: Path, stream: str, output: Path
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    actions = build_actions(source_path, canonical_root, stream)
    if actions.empty:
        raise ValueError(f"no actions for stream {stream}")
    train = actions[
        (actions["source_hour_start"] < FIT_END)
        & actions["resolved"]
        & (actions["exit_time"] < FIT_END)
    ].dropna(subset=[*FEATURES, "account_return_24"]).copy()
    development = actions[
        (actions["source_hour_start"] >= FIT_END)
        & (actions["source_hour_start"] < DEVELOP_END)
    ].dropna(subset=FEATURES).copy()
    confirmation = actions[
        (actions["source_hour_start"] >= DEVELOP_END)
        & (actions["source_hour_start"] < END)
    ].dropna(subset=FEATURES).copy()
    models, ridge = fit_models(train)
    development = score(development, models, ridge)
    confirmation = score(confirmation, models, ridge)
    report = {
        "counts": {
            "shock_events": int(actions["event_key"].nunique()),
            "action_rows": int(len(actions)),
            "fit_resolved_actions": int(len(train)),
            "development_actions": int(len(development)),
            "confirmation_actions": int(len(confirmation)),
        },
        "development": period_report(stream, "DEVELOP", development, output),
        "confirmation": period_report(stream, "CONFIRMATION", confirmation, output),
    }
    actions.to_pickle(output / f"{stream.upper()}_ACTIONS.pkl.gz", compression="gzip")
    development.to_pickle(
        output / f"{stream.upper()}_DEVELOP_SCORED.pkl.gz", compression="gzip"
    )
    confirmation.to_pickle(
        output / f"{stream.upper()}_CONFIRMATION_SCORED.pkl.gz", compression="gzip"
    )
    return report, actions, development, confirmation


def pass_rule(results: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    net = results["net"]
    for stage in ("development", "confirmation"):
        primary = net[stage]["ml_policy"]["24"]
        deleted = net[stage]["ml_24bp_winner_deleted"]
        controls = [
            results["deposit"][stage]["ml_policy"]["24"]["end_nav"],
            results["release"][stage]["ml_policy"]["24"]["end_nav"],
        ]
        if primary["trades"] < 15:
            reasons.append(f"{stage}: net ML trades {primary['trades']} < 15")
        if primary["end_nav"] <= 10_000:
            reasons.append(f"{stage}: net ML NAV {primary['end_nav']:.2f} <= 10000")
        if deleted["end_nav"] <= 10_000:
            reasons.append(
                f"{stage}: net winner-deleted NAV {deleted['end_nav']:.2f} <= 10000"
            )
        if primary["end_nav"] <= max(controls):
            reasons.append(
                f"{stage}: net ML NAV {primary['end_nav']:.2f} <= best control {max(controls):.2f}"
            )
    return not reasons, reasons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {}
    for stream in STREAMS:
        report, _, _, _ = evaluate_stream(
            args.source, args.canonical_root, stream, args.output
        )
        results[stream] = report
    passed, failure_reasons = pass_rule(results)
    status = (
        "PRE2024_EXPOSED_NET_STAKING_DIAGNOSTIC_PASS"
        if passed
        else "RETIRED_NET_STAKING_INVENTORY_FAILURE"
    )
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260730-ETH-NET-STAKING-INVENTORY-CORE-001",
        "result_id": "RES-20260730-ETH-NET-STAKING-INVENTORY-001",
        "status": status,
        "comparison_confidence": "LOW_EXPOSED_SEMANTIC_DIAGNOSTIC",
        "source_status": "SOURCE_PASS_NET_STAKING_PRE2024",
        "source_period": ["2023-04-12", "2023-12-31"],
        "chronology": {
            "fit": ["2023-04-12", "2023-09-01"],
            "forward_development": ["2023-09-01", "2023-11-01"],
            "frozen_confirmation": ["2023-11-01", "2024-01-01"],
            "stage_boundary": "mark only; unresolved labels excluded",
            "model_refit_after_fit": False,
            "official_2024_2026_opened": False,
        },
        "information_unit": {
            "net_event": "hourly deposit ETH minus principal-scale release ETH in prior-only rolling 720h q10/q90 tails",
            "controls": ["deposit upper-tail", "principal release upper-tail"],
            "actions": ["long", "short", "flat"],
            "source_confirmation_delay_seconds": 180,
            "order_latency_ms": 500,
            "risk_fraction": RISK,
            "notional_cap": CAP,
            "costs_bp": list(COSTS),
            "elapsed_time_liquidation": False,
        },
        "streams": results,
        "pass_rule_met": passed,
        "pass_rule_failure_reasons": failure_reasons,
        "known_official_source_limitation": "Xatu canonical_beacon_block_deposit public files are documented only through 2025-05-14",
        "decision": (
            [
                "The net-staking inventory state passes the frozen exposed pre-2024 diagnostic.",
                "This evidence is low-confidence because adjacent validator outcomes for the same periods were already exposed.",
                "Before any official replay, reconstruct the deposit source from a separately frozen full-period execution-deposit-contract authority.",
            ]
            if passed
            else [
                "Combining deposit locks with principal-scale releases does not produce a broad winner-resistant Core under the frozen rule.",
                "Do not change source definitions, quantiles, delay, geometry, cost, risk or leverage after observing the result.",
                "Official 2024-2026 remains unopened and ranking is unchanged.",
            ]
        ),
        "orders_submitted": False,
        "live_permission": False,
        "ranking_change": False,
    }
    (args.output / "RESULT.json").write_text(
        json.dumps(native(result), indent=2, sort_keys=True)
    )
    print(json.dumps(native(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
