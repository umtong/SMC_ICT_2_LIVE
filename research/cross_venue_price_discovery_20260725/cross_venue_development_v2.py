from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import cross_venue_pilot as v1
import cross_venue_pilot_v2 as v2

PILOT_DAYS = set(v1.PILOT_DAYS)
DEVELOPMENT_DAYS = tuple(
    f"{year}-{month:02d}-01"
    for year in (2022, 2023)
    for month in range(1, 13)
    if f"{year}-{month:02d}-01" not in PILOT_DAYS
)
FEE_LEVELS = (5.0, 7.5, 10.0)
INITIAL_NAV = 10_000.0
RISK_FRACTION = 0.005
MAX_LEVERAGE = 3.0
MAX_TOP_QUOTE_PARTICIPATION = 0.05
FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000


@dataclass(frozen=True, slots=True)
class AccountTrade:
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


def config_from_row(row: pd.Series) -> v1.Config:
    return v1.Config(
        str(row.family),
        int(row.observation_ms),
        float(row.displacement_spreads),
        float(row.flow_imbalance),
        float(row.follower_fraction),
        int(row.latency_ms),
        int(row.hold_ms),
        float(row.stop_spreads),
        float(row.basis_z),
    )


def freeze_pilot_representatives(pilot_dir: Path, output: Path) -> list[v1.Config]:
    result = json.loads((pilot_dir / "PILOT_RESULT.json").read_text(encoding="utf-8"))
    if result.get("causal_version") != 2 or result.get("v1_outputs_admissible") is not False:
        raise ValueError("pilot is not admissible causal V2")
    table = pd.read_csv(pilot_dir / "PILOT_CANDIDATES.csv")
    passed = table.loc[table.fatal_edge_pass.astype(bool)].copy()
    chosen: list[pd.Series] = []
    if not passed.empty:
        passed = passed.sort_values(
            ["ten_fee_total_return", "top10pct_removed_mean_bps", "config_id"],
            ascending=[False, False, True],
        )
        used: set[str] = set()
        for _, row in passed.groupby(["family", "latency_ms"], sort=True).head(1).iterrows():
            if row.config_id not in used:
                chosen.append(row)
                used.add(str(row.config_id))
        for _, row in passed.iterrows():
            if len(chosen) >= 12:
                break
            if str(row.config_id) not in used:
                chosen.append(row)
                used.add(str(row.config_id))
    configs = [config_from_row(row) for row in chosen[:12]]
    payload = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-1850-XVENUE-001",
        "source_pilot_sha256": hashlib.sha256((pilot_dir / "PILOT_RESULT.json").read_bytes()).hexdigest(),
        "causal_version": 2,
        "pilot_fatal_edge_pass_count": int(result["fatal_edge_pass_count"]),
        "representatives": [asdict(config) | {"config_id": config.config_id} for config in configs],
        "development_days": list(DEVELOPMENT_DAYS),
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
    }
    path = output / "FROZEN_PILOT_REPRESENTATIVES.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "FROZEN_PILOT_REPRESENTATIVES.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8"
    )
    return configs


