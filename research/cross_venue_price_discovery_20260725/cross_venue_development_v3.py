from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import cross_venue_pilot as v1
import cross_venue_pilot_v2 as v2
import cross_venue_development_v2 as d2


@dataclass(frozen=True, slots=True)
class AccountTradeV3:
    config_id: str
    day: str
    symbol: str
    family: str
    decision_ms: int
    entry_ms: int
    exit_ms: int
    side: int
    entry_price: float
    exit_price: float
    stop_price: float
    quantity: float
    notional: float
    leverage: float
    gross_pnl: float
    fees: float
    net_pnl: float
    account_return: float
    nav_before: float
    nav_after: float
    exit_reason: str
    score: float
    exit_liquidity_overrun: bool
    maximum_intratrade_drawdown: float


def mandatory_exit_price(row: pd.Series, side: int, quantity: float) -> tuple[float, bool] | None:
    quote = float(row.bn_bid if side > 0 else row.bn_ask)
    available = float(row.bn_bid_amount if side > 0 else row.bn_ask_amount)
    spread = float(row.bn_ask - row.bn_bid)
    if not all(math.isfinite(value) for value in (quote, available, spread)) or quote <= 0 or available <= 0 or spread <= 0:
        return None
    participation = quantity / available
    normalized = participation / d2.MAX_TOP_QUOTE_PARTICIPATION
    impact_spreads = 0.25 * min(normalized, 1.0) + 2.0 * max(normalized - 1.0, 0.0)
    impact = spread * impact_spreads
    if side > 0:
        price = max(quote * 0.10, quote - impact)
    else:
        price = quote + impact
    return price, participation > d2.MAX_TOP_QUOTE_PARTICIPATION


def simulate_account_v3(
    frames: dict[tuple[str, str], pd.DataFrame],
    events: list[v1.Event],
    config: v1.Config,
    fee_bps: float,
) -> tuple[list[AccountTradeV3], dict[str, float]]:
    nav = d2.INITIAL_NAV
    peak = nav
    maximum_drawdown = 0.0
    free_time = -1
    trades: list[AccountTradeV3] = []
    by_key = {key: frame.loc[frame.bn_quote_actual].copy() for key, frame in frames.items()}
    ordered = sorted(events, key=lambda item: (item.decision_ms, -item.score, item.symbol, item.family))
    for event in ordered:
        if event.decision_ms < free_time:
            continue
        key = (event.day, event.symbol)
        frame = frames[key]
        quotes = by_key[key]
        if quotes.empty:
            continue
        quote_buckets = quotes.index.to_numpy(np.int64)
        quote_times = quotes.bn_quote_event_ms.to_numpy(np.int64)
        target = event.decision_ms + config.latency_ms
        entry_pos = int(np.searchsorted(quote_times, target, side="left"))
        if entry_pos >= len(quote_times):
            continue
        entry_ms = int(quote_times[entry_pos])
        maximum_exit_ms = entry_ms + config.hold_ms
        if d2.funding_collision(entry_ms, maximum_exit_ms):
            continue
        entry_row = quotes.iloc[entry_pos]
        entry_mid = float(entry_row.bn_mid)
        spread = float(entry_row.bn_ask - entry_row.bn_bid)
        stop_mid = entry_mid - event.side * config.stop_spreads * spread
        sized = d2.size_position(entry_row, event.side, stop_mid, nav, fee_bps)
        if sized is None:
            continue
        quantity, entry_price, leverage, _planned_loss = sized
        entry_fee = quantity * entry_price * fee_bps / 10_000.0
        exit_pos = min(int(np.searchsorted(quote_times, maximum_exit_ms, side="left")), len(quote_times) - 1)
        reason = "horizon"
        chosen = exit_pos
        initial_gap = abs(event.initial_basis_residual)
        frame_times = frame.index.to_numpy(np.int64)
        trade_peak = nav
        trade_maximum_drawdown = 0.0
        for position in range(entry_pos, exit_pos + 1):
            row = quotes.iloc[position]
            executable_stop_hit = (
                float(row.bn_bid) <= stop_mid if event.side > 0 else float(row.bn_ask) >= stop_mid
            )
            mark = mandatory_exit_price(row, event.side, quantity)
            if mark is not None:
                mark_price = mark[0]
                mark_fee = quantity * mark_price * fee_bps / 10_000.0
                mark_nav = nav + event.side * quantity * (mark_price - entry_price) - entry_fee - mark_fee
                trade_peak = max(trade_peak, mark_nav)
                drawdown = 1.0 - mark_nav / max(trade_peak, 1e-12)
                trade_maximum_drawdown = max(trade_maximum_drawdown, drawdown)
                maximum_drawdown = max(maximum_drawdown, drawdown)
            if executable_stop_hit:
                chosen, reason = position, "protective_stop"
                break
            current_basis = math.log(float(row.bb_mid) / float(row.bn_mid))
            bucket = int(quote_buckets[position])
            history_end = int(np.searchsorted(frame_times, bucket, side="right"))
            start = max(0, history_end - 601)
            stop_at = max(start, history_end - 1)
            history = np.log(frame.bb_mid.iloc[start:stop_at]) - np.log(frame.bn_mid.iloc[start:stop_at])
            if len(history) >= 300:
                residual = current_basis - float(history.median())
                if initial_gap > 0 and abs(residual) <= 0.25 * initial_gap:
                    chosen, reason = position, "cross_venue_convergence"
                    break
        exit_ms = int(quote_times[chosen])
        mandatory = mandatory_exit_price(quotes.iloc[chosen], event.side, quantity)
        if mandatory is None:
            # An actual quote row with unusable prices is a data failure for this event,
            # not permission to pretend a favorable fill. Skip entry by rolling it back.
            continue
        exit_price, overrun = mandatory
        exit_fee = quantity * exit_price * fee_bps / 10_000.0
        gross = event.side * quantity * (exit_price - entry_price)
        fees = entry_fee + exit_fee
        net = gross - fees
        before = nav
        nav += net
        account_return = net / before
        peak = max(peak, nav, trade_peak)
        maximum_drawdown = max(maximum_drawdown, 1.0 - nav / max(peak, 1e-12))
        trades.append(
            AccountTradeV3(
                config.config_id,
                event.day,
                event.symbol,
                event.family,
                event.decision_ms,
                entry_ms,
                exit_ms,
                event.side,
                entry_price,
                exit_price,
                stop_mid,
                quantity,
                quantity * entry_price,
                leverage,
                gross,
                fees,
                net,
                account_return,
                before,
                nav,
                reason,
                event.score,
                overrun,
                trade_maximum_drawdown,
            )
        )
        free_time = exit_ms + v1.BUCKET_MS
        if nav <= 0:
            break
    return trades, {"ending_nav": nav, "maximum_drawdown": maximum_drawdown}


