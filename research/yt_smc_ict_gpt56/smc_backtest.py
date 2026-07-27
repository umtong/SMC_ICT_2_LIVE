from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from smc_core import BAR_MS, FEATURE_COLUMNS, MarketData

DAY_MS = 86_400_000
MAKER_FEE = 0.0002
TAKER_FEE = 0.00055
MAINTENANCE_MARGIN_RATE = 0.005
MODEL_VARIANTS: tuple[dict[str, Any], ...] = (
    {
        "learning_rate": 0.035,
        "max_iter": 180,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 35,
        "l2_regularization": 1.0,
    },
    {
        "learning_rate": 0.05,
        "max_iter": 150,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 45,
        "l2_regularization": 2.0,
    },
    {
        "learning_rate": 0.025,
        "max_iter": 240,
        "max_leaf_nodes": 9,
        "min_samples_leaf": 25,
        "l2_regularization": 0.5,
    },
)


@dataclass
class ModelBundle:
    regressor: Pipeline
    classifier: Pipeline | None
    train_rows: int
    positive_rate: float


@dataclass(frozen=True)
class StrategyFilter:
    model_variant: int
    score_threshold: float
    rr_min: float
    entry_variant: str
    require_smt: bool
    require_cisd: bool
    session_scope: str


def slippage_rate(atr_pct: float) -> float:
    if not math.isfinite(atr_pct):
        atr_pct = 0.001
    return float(np.clip(0.00012 + 0.12 * atr_pct, 0.0002, 0.0012))


def effective_exit(row: pd.Series) -> tuple[float | None, float]:
    raw = row.get("exit_price_raw")
    if pd.isna(raw):
        return None, 0.0
    raw = float(raw)
    direction = int(row["direction"])
    reason = str(row["exit_reason"])
    if reason.startswith("target"):
        return raw, MAKER_FEE
    slip = slippage_rate(float(row.get("atr_pct", np.nan)))
    effective = raw * (1.0 - direction * slip)
    return effective, TAKER_FEE


def _funding_cash_per_unit(
    row: pd.Series,
    market: MarketData,
    prepared_frame: pd.DataFrame,
    *,
    end_timestamp_ms: int | None = None,
) -> float:
    fill_ts = row.get("fill_timestamp_ms")
    exit_ts = row.get("exit_timestamp_ms") if end_timestamp_ms is None else end_timestamp_ms
    if pd.isna(fill_ts) or exit_ts is None or pd.isna(exit_ts) or market.funding.empty:
        return 0.0
    fill_ts_i = int(fill_ts)
    exit_ts_i = int(exit_ts)
    funding = market.funding
    selected = funding[(funding["timestamp_ms"] > fill_ts_i) & (funding["timestamp_ms"] <= exit_ts_i)]
    if selected.empty:
        return 0.0
    timestamps = prepared_frame["timestamp_ms"].to_numpy(np.int64)
    closes = prepared_frame["close"].to_numpy(float)
    total = 0.0
    direction = int(row["direction"])
    for item in selected.itertuples(index=False):
        position = int(np.searchsorted(timestamps, int(item.timestamp_ms), side="right") - 1)
        if position < 0:
            continue
        price = float(closes[min(position, len(closes) - 1)])
        # Positive funding: longs pay, shorts receive.
        total += -direction * price * float(item.funding_rate)
    return total