def funding_collision(entry_ms: int, maximum_exit_ms: int) -> bool:
    next_settlement = ((entry_ms + FUNDING_INTERVAL_MS - 1) // FUNDING_INTERVAL_MS) * FUNDING_INTERVAL_MS
    return entry_ms <= next_settlement <= maximum_exit_ms


def fill_price(row: pd.Series, side: int, entering: bool, quantity: float) -> tuple[float, float] | None:
    if entering:
        quote = float(row.bn_ask if side > 0 else row.bn_bid)
        available = float(row.bn_ask_amount if side > 0 else row.bn_bid_amount)
    else:
        quote = float(row.bn_bid if side > 0 else row.bn_ask)
        available = float(row.bn_bid_amount if side > 0 else row.bn_ask_amount)
    if not all(math.isfinite(value) for value in (quote, available)) or quote <= 0 or available <= 0:
        return None
    participation = quantity / available
    if participation > MAX_TOP_QUOTE_PARTICIPATION + 1e-12:
        return None
    spread = float(row.bn_ask - row.bn_bid)
    impact = spread * 0.25 * max(participation / MAX_TOP_QUOTE_PARTICIPATION, 0.0)
    price = quote + side * impact if entering else quote - side * impact
    return price, spread


def size_position(row: pd.Series, side: int, stop_mid: float, nav: float, fee_bps: float) -> tuple[float, float, float, float] | None:
    reference = float(row.bn_ask if side > 0 else row.bn_bid)
    available = float(row.bn_ask_amount if side > 0 else row.bn_bid_amount)
    spread = float(row.bn_ask - row.bn_bid)
    if not all(math.isfinite(value) for value in (reference, available, spread)) or reference <= 0 or available <= 0 or spread <= 0:
        return None
    max_quantity = min(MAX_LEVERAGE * nav / reference, MAX_TOP_QUOTE_PARTICIPATION * available)
    if max_quantity <= 0:
        return None
    quantity = max_quantity
    for _ in range(4):
        entry = fill_price(row, side, True, quantity)
        if entry is None:
            return None
        entry_price = entry[0]
        participation = quantity / available
        stop_impact = spread * (0.5 + 0.25 * max(participation / MAX_TOP_QUOTE_PARTICIPATION, 0.0))
        stop_execution = stop_mid - side * stop_impact
        unit_loss = abs(entry_price - stop_execution) + (entry_price + abs(stop_execution)) * fee_bps / 10_000.0
        if not math.isfinite(unit_loss) or unit_loss <= 0:
            return None
        risk_quantity = nav * RISK_FRACTION / unit_loss
        new_quantity = min(max_quantity, risk_quantity)
        if abs(new_quantity - quantity) <= max(1e-12, 1e-6 * quantity):
            quantity = new_quantity
            break
        quantity = new_quantity
    entry = fill_price(row, side, True, quantity)
    if entry is None or quantity <= 0:
        return None
    entry_price = entry[0]
    planned_loss = quantity * (
        abs(entry_price - stop_mid)
        + (entry_price + abs(stop_mid)) * fee_bps / 10_000.0
        + spread
    )
    leverage = quantity * entry_price / nav
    if planned_loss > nav * RISK_FRACTION * 1.05 or leverage > MAX_LEVERAGE + 1e-9:
        return None
    return quantity, entry_price, leverage, planned_loss


def simulate_account(
    frames: dict[tuple[str, str], pd.DataFrame],
    events: list[v1.Event],
    config: v1.Config,
    fee_bps: float,
) -> tuple[list[AccountTrade], dict[str, float]]:
    nav = INITIAL_NAV
    peak = nav
    maximum_drawdown = 0.0
    free_time = -1
    trades: list[AccountTrade] = []
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
        if funding_collision(entry_ms, maximum_exit_ms):
            continue
        entry_row = quotes.iloc[entry_pos]
        entry_mid = float(entry_row.bn_mid)
        spread = float(entry_row.bn_ask - entry_row.bn_bid)
        stop_mid = entry_mid - event.side * config.stop_spreads * spread
        sized = size_position(entry_row, event.side, stop_mid, nav, fee_bps)
        if sized is None:
            continue
        quantity, entry_price, leverage, _planned_loss = sized
        exit_pos = min(int(np.searchsorted(quote_times, maximum_exit_ms, side="left")), len(quote_times) - 1)
        reason = "horizon"
        chosen = exit_pos
        initial_gap = abs(event.initial_basis_residual)
        frame_times = frame.index.to_numpy(np.int64)
        for position in range(entry_pos, exit_pos + 1):
            row = quotes.iloc[position]
            mid = float(row.bn_mid)
            if (event.side > 0 and mid <= stop_mid) or (event.side < 0 and mid >= stop_mid):
                chosen, reason = position, "protective_stop"
                break
            current_basis = math.log(float(row.bb_mid) / mid)
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
        exit_fill = fill_price(quotes.iloc[chosen], event.side, False, quantity)
        if exit_fill is None:
            continue
        exit_price = exit_fill[0]
        gross = event.side * quantity * (exit_price - entry_price)
        fees = quantity * (entry_price + exit_price) * fee_bps / 10_000.0
        net = gross - fees
        before = nav
        nav += net
        account_return = net / before
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, 1.0 - nav / peak)
        trades.append(
            AccountTrade(
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
            )
        )
        free_time = exit_ms + v1.BUCKET_MS
        if nav <= 0:
            break
    return trades, {"ending_nav": nav, "maximum_drawdown": maximum_drawdown}