def account_metrics_v3(trades: list[AccountTradeV3], state: dict[str, float]) -> dict:
    days = list(d2.DEVELOPMENT_DAYS)
    if not trades:
        return d2.account_metrics([], state)
    frame = pd.DataFrame([asdict(item) for item in trades])
    daily = frame.groupby("day").account_return.apply(
        lambda values: float(np.prod(1.0 + values.to_numpy(float)) - 1.0)
    ).reindex(days, fill_value=0.0)
    positive_frame = frame.loc[frame.net_pnl > 0].copy()
    positive = positive_frame.net_pnl.to_numpy(float)
    negative = frame.loc[frame.net_pnl < 0, "net_pnl"].to_numpy(float)
    positive_sum = float(positive.sum())
    positive_by_symbol = positive_frame.groupby("symbol").net_pnl.sum()
    year_returns = {}
    for year in (2022, 2023):
        values = daily.loc[[day.startswith(str(year)) for day in daily.index]].to_numpy(float)
        year_returns[year] = float(np.prod(1.0 + values) - 1.0)
    counts = frame.groupby("day").size().reindex(days, fill_value=0)
    return {
        "n": int(len(frame)),
        "eligible_days": len(days),
        "trades_per_day_median": float(counts.median()),
        "positive_day_fraction": float((daily > 0).mean()),
        "total_return": float(state["ending_nav"] / d2.INITIAL_NAV - 1.0),
        "geometric_sample_day_return": float(np.expm1(np.log1p(daily).mean())),
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) else None,
        "maximum_drawdown": float(state["maximum_drawdown"]),
        "top10pct_removed_return": d2.removed_path_return(frame, 0.10),
        "top5_positive_share": float(np.sort(positive)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0,
        "return_2022": year_returns[2022],
        "return_2023": year_returns[2023],
        "maximum_single_symbol_positive_pnl_share": float(positive_by_symbol.max() / positive_sum) if positive_sum > 0 else 1.0,
        "symbol_net_pnl": frame.groupby("symbol").net_pnl.sum().to_dict(),
        "symbol_positive_pnl": positive_by_symbol.to_dict(),
        "day_returns": daily.to_dict(),
        "exit_liquidity_overrun_count": int(frame.exit_liquidity_overrun.sum()),
        "maximum_intratrade_drawdown": float(frame.maximum_intratrade_drawdown.max()),
    }


def patch_development() -> None:
    v2.patch_v1()
    d2.simulate_account = simulate_account_v3
    d2.account_metrics = account_metrics_v3


def self_test() -> None:
    row = pd.Series({
        "bn_bid": 99.9,
        "bn_ask": 100.1,
        "bn_bid_amount": 0.01,
        "bn_ask_amount": 100.0,
    })
    forced = mandatory_exit_price(row, 1, 1.0)
    assert forced is not None and forced[1] is True and forced[0] < row.bn_bid
    adequate = pd.Series({
        "bn_bid": 99.9,
        "bn_ask": 100.1,
        "bn_bid_amount": 100.0,
        "bn_ask_amount": 100.0,
    })
    normal = mandatory_exit_price(adequate, 1, 1.0)
    assert normal is not None and normal[1] is False
    print("cross-venue development V3 self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    patch_development()
    if args.self_test:
        self_test()
        return 0
    result = d2.run(args.pilot_dir, args.output, args.cache)
    result["account_engine_version"] = 3
    result["v2_development_promotion_admissible"] = False
    path = args.output / "DEVELOPMENT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "stage": result["stage"],
        "account_engine_version": 3,
        "development_gate_pass_count": int(result.get("development_gate_pass_count", 0)),
        "selection_opened": False,
        "2026_opened": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