def attach_net_labels(
    candidates: pd.DataFrame,
    markets: dict[str, MarketData],
    prepared: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    work = candidates.copy()
    net_labels: list[float] = []
    valid: list[bool] = []
    funding_r_values: list[float] = []
    cost_r_values: list[float] = []
    filled_values: list[int] = []
    for row in work.itertuples(index=False):
        item = pd.Series(row._asdict())
        fill_idx = item.get("fill_idx")
        exit_idx = item.get("exit_idx")
        reason = str(item.get("exit_reason"))
        filled = 0 if pd.isna(fill_idx) else 1
        filled_values.append(filled)
        if filled == 0:
            is_valid = reason not in {"unresolved", "dataset_end_before_activation"}
            valid.append(is_valid)
            net_labels.append(0.0 if is_valid else np.nan)
            funding_r_values.append(0.0)
            cost_r_values.append(0.0)
            continue
        if pd.isna(exit_idx):
            valid.append(False)
            net_labels.append(np.nan)
            funding_r_values.append(np.nan)
            cost_r_values.append(np.nan)
            continue
        entry = float(item["entry"])
        stop = float(item["stop"])
        risk_distance = abs(entry - stop)
        if risk_distance <= 0:
            valid.append(False)
            net_labels.append(np.nan)
            funding_r_values.append(np.nan)
            cost_r_values.append(np.nan)
            continue
        exit_price, exit_fee_rate = effective_exit(item)
        if exit_price is None:
            valid.append(False)
            net_labels.append(np.nan)
            funding_r_values.append(np.nan)
            cost_r_values.append(np.nan)
            continue
        direction = int(item["direction"])
        gross = direction * (exit_price - entry)
        trading_cost = entry * MAKER_FEE + exit_price * exit_fee_rate
        funding_cash = _funding_cash_per_unit(item, markets[str(item["symbol"])], prepared[str(item["symbol"])])
        net = (gross - trading_cost + funding_cash) / risk_distance
        valid.append(True)
        net_labels.append(net)
        funding_r_values.append(funding_cash / risk_distance)
        cost_r_values.append(trading_cost / risk_distance)
    work["label_valid"] = valid
    work["filled_hypothetical"] = filled_values
    work["net_r_label"] = net_labels
    work["funding_r_label"] = funding_r_values
    work["cost_r_label"] = cost_r_values
    work["positive_label"] = (work["net_r_label"] > 0.0).astype(float)
    return work


def _training_rows(candidates: pd.DataFrame, cutoff_ms: int) -> pd.DataFrame:
    return candidates[
        candidates["label_valid"]
        & (candidates["signal_timestamp_ms"] < cutoff_ms)
        & (candidates["resolved_timestamp_ms"] <= cutoff_ms)
        & candidates["net_r_label"].notna()
    ]


def train_model(candidates: pd.DataFrame, *, cutoff_ms: int, params: dict[str, Any]) -> ModelBundle:
    train = _training_rows(candidates, cutoff_ms)
    if len(train) < 150:
        raise ValueError(f"insufficient causally resolved training candidates: {len(train)}")
    x = train[FEATURE_COLUMNS]
    y = train["net_r_label"].clip(-2.0, 6.0)
    regressor = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            (
                "model",
                HistGradientBoostingRegressor(
                    loss="squared_error",
                    random_state=731,
                    early_stopping=True,
                    validation_fraction=0.15,
                    **params,
                ),
            ),
        ]
    )
    regressor.fit(x, y)
    positive = (train["net_r_label"] > 0.0).astype(int)
    classifier: Pipeline | None = None
    if positive.nunique() >= 2:
        classifier = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                (
                    "model",
                    HistGradientBoostingClassifier(
                        loss="log_loss",
                        random_state=977,
                        early_stopping=True,
                        validation_fraction=0.15,
                        learning_rate=params["learning_rate"],
                        max_iter=params["max_iter"],
                        max_leaf_nodes=params["max_leaf_nodes"],
                        min_samples_leaf=params["min_samples_leaf"],
                        l2_regularization=params["l2_regularization"],
                    ),
                ),
            ]
        )
        classifier.fit(x, positive)
    return ModelBundle(
        regressor=regressor,
        classifier=classifier,
        train_rows=len(train),
        positive_rate=float(positive.mean()),
    )


def predict_model(bundle: ModelBundle, rows: pd.DataFrame) -> np.ndarray:
    if rows.empty:
        return np.empty(0, dtype=float)
    x = rows[FEATURE_COLUMNS]
    predicted_r = bundle.regressor.predict(x)
    if bundle.classifier is None:
        probability = np.full(len(rows), bundle.positive_rate, dtype=float)
    else:
        probability = bundle.classifier.predict_proba(x)[:, 1]
    # Expected R remains the dominant term; probability suppresses brittle tails.
    return predicted_r * (0.55 + 0.45 * probability)


def walk_forward_scores(
    candidates: pd.DataFrame,
    *,
    start_ms: int,
    end_ms: int,
    model_params: dict[str, Any],
    training_lead_ms: int = 3_600_000,
) -> tuple[pd.Series, list[dict[str, Any]]]:
    score = pd.Series(np.nan, index=candidates.index, dtype=float)
    audits: list[dict[str, Any]] = []
    start = pd.Timestamp(start_ms, unit="ms", tz="UTC").floor("D")
    end = pd.Timestamp(end_ms, unit="ms", tz="UTC")
    month_starts = pd.date_range(start=start.replace(day=1), end=end, freq="MS")
    for month_start in month_starts:
        segment_start = max(int(month_start.timestamp() * 1000), start_ms)
        next_month = month_start + pd.offsets.MonthBegin(1)
        segment_end = min(int(next_month.timestamp() * 1000), end_ms)
        if segment_start >= segment_end:
            continue
        cutoff = segment_start - training_lead_ms
        bundle = train_model(candidates, cutoff_ms=cutoff, params=model_params)
        mask = (
            (candidates["signal_timestamp_ms"] >= segment_start)
            & (candidates["signal_timestamp_ms"] < segment_end)
        )
        score.loc[mask] = predict_model(bundle, candidates.loc[mask])
        audits.append(
            {
                "segment_start_ms": segment_start,
                "segment_end_ms": segment_end,
                "training_cutoff_ms": cutoff,
                "training_rows": bundle.train_rows,
                "positive_rate": bundle.positive_rate,
                "scored_rows": int(mask.sum()),
            }
        )
    return score, audits


