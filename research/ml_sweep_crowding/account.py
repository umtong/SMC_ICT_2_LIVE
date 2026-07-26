"""Global-slot execution, costs, funding, sizing, and NAV accounting."""
from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from .common import EPS, EconomicGateError, MarketData, SimConfig, SimResult, StageSpec
from .strategy import (
    build_global_sequence,
    funding_between,
    prepare_matrix,
    select_event_actions,
)


def price_at_or_before(
    market: MarketData, timestamp: pd.Timestamp, column: str = "close"
) -> float:
    series = market.one_minute[column]
    loc = series.index.searchsorted(timestamp, side="right") - 1
    while loc >= 0:
        value = float(series.iloc[loc])
        if np.isfinite(value):
            return value
        loc -= 1
    raise EconomicGateError(
        f"no {column} price at or before {timestamp} for {market.symbol}"
    )


def effective_entry(raw: float, direction: int, round_trip_bps: float) -> float:
    side = round_trip_bps / 20000.0
    return raw * (1.0 + direction * side)


def effective_exit(raw: float, direction: int, round_trip_bps: float) -> float:
    side = round_trip_bps / 20000.0
    return raw * (1.0 - direction * side)


def trade_exit_for_stage(
    candidate: pd.Series,
    market: MarketData,
    stage: StageSpec,
) -> tuple[pd.Timestamp, float, str, bool]:
    full_ts = candidate.exit_ts_full
    if pd.notna(full_ts) and full_ts < stage.end_exclusive:
        return (
            full_ts,
            float(candidate.exit_raw_full),
            str(candidate.resolution),
            False,
        )
    mark_ts = stage.end_exclusive - pd.Timedelta(minutes=1)
    return (
        mark_ts,
        price_at_or_before(market, mark_ts, "close"),
        "stage_mark",
        True,
    )