def removed_path_return(frame: pd.DataFrame, fraction: float) -> float | None:
    if frame.empty:
        return None
    count = max(1, int(math.ceil(len(frame) * fraction)))
    removed = set(frame.nlargest(count, "account_return").index)
    retained = frame.loc[~frame.index.isin(removed), "account_return"].to_numpy(float)
    return float(np.prod(1.0 + retained) - 1.0) if len(retained) else None


def account_metrics(trades: list[AccountTrade], state: dict[str, float]) -> dict:
    days = list(DEVELOPMENT_DAYS)
    if not trades:
        return {
            "n": 0,
            "eligible_days": len(days),
            "trades_per_day_median": 0.0,
            "positive_day_fraction": 0.0,
            "total_return": 0.0,
            "geometric_sample_day_return": 0.0,
            "profit_factor": None,
            "maximum_drawdown": 0.0,
            "top10pct_removed_return": None,
            "top5_positive_share": 1.0,
            "return_2022": 0.0,
            "return_2023": 0.0,
            "maximum_single_symbol_positive_pnl_share": 1.0,
        }
    frame = pd.DataFrame([asdict(item) for item in trades])
    daily = frame.groupby("day").account_return.apply(lambda x: float(np.prod(1.0 + x.to_numpy(float)) - 1.0)).reindex(days, fill_value=0.0)
    positive = frame.loc[frame.net_pnl > 0, "net_pnl"].to_numpy(float)
    negative = frame.loc[frame.net_pnl < 0, "net_pnl"].to_numpy(float)
    positive_sum = float(positive.sum())
    by_symbol = frame.groupby("symbol").net_pnl.sum()
    positive_symbol = by_symbol.clip(lower=0)
    symbol_positive_sum = float(positive_symbol.sum())
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
        "total_return": float(state["ending_nav"] / INITIAL_NAV - 1.0),
        "geometric_sample_day_return": float(np.expm1(np.log1p(daily).mean())),
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) else None,
        "maximum_drawdown": float(state["maximum_drawdown"]),
        "top10pct_removed_return": removed_path_return(frame, 0.10),
        "top5_positive_share": float(np.sort(positive)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0,
        "return_2022": year_returns[2022],
        "return_2023": year_returns[2023],
        "maximum_single_symbol_positive_pnl_share": float(positive_symbol.max() / symbol_positive_sum) if symbol_positive_sum > 0 else 1.0,
        "symbol_net_pnl": by_symbol.to_dict(),
        "day_returns": daily.to_dict(),
    }


def passes(metrics_by_fee: dict[float, dict]) -> bool:
    base = metrics_by_fee[5.0]
    return (
        base["n"] >= 500
        and base["trades_per_day_median"] >= 10
        and all(metrics_by_fee[fee]["total_return"] > 0 for fee in FEE_LEVELS)
        and base["return_2022"] > 0
        and base["return_2023"] > 0
        and base["positive_day_fraction"] >= 0.60
        and (base["top10pct_removed_return"] is not None and base["top10pct_removed_return"] > 0)
        and base["top5_positive_share"] <= 0.20
        and (base["profit_factor"] is not None and base["profit_factor"] >= 1.10)
        and base["maximum_drawdown"] <= 0.20
        and base["maximum_single_symbol_positive_pnl_share"] <= 0.70
    )