def _qty_rules(market: MarketData) -> tuple[float, float]:
    lot = market.instrument.get("lotSizeFilter") or {}
    try:
        step = float(lot.get("qtyStep") or (0.001 if market.symbol == "BTCUSDT" else 0.01))
        minimum = float(lot.get("minOrderQty") or step)
    except (TypeError, ValueError):
        step = 0.001 if market.symbol == "BTCUSDT" else 0.01
        minimum = step
    return step, minimum


def _round_quantity(quantity: float, step: float) -> float:
    if quantity <= 0 or step <= 0:
        return 0.0
    return math.floor(quantity / step + 1e-12) * step


def _mark_price(prepared_frame: pd.DataFrame, timestamp_ms: int) -> float:
    timestamps = prepared_frame["timestamp_ms"].to_numpy(np.int64)
    closes = prepared_frame["close"].to_numpy(float)
    idx = int(np.searchsorted(timestamps, timestamp_ms, side="right") - 1)
    if idx < 0:
        return float(closes[0])
    return float(closes[min(idx, len(closes) - 1)])


def _funding_events(
    row: pd.Series,
    market: MarketData,
    prepared_frame: pd.DataFrame,
    quantity: float,
    end_ms: int,
) -> list[dict[str, float]]:
    fill_ts = int(row["fill_timestamp_ms"])
    funding = market.funding
    if funding.empty:
        return []
    selected = funding[(funding["timestamp_ms"] > fill_ts) & (funding["timestamp_ms"] <= end_ms)]
    events: list[dict[str, float]] = []
    direction = int(row["direction"])
    for item in selected.itertuples(index=False):
        price = _mark_price(prepared_frame, int(item.timestamp_ms))
        cash = -direction * quantity * price * float(item.funding_rate)
        events.append({"timestamp_ms": int(item.timestamp_ms), "cash": cash})
    return events


def filter_candidates(candidates: pd.DataFrame, strategy: StrategyFilter, score_column: str) -> pd.DataFrame:
    mask = candidates[score_column].notna() & (candidates[score_column] >= strategy.score_threshold)
    mask &= candidates["reward_risk"] >= strategy.rr_min
    if strategy.entry_variant != "all":
        mask &= candidates["entry_variant"] == strategy.entry_variant
    if strategy.require_smt:
        mask &= candidates["smt_divergence"] >= 0.5
    if strategy.require_cisd:
        mask &= candidates["cisd_confirmed"] >= 0.5
    if strategy.session_scope == "london_newyork":
        mask &= candidates["session_code"].isin([1.0, 2.0])
    elif strategy.session_scope == "newyork":
        mask &= candidates["session_code"] == 2.0
    elif strategy.session_scope == "active_three":
        mask &= candidates["session_code"].isin([0.0, 1.0, 2.0])
    return candidates.loc[mask].copy()