def simulate(
    sequence: pd.DataFrame,
    markets: Mapping[str, MarketData],
    stage: StageSpec,
    config: SimConfig,
    contract: Mapping[str, Any],
    skip_sequence_ids: set[int] | None = None,
) -> SimResult:
    skip_sequence_ids = skip_sequence_ids or set()
    start_nav = float(contract["sizing"]["start_nav_usdt"])
    nav = start_nav
    records: list[dict[str, Any]] = []
    forced_liquidation = False
    invalid_reason: str | None = None
    mmr = float(contract["sizing"]["maintenance_margin_fraction_proxy"])
    liq_buffer = float(contract["sizing"]["liquidation_distance_buffer_fraction"])
    for _, candidate in sequence.iterrows():
        sequence_id = int(candidate.sequence_id)
        if sequence_id in skip_sequence_ids:
            continue
        market = markets[str(candidate.symbol)]
        direction = int(candidate.candidate_direction)
        entry_raw = float(candidate.entry_raw)
        stop_raw = float(candidate.stop_raw)
        entry_eff = effective_entry(entry_raw, direction, config.round_trip_bps)
        stop_eff = effective_exit(stop_raw, direction, config.round_trip_bps)
        expected_stop_loss = direction * (entry_eff - stop_eff)
        if not np.isfinite(expected_stop_loss) or expected_stop_loss <= EPS:
            invalid_reason = "nonpositive expected stop loss"
            break
        planned_budget = nav * config.risk_fraction
        risk_qty = planned_budget / expected_stop_loss
        leverage_qty = nav * config.leverage / entry_raw
        stop_loss_fraction = expected_stop_loss / entry_eff
        liq_notional_cap = nav * liq_buffer / max(stop_loss_fraction + mmr, EPS)
        liq_qty = liq_notional_cap / entry_raw
        qty = min(risk_qty, leverage_qty, liq_qty)
        if not np.isfinite(qty) or qty <= 0:
            invalid_reason = "invalid quantity"
            break
        exit_ts, exit_raw, outcome, stage_mark = trade_exit_for_stage(
            candidate, market, stage
        )
        funding_per_unit = funding_between(
            market, candidate.entry_ts, exit_ts, direction
        )
        exit_eff = effective_exit(exit_raw, direction, config.round_trip_bps)
        pnl_per_unit = direction * (exit_eff - entry_eff) + funding_per_unit
        pnl = qty * pnl_per_unit
        nav_before = nav
        nav = nav + pnl
        notional = qty * entry_raw
        liq_distance_budget = max(nav_before / max(notional, EPS) - mmr, 0.0)
        if stop_loss_fraction > liq_distance_budget * liq_buffer + 1e-10:
            forced_liquidation = True
            invalid_reason = "liquidation-distance constraint breached"
        records.append(
            {
                "sequence_id": sequence_id,
                "event_id": candidate.event_id,
                "symbol": candidate.symbol,
                "entry_ts": candidate.entry_ts,
                "exit_ts": exit_ts,
                "direction": direction,
                "is_continuation": int(candidate.is_continuation),
                "probability": float(candidate.probability),
                "entry_raw": entry_raw,
                "stop_raw": stop_raw,
                "target_raw": float(candidate.target_raw),
                "exit_raw": float(exit_raw),
                "outcome": outcome,
                "stage_mark": stage_mark,
                "qty": float(qty),
                "notional": float(notional),
                "funding_per_unit": float(funding_per_unit),
                "pnl_per_unit": float(pnl_per_unit),
                "pnl": float(pnl),
                "nav_before": float(nav_before),
                "nav_after": float(nav),
            }
        )
        if forced_liquidation or not np.isfinite(nav) or nav <= 0:
            invalid_reason = invalid_reason or "nonpositive or nonfinite NAV"
            break
        if stage_mark:
            break
    trades = pd.DataFrame(records)
    valid = (
        invalid_reason is None
        and not forced_liquidation
        and np.isfinite(nav)
        and nav > 0
    )
    geometric_daily_growth = (
        (nav / start_nav) ** (1.0 / stage.calendar_days) - 1.0 if valid else -1.0
    )
    daily = daily_nav_series(
        trades, markets, stage, config.round_trip_bps, start_nav
    )
    if daily.empty:
        daily = pd.Series(
            [start_nav], index=[stage.end_exclusive - pd.Timedelta(minutes=1)]
        )
    max_drawdown = float((1.0 - daily / daily.cummax()).max()) if len(daily) else 0.0
    return SimResult(
        valid=valid,
        forced_liquidation=forced_liquidation,
        start_nav=start_nav,
        final_nav=float(nav),
        geometric_daily_growth=float(geometric_daily_growth),
        max_drawdown=max_drawdown,
        daily_nav=daily,
        trades=trades,
        invalid_reason=invalid_reason,
    )


def daily_nav_series(
    trades: pd.DataFrame,
    markets: Mapping[str, MarketData],
    stage: StageSpec,
    round_trip_bps: float,
    start_nav: float,
) -> pd.Series:
    day_marks = pd.date_range(
        stage.start.normalize() + pd.Timedelta(days=1) - pd.Timedelta(minutes=1),
        stage.end_exclusive - pd.Timedelta(minutes=1),
        freq="1D",
    )
    values: list[float] = []
    for mark_ts in day_marks:
        nav = start_nav
        if not trades.empty:
            closed = trades.loc[trades["exit_ts"] <= mark_ts]
            if not closed.empty:
                nav = float(closed.iloc[-1].nav_after)
            open_rows = trades.loc[
                (trades["entry_ts"] <= mark_ts) & (trades["exit_ts"] > mark_ts)
            ]
            if not open_rows.empty:
                trade = open_rows.iloc[0]
                market = markets[str(trade.symbol)]
                direction = int(trade.direction)
                mark_raw = price_at_or_before(market, mark_ts, "close")
                entry_eff = effective_entry(
                    float(trade.entry_raw), direction, round_trip_bps
                )
                mark_eff = effective_exit(mark_raw, direction, round_trip_bps)
                funding_per_unit = funding_between(
                    market, trade.entry_ts, mark_ts, direction
                )
                pnl_per_unit = direction * (mark_eff - entry_eff) + funding_per_unit
                nav = float(trade.nav_before) + float(trade.qty) * pnl_per_unit
        values.append(float(nav))
    return pd.Series(values, index=day_marks, name="nav")