def run(pilot_dir: Path, output: Path, cache: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    v2.patch_v1()
    configs = freeze_pilot_representatives(pilot_dir, output)
    if not configs:
        result = {
            "schema_version": 1,
            "claim_id": "CLM-20260725-1850-XVENUE-001",
            "stage": "DEVELOPMENT_BLOCKED_BY_FATAL_PILOT",
            "causal_version": 2,
            "development_opened": False,
            "selection_opened": False,
            "confirmation_opened": False,
            "2026_opened": False,
            "orders_submitted": False,
            "champion_eligible": False,
            "reason": "No causal V2 pilot configuration passed the fatal edge gate.",
        }
        path = output / "DEVELOPMENT_RESULT.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result

    frames: dict[tuple[str, str], pd.DataFrame] = {}
    sources: list[dict] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-venue-development-v2/1.0"
        for day in DEVELOPMENT_DAYS:
            for symbol in v1.SYMBOLS:
                frame, records = v1.load_day(cache, session, day, symbol)
                frames[(day, symbol)] = frame
                sources.extend(records)
                print(json.dumps({"day": day, "symbol": symbol, "aligned_rows": len(frame)}), flush=True)

    rows = []
    ledgers = []
    selections = []
    for config in configs:
        events: list[v1.Event] = []
        for (day, symbol), frame in frames.items():
            events.extend(v2.signal_events_v2(frame, config, day, symbol))
        metrics_by_fee: dict[float, dict] = {}
        for fee in FEE_LEVELS:
            trades, state = simulate_account(frames, events, config, fee)
            metrics = account_metrics(trades, state)
            metrics_by_fee[fee] = metrics
            rows.append({
                "config_id": config.config_id,
                **asdict(config),
                "fee_bps_per_side": fee,
                "event_count": len(events),
                **{key: value for key, value in metrics.items() if not isinstance(value, dict)},
            })
            if fee == 5.0 and trades:
                ledger = pd.DataFrame([asdict(item) for item in trades])
                ledger["config_id"] = config.config_id
                ledgers.append(ledger)
        selected = passes(metrics_by_fee)
        selections.append({
            "config_id": config.config_id,
            "config": asdict(config),
            "development_pass": selected,
            "metrics": {str(fee): metrics_by_fee[fee] for fee in FEE_LEVELS},
        })
        print(json.dumps({"config_id": config.config_id, "development_pass": selected}), flush=True)

    pd.DataFrame(rows).to_csv(output / "DEVELOPMENT_GRID.csv", index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(output / "DEVELOPMENT_5BPS_LEDGERS.csv", index=False)
    passed = [item for item in selections if item["development_pass"]]
    passed.sort(
        key=lambda item: min(
            item["metrics"]["5.0"]["return_2022"],
            item["metrics"]["5.0"]["return_2023"],
            item["metrics"]["7.5"]["total_return"],
            item["metrics"]["10.0"]["total_return"],
        ),
        reverse=True,
    )
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-1850-XVENUE-001",
        "stage": "CAUSAL_V2_RISK_BASED_DEVELOPMENT",
        "causal_version": 2,
        "development_days": list(DEVELOPMENT_DAYS),
        "development_opened": True,
        "representatives_tested": len(configs),
        "development_gate_pass_count": len(passed),
        "family_selections": selections,
        "frozen_development_representatives": passed[:12],
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "champion_eligible": False,
        "source_records": sources,
    }
    path = output / "DEVELOPMENT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (output / "DEVELOPMENT_RESULT.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.pilot_dir, args.output, args.cache)
    print(json.dumps({
        "stage": result["stage"],
        "development_gate_pass_count": result.get("development_gate_pass_count", 0),
        "selection_opened": False,
        "2026_opened": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