def simulate_account(
    candidates: pd.DataFrame,
    markets: dict[str, MarketData],
    prepared: dict[str, pd.DataFrame],
    *,
    period_start_ms: int,
    period_end_ms: int,
    score_column: str,
    risk_fraction: float,
    leverage: float,
    initial_nav: float = 10_000.0,
) -> dict[str, Any]:
    pool = candidates[
        (candidates["signal_timestamp_ms"] >= period_start_ms)
        & (candidates["signal_timestamp_ms"] < period_end_ms)
        & candidates[score_column].notna()
    ].copy()
    pool = pool.sort_values(["signal_timestamp_ms", score_column, "reward_risk"], ascending=[True, False, False])
    nav = float(initial_nav)
    free_ms = period_start_ms
    orders: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    total_fees = 0.0
    total_slippage = 0.0
    total_funding = 0.0
    liquidated = False

    for signal_ms, group in pool.groupby("signal_timestamp_ms", sort=True):
        signal_ms_i = int(signal_ms)
        if signal_ms_i < free_ms or nav <= 0:
            continue
        row = group.iloc[0]
        order_end_ms = int(row["order_end_timestamp_ms"]) + BAR_MS
        fill_ts_value = row.get("fill_timestamp_ms")
        orders.append(
            {
                "candidate_id": row["candidate_id"],
                "symbol": row["symbol"],
                "signal_timestamp_ms": signal_ms_i,
                "score": float(row[score_column]),
                "filled": not pd.isna(fill_ts_value),
                "order_end_timestamp_ms": order_end_ms,
            }
        )
        if pd.isna(fill_ts_value) or int(fill_ts_value) >= period_end_ms:
            free_ms = min(order_end_ms, period_end_ms)
            continue
        fill_ms = int(fill_ts_value)
        symbol = str(row["symbol"])
        market = markets[symbol]
        frame = prepared[symbol]
        entry = float(row["entry"])
        stop = float(row["stop"])
        direction = int(row["direction"])
        slip = slippage_rate(float(row.get("atr_pct", np.nan)))
        stop_effective = stop * (1.0 - direction * slip)
        loss_per_unit = abs(entry - stop_effective) + entry * MAKER_FEE + stop_effective * TAKER_FEE
        risk_budget = nav * risk_fraction
        quantity_risk = risk_budget / loss_per_unit if loss_per_unit > 0 else 0.0
        quantity_leverage = nav * leverage / entry
        quantity_liquidation = nav / (loss_per_unit + entry * MAINTENANCE_MARGIN_RATE)
        quantity = min(quantity_risk, quantity_leverage, quantity_liquidation * 0.995)
        step, minimum = _qty_rules(market)
        quantity = _round_quantity(quantity, step)
        if quantity < minimum:
            free_ms = min(order_end_ms, period_end_ms)
            continue
        entry_fee = quantity * entry * MAKER_FEE
        exit_ts_value = row.get("exit_timestamp_ms")
        completed = not pd.isna(exit_ts_value) and int(exit_ts_value) < period_end_ms
        if completed:
            exit_ms = int(exit_ts_value)
            exit_price, exit_fee_rate = effective_exit(row)
            assert exit_price is not None
            exit_reason = str(row["exit_reason"])
        else:
            exit_ms = period_end_ms
            raw_mark = _mark_price(frame, period_end_ms - 1)
            exit_price = raw_mark * (1.0 - direction * slip)
            exit_fee_rate = TAKER_FEE
            exit_reason = "evaluation_mark"
        funding_events = _funding_events(row, market, frame, quantity, exit_ms)
        funding_cash = sum(event["cash"] for event in funding_events)
        gross_pnl = direction * quantity * (exit_price - entry)
        exit_fee = quantity * exit_price * exit_fee_rate
        nav_after = nav + gross_pnl - entry_fee - exit_fee + funding_cash
        slippage_cost = 0.0
        raw_exit = row.get("exit_price_raw")
        if completed and not pd.isna(raw_exit) and not str(row["exit_reason"]).startswith("target"):
            slippage_cost = abs(float(raw_exit) - exit_price) * quantity
        elif not completed:
            slippage_cost = abs(raw_mark - exit_price) * quantity
        maintenance_margin = quantity * entry * MAINTENANCE_MARGIN_RATE
        stop_equity = nav - quantity * loss_per_unit
        liquidation_before_stop = stop_equity <= maintenance_margin
        if liquidation_before_stop:
            liquidated = True
        trade = {
            "candidate_id": row["candidate_id"],
            "symbol": symbol,
            "direction": direction,
            "score": float(row[score_column]),
            "signal_timestamp_ms": signal_ms_i,
            "fill_timestamp_ms": fill_ms,
            "exit_timestamp_ms": exit_ms,
            "entry": entry,
            "stop": stop,
            "target": float(row["target"]),
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "completed": completed,
            "quantity": quantity,
            "risk_fraction": risk_fraction,
            "leverage_cap": leverage,
            "nav_before": nav,
            "nav_after": nav_after,
            "gross_pnl": gross_pnl,
            "entry_fee": entry_fee,
            "exit_fee": exit_fee,
            "slippage_cost": slippage_cost,
            "funding_cash": funding_cash,
            "funding_events": funding_events,
            "liquidation_before_stop": liquidation_before_stop,
        }
        trades.append(trade)
        total_fees += entry_fee + exit_fee
        total_slippage += slippage_cost
        total_funding += funding_cash
        nav = nav_after
        free_ms = exit_ms + BAR_MS if completed else period_end_ms
        if nav <= 0 or liquidation_before_stop:
            liquidated = True
            if nav <= 0:
                nav = max(nav, 0.0)
            break

    daily_boundaries = np.arange(period_start_ms + DAY_MS, period_end_ms + 1, DAY_MS, dtype=np.int64)
    daily_nav: list[dict[str, float]] = []
    trade_pointer = 0
    realized_nav = float(initial_nav)
    for boundary in daily_boundaries:
        while trade_pointer < len(trades) and int(trades[trade_pointer]["exit_timestamp_ms"]) <= int(boundary):
            realized_nav = float(trades[trade_pointer]["nav_after"])
            trade_pointer += 1
        value = realized_nav
        if trade_pointer < len(trades):
            trade = trades[trade_pointer]
            fill_ms = int(trade["fill_timestamp_ms"])
            exit_ms = int(trade["exit_timestamp_ms"])
            if fill_ms < int(boundary) < exit_ms:
                mark = _mark_price(prepared[trade["symbol"]], int(boundary) - 1)
                direction = int(trade["direction"])
                quantity = float(trade["quantity"])
                entry = float(trade["entry"])
                funding_cash_to_boundary = sum(
                    event["cash"] for event in trade["funding_events"] if event["timestamp_ms"] <= int(boundary)
                )
                close_slip = slippage_rate(
                    float(
                        pool.loc[pool["candidate_id"] == trade["candidate_id"], "atr_pct"].iloc[0]
                        if (pool["candidate_id"] == trade["candidate_id"]).any()
                        else 0.001
                    )
                )
                liquidation_price = mark * (1.0 - direction * close_slip)
                liquidation_fee = quantity * liquidation_price * TAKER_FEE
                value = (
                    float(trade["nav_before"])
                    - float(trade["entry_fee"])
                    + direction * quantity * (liquidation_price - entry)
                    - liquidation_fee
                    + funding_cash_to_boundary
                )
        daily_nav.append({"timestamp_ms": int(boundary), "nav": float(max(value, 0.0))})

    if daily_nav:
        final_nav = float(daily_nav[-1]["nav"])
    else:
        final_nav = float(nav)
    days = max(1, int((period_end_ms - period_start_ms) // DAY_MS))
    if final_nav > 0:
        geometric_daily_growth = math.exp(math.log(final_nav / initial_nav) / days) - 1.0
    else:
        geometric_daily_growth = -1.0
    nav_values = np.array([initial_nav] + [item["nav"] for item in daily_nav], dtype=float)
    peaks = np.maximum.accumulate(nav_values)
    drawdowns = np.where(peaks > 0, nav_values / peaks - 1.0, -1.0)
    max_drawdown = float(-drawdowns.min())
    completed_trades = [trade for trade in trades if trade["completed"]]
    pnl_values = np.array([trade["nav_after"] - trade["nav_before"] for trade in completed_trades], dtype=float)
    wins = pnl_values[pnl_values > 0]
    losses = pnl_values[pnl_values < 0]
    profit_factor = float(wins.sum() / abs(losses.sum())) if len(losses) and abs(losses.sum()) > 0 else (float("inf") if len(wins) else 0.0)
    return {
        "period_start_ms": period_start_ms,
        "period_end_ms": period_end_ms,
        "days": days,
        "initial_nav": initial_nav,
        "final_nav": final_nav,
        "account_multiple": final_nav / initial_nav,
        "geometric_daily_growth": geometric_daily_growth,
        "max_drawdown": max_drawdown,
        "orders_selected": len(orders),
        "filled_trades": len(trades),
        "completed_trades": len(completed_trades),
        "win_rate": float((pnl_values > 0).mean()) if len(pnl_values) else 0.0,
        "profit_factor": profit_factor,
        "total_fees": total_fees,
        "total_slippage": total_slippage,
        "funding_cash": total_funding,
        "liquidated": liquidated,
        "daily_nav": daily_nav,
        "orders": orders,
        "trades": trades,
    }


def compact_metrics(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key not in {"daily_nav", "orders", "trades"}}


def self_test() -> None:
    assert abs(slippage_rate(0.001) - 0.00024) < 1e-12
    frame = pd.DataFrame(
        {
            "timestamp_ms": [0, BAR_MS, 2 * BAR_MS],
            "close": [100.0, 101.0, 102.0],
        }
    )
    assert _mark_price(frame, BAR_MS + 1) == 101.0
    print("smc_backtest self-test: ok")


if __name__ == "__main__":
    self_test()