def summarize_trades(result: SimResult) -> dict[str, Any]:
    trades = result.trades
    if trades.empty:
        return {
            "completed_trades": 0,
            "profit_factor": 0.0,
            "median_trade_return_on_nav": 0.0,
            "positive_pnl_top5_share": None,
            "long_trades": 0,
            "short_trades": 0,
            "continuation_trades": 0,
            "reversal_trades": 0,
            "by_symbol": {},
        }
    completed = trades.loc[~trades["stage_mark"]]
    wins = completed.loc[completed.pnl > 0, "pnl"]
    losses = completed.loc[completed.pnl < 0, "pnl"]
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (math.inf if gross_profit > 0 else 0.0)
    )
    positive_total = float(wins.sum())
    top5 = float(wins.nlargest(5).sum()) if positive_total > 0 else 0.0
    return {
        "completed_trades": int(len(completed)),
        "profit_factor": profit_factor,
        "median_trade_return_on_nav": (
            float((completed.pnl / completed.nav_before).median())
            if len(completed)
            else 0.0
        ),
        "positive_pnl_top5_share": (
            top5 / positive_total if positive_total > 0 else None
        ),
        "long_trades": int((completed.direction == 1).sum()),
        "short_trades": int((completed.direction == -1).sum()),
        "continuation_trades": int((completed.is_continuation == 1).sum()),
        "reversal_trades": int((completed.is_continuation == 0).sum()),
        "by_symbol": {
            str(key): int(value)
            for key, value in completed.symbol.value_counts().to_dict().items()
        },
    }


def select_pre2024_configuration(
    scored: pd.DataFrame,
    markets: Mapping[str, MarketData],
    stage: StageSpec,
    contract: Mapping[str, Any],
) -> tuple[SimConfig, pd.DataFrame, SimResult, list[dict[str, Any]]]:
    best: tuple[float, int, SimConfig, pd.DataFrame, SimResult] | None = None
    grid_report: list[dict[str, Any]] = []
    for threshold in contract["sizing"]["probability_thresholds"]:
        selected = select_event_actions(scored, float(threshold), stage)
        sequence = build_global_sequence(selected, stage)
        for risk in contract["sizing"]["risk_fractions"]:
            for leverage in contract["sizing"]["leverages"]:
                config = SimConfig(
                    float(threshold),
                    float(risk),
                    float(leverage),
                    float(contract["execution"]["base_round_trip_bps"]),
                )
                result = simulate(sequence, markets, stage, config, contract)
                grid_report.append(
                    {
                        "threshold": config.threshold,
                        "risk_fraction": config.risk_fraction,
                        "leverage": config.leverage,
                        "final_nav": result.final_nav,
                        "geometric_daily_growth": result.geometric_daily_growth,
                        "valid": result.valid,
                        "trades": int(len(result.trades)),
                    }
                )
                score = (
                    result.final_nav if result.valid else -math.inf,
                    int(len(result.trades)),
                )
                if best is None or score > (best[0], best[1]):
                    best = (score[0], score[1], config, sequence, result)
    if best is None:
        raise EconomicGateError("configuration grid produced no result")
    return best[2], best[3], best[4], grid_report


def model_diagnostics(
    model: HistGradientBoostingClassifier, frame: pd.DataFrame
) -> dict[str, Any]:
    labels = (frame["resolution"] == "target").astype(int).to_numpy()
    probabilities = model.predict_proba(prepare_matrix(frame))[:, 1]
    brier = float(np.mean((probabilities - labels) ** 2))
    baseline = float(np.mean((labels.mean() - labels) ** 2))
    return {
        "rows": int(len(frame)),
        "target_rate": float(labels.mean()),
        "brier": brier,
        "constant_brier": baseline,
        "brier_skill": 1.0 - brier / baseline if baseline > 0 else None,
        "mean_probability": float(probabilities.mean()),
    }
