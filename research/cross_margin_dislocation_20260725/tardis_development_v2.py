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

import tardis_pilot as pilot

PILOT_DAYS = set(pilot.PILOT_DAYS)
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


@dataclass(frozen=True, slots=True)
class AccountTrade:
    config_id: str
    day: str
    asset: str
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


def config_from_row(row: pd.Series) -> pilot.Config:
    return pilot.Config(
        str(row.family), int(row.observation_ms), float(row.displacement_spreads),
        float(row.flow_imbalance), float(row.follower_fraction), int(row.latency_ms),
        int(row.hold_ms), float(row.stop_spreads), float(row.basis_z),
    )


def freeze_representatives(pilot_dir: Path, output: Path) -> list[pilot.Config]:
    result_path = pilot_dir / "PILOT_RESULT.json"
    table_path = pilot_dir / "PILOT_CANDIDATES.csv"
    if not result_path.exists() or not table_path.exists():
        raise FileNotFoundError("pilot result or candidate table missing")
    result = json.loads(result_path.read_text())
    table = pd.read_csv(table_path)
    passed = table.loc[table.fatal_edge_pass.astype(bool)].copy()
    chosen: list[pd.Series] = []
    used: set[str] = set()
    if not passed.empty:
        passed = passed.sort_values(
            ["ten_fee_total_return", "top10pct_removed_mean_bps", "config_id"],
            ascending=[False, False, True],
        )
        for _, row in passed.groupby(["family", "latency_ms"], sort=True).head(1).iterrows():
            cid = str(row.config_id)
            if cid not in used:
                chosen.append(row)
                used.add(cid)
        for _, row in passed.iterrows():
            if len(chosen) >= 12:
                break
            cid = str(row.config_id)
            if cid not in used:
                chosen.append(row)
                used.add(cid)
    configs = [config_from_row(row) for row in chosen[:12]]
    frozen = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-2120-CROSS-MARGIN-001",
        "dataset_revision": "TARDIS_PUBLIC_NORMALIZED_SAMPLE_V1",
        "pilot_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "pilot_fatal_edge_pass_count": int(result.get("fatal_edge_pass_count", 0)),
        "representatives": [asdict(config) | {"config_id": config.config_id} for config in configs],
        "development_days": list(DEVELOPMENT_DAYS),
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
    }
    path = output / "FROZEN_PILOT_REPRESENTATIVES.json"
    path.write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n")
    (output / "FROZEN_PILOT_REPRESENTATIVES.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
    )
    return configs


def forced_exit(row: pd.Series, side: int, quantity: float) -> tuple[float, bool]:
    quote = float(row.um_bid if side > 0 else row.um_ask)
    amount = float(row.um_bid_amount if side > 0 else row.um_ask_amount)
    spread = float(row.um_ask - row.um_bid)
    if not all(math.isfinite(value) for value in (quote, amount, spread)) or quote <= 0 or amount <= 0 or spread <= 0:
        raise ValueError("entered trade reached unusable actual USD-M exit quote")
    participation = quantity / amount
    normalized = participation / MAX_TOP_QUOTE_PARTICIPATION
    impact = spread * (0.25 * min(normalized, 1.0) + 2.0 * max(normalized - 1.0, 0.0))
    price = max(quote * 0.10, quote - impact) if side > 0 else quote + impact
    return price, participation > MAX_TOP_QUOTE_PARTICIPATION


def entry_fill(row: pd.Series, side: int, quantity: float) -> float | None:
    quote = float(row.um_ask if side > 0 else row.um_bid)
    amount = float(row.um_ask_amount if side > 0 else row.um_bid_amount)
    spread = float(row.um_ask - row.um_bid)
    if not all(math.isfinite(value) for value in (quote, amount, spread)) or quote <= 0 or amount <= 0 or spread <= 0:
        return None
    participation = quantity / amount
    if participation > MAX_TOP_QUOTE_PARTICIPATION + 1e-12:
        return None
    impact = spread * 0.25 * max(participation / MAX_TOP_QUOTE_PARTICIPATION, 0.0)
    return quote + side * impact


def size_position(row: pd.Series, side: int, stop: float, nav: float, fee: float) -> tuple[float, float, float] | None:
    reference = float(row.um_ask if side > 0 else row.um_bid)
    amount = float(row.um_ask_amount if side > 0 else row.um_bid_amount)
    spread = float(row.um_ask - row.um_bid)
    if not all(math.isfinite(value) for value in (reference, amount, spread)) or reference <= 0 or amount <= 0 or spread <= 0:
        return None
    maximum = min(MAX_LEVERAGE * nav / reference, MAX_TOP_QUOTE_PARTICIPATION * amount)
    quantity = maximum
    if quantity <= 0:
        return None
    for _ in range(4):
        entry = entry_fill(row, side, quantity)
        if entry is None:
            return None
        stop_execution = stop - side * spread * 0.75
        unit_loss = abs(entry - stop_execution) + (entry + abs(stop_execution)) * fee / 10_000.0
        if not math.isfinite(unit_loss) or unit_loss <= 0:
            return None
        updated = min(maximum, nav * RISK_FRACTION / unit_loss)
        if abs(updated - quantity) <= max(1e-12, quantity * 1e-6):
            quantity = updated
            break
        quantity = updated
    entry = entry_fill(row, side, quantity)
    if entry is None or quantity <= 0:
        return None
    leverage = quantity * entry / nav
    planned_loss = quantity * (
        abs(entry - stop) + (entry + abs(stop)) * fee / 10_000.0 + spread
    )
    if leverage > MAX_LEVERAGE + 1e-9 or planned_loss > nav * RISK_FRACTION * 1.05:
        return None
    return quantity, entry, leverage


def simulate_account(frames: dict[tuple[str, str], pd.DataFrame], events: list[pilot.Event], config: pilot.Config, fee: float) -> tuple[list[AccountTrade], dict[str, float]]:
    nav = INITIAL_NAV
    closed_peak = nav
    closed_drawdown = 0.0
    maximum_intratrade_drawdown = 0.0
    free = -1
    trades: list[AccountTrade] = []
    quote_frames = {key: frame.loc[frame.um_quote_actual].copy() for key, frame in frames.items()}
    for event in sorted(events, key=lambda item: (item.decision_ms, -item.score, item.asset, item.family)):
        if event.decision_ms < free:
            continue
        frame = frames[(event.day, event.asset)]
        quotes = quote_frames[(event.day, event.asset)]
        if quotes.empty:
            continue
        quote_times = quotes.um_quote_event_ms.to_numpy(np.int64)
        start = int(np.searchsorted(quote_times, event.decision_ms + config.latency_ms, side="left"))
        if start >= len(quote_times):
            continue
        entry_ms = int(quote_times[start])
        row = quotes.iloc[start]
        spread = float(row.um_ask - row.um_bid)
        stop = float(row.um_mid) - event.side * config.stop_spreads * spread
        sized = size_position(row, event.side, stop, nav, fee)
        if sized is None:
            continue
        quantity, entered, leverage = sized
        entry_fee = quantity * entered * fee / 10_000.0
        end = min(int(np.searchsorted(quote_times, entry_ms + config.hold_ms, side="left")), len(quote_times) - 1)
        chosen, reason = end, "horizon"
        initial_gap = abs(event.initial_basis_residual)
        frame_times = frame.index.to_numpy(np.int64)
        trade_peak = nav
        trade_dd = 0.0
        for position in range(start, end + 1):
            current = quotes.iloc[position]
            marked, _ = forced_exit(current, event.side, quantity)
            mark_fee = quantity * marked * fee / 10_000.0
            mark_nav = nav + event.side * quantity * (marked - entered) - entry_fee - mark_fee
            trade_peak = max(trade_peak, mark_nav)
            trade_dd = max(trade_dd, 1.0 - mark_nav / max(trade_peak, 1e-12))
            executable_stop = float(current.um_bid) <= stop if event.side > 0 else float(current.um_ask) >= stop
            if executable_stop:
                chosen, reason = position, "protective_stop"
                break
            basis = math.log(float(current.cm_mid) / float(current.um_mid))
            bucket = int(quotes.index[position])
            history_end = int(np.searchsorted(frame_times, bucket, side="right"))
            hist_start = max(0, history_end - 601)
            hist_stop = max(hist_start, history_end - 1)
            history = np.log(frame.cm_mid.iloc[hist_start:hist_stop]) - np.log(frame.um_mid.iloc[hist_start:hist_stop])
            if len(history) >= 300:
                residual = basis - float(history.median())
                if initial_gap > 0 and abs(residual) <= 0.25 * initial_gap:
                    chosen, reason = position, "basis_convergence"
                    break
        exited, overrun = forced_exit(quotes.iloc[chosen], event.side, quantity)
        exit_fee = quantity * exited * fee / 10_000.0
        gross = event.side * quantity * (exited - entered)
        fees = entry_fee + exit_fee
        net = gross - fees
        before = nav
        nav += net
        account_return = net / before
        closed_peak = max(closed_peak, nav)
        closed_drawdown = max(closed_drawdown, 1.0 - nav / max(closed_peak, 1e-12))
        maximum_intratrade_drawdown = max(maximum_intratrade_drawdown, trade_dd)
        trades.append(AccountTrade(config.config_id, event.day, event.asset, event.family, event.decision_ms, entry_ms, int(quote_times[chosen]), event.side, entered, exited, stop, quantity, quantity * entered, leverage, gross, fees, net, account_return, before, nav, reason, event.score, overrun, trade_dd))
        free = int(quote_times[chosen]) + pilot.BUCKET_MS
        if nav <= 0:
            break
    conservative_drawdown = min(1.0, closed_drawdown + maximum_intratrade_drawdown)
    return trades, {"ending_nav": nav, "closed_drawdown": closed_drawdown, "maximum_intratrade_drawdown": maximum_intratrade_drawdown, "maximum_drawdown": conservative_drawdown}


def removed_path_return(frame: pd.DataFrame, fraction: float) -> float | None:
    if frame.empty:
        return None
    count = max(1, int(math.ceil(len(frame) * fraction)))
    removed = set(frame.nlargest(count, "account_return").index)
    values = frame.loc[~frame.index.isin(removed), "account_return"].to_numpy(float)
    return float(np.prod(1.0 + values) - 1.0) if len(values) else None


def account_metrics(trades: list[AccountTrade], state: dict[str, float]) -> dict:
    days = list(DEVELOPMENT_DAYS)
    if not trades:
        return {"n": 0, "eligible_days": len(days), "trades_per_day_median": 0.0, "positive_day_fraction": 0.0, "total_return": 0.0, "geometric_sample_day_return": 0.0, "profit_factor": None, "maximum_drawdown": 0.0, "top10pct_removed_return": None, "top5_positive_share": 1.0, "return_2022": 0.0, "return_2023": 0.0, "maximum_single_asset_positive_pnl_share": 1.0}
    frame = pd.DataFrame([asdict(item) for item in trades])
    daily = frame.groupby("day").account_return.apply(lambda values: float(np.prod(1.0 + values.to_numpy(float)) - 1.0)).reindex(days, fill_value=0.0)
    positive_frame = frame.loc[frame.net_pnl > 0]
    positive = positive_frame.net_pnl.to_numpy(float)
    negative = frame.loc[frame.net_pnl < 0, "net_pnl"].to_numpy(float)
    positive_sum = float(positive.sum())
    positive_by_asset = positive_frame.groupby("asset").net_pnl.sum()
    returns = {}
    for year in (2022, 2023):
        values = daily.loc[[day.startswith(str(year)) for day in daily.index]].to_numpy(float)
        returns[year] = float(np.prod(1.0 + values) - 1.0)
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
        "closed_drawdown": float(state["closed_drawdown"]),
        "maximum_intratrade_drawdown": float(state["maximum_intratrade_drawdown"]),
        "top10pct_removed_return": removed_path_return(frame, 0.10),
        "top5_positive_share": float(np.sort(positive)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0,
        "return_2022": returns[2022],
        "return_2023": returns[2023],
        "maximum_single_asset_positive_pnl_share": float(positive_by_asset.max() / positive_sum) if positive_sum > 0 else 1.0,
        "asset_net_pnl": frame.groupby("asset").net_pnl.sum().to_dict(),
        "asset_positive_pnl": positive_by_asset.to_dict(),
        "day_returns": daily.to_dict(),
        "exit_liquidity_overrun_count": int(frame.exit_liquidity_overrun.sum()),
    }


def passes(by_fee: dict[float, dict]) -> bool:
    base = by_fee[5.0]
    return (
        base["n"] >= 500
        and base["trades_per_day_median"] >= 10
        and all(by_fee[fee]["total_return"] > 0 for fee in FEE_LEVELS)
        and base["return_2022"] > 0
        and base["return_2023"] > 0
        and base["positive_day_fraction"] >= 0.60
        and (base["top10pct_removed_return"] is not None and base["top10pct_removed_return"] > 0)
        and base["top5_positive_share"] <= 0.20
        and (base["profit_factor"] is not None and base["profit_factor"] >= 1.10)
        and base["maximum_drawdown"] <= 0.20
        and base["maximum_single_asset_positive_pnl_share"] <= 0.70
    )


def run(pilot_dir: Path, output: Path, cache: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    configs = freeze_representatives(pilot_dir, output)
    if not configs:
        result = {"schema_version": 2, "claim_id": "CLM-20260725-2120-CROSS-MARGIN-001", "stage": "DEVELOPMENT_BLOCKED_BY_FATAL_PILOT", "development_opened": False, "selection_opened": False, "confirmation_opened": False, "2026_opened": False, "orders_submitted": False, "paper_live_started": False, "champion_eligible": False}
        (output / "DEVELOPMENT_RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result
    frames = {}
    sources = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-margin-development/1.0"
        for day in DEVELOPMENT_DAYS:
            for asset in pilot.ROUTES:
                frame, records = pilot.load_day(cache, session, day, asset)
                frames[(day, asset)] = frame
                sources.extend(records)
                print(json.dumps({"day": day, "asset": asset, "aligned_rows": len(frame)}), flush=True)
    rows = []
    selections = []
    ledgers = []
    for config in configs:
        events = []
        for (day, asset), frame in frames.items():
            events.extend(pilot.signals(frame, config, day, asset))
        by_fee = {}
        for fee in FEE_LEVELS:
            trades, state = simulate_account(frames, events, config, fee)
            metrics = account_metrics(trades, state)
            by_fee[fee] = metrics
            rows.append({"config_id": config.config_id, **asdict(config), "fee_bps_per_side": fee, "event_count": len(events), **{key: value for key, value in metrics.items() if not isinstance(value, dict)}})
            if fee == 5.0 and trades:
                ledgers.append(pd.DataFrame([asdict(item) for item in trades]))
        passed = passes(by_fee)
        selections.append({"config_id": config.config_id, "config": asdict(config), "development_pass": passed, "metrics": {str(fee): by_fee[fee] for fee in FEE_LEVELS}})
        print(json.dumps({"config_id": config.config_id, "development_pass": passed}), flush=True)
    pd.DataFrame(rows).to_csv(output / "DEVELOPMENT_GRID.csv", index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(output / "DEVELOPMENT_5BPS_LEDGERS.csv", index=False)
    passed = [item for item in selections if item["development_pass"]]
    passed.sort(key=lambda item: min(item["metrics"]["5.0"]["return_2022"], item["metrics"]["5.0"]["return_2023"], item["metrics"]["7.5"]["total_return"], item["metrics"]["10.0"]["total_return"]), reverse=True)
    result = {
        "schema_version": 2,
        "claim_id": "CLM-20260725-2120-CROSS-MARGIN-001",
        "dataset_revision": "TARDIS_PUBLIC_NORMALIZED_SAMPLE_V1",
        "stage": "RISK_BASED_SYSTEMATIC_SAMPLE_DEVELOPMENT",
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
        "target_1pct_daily_test_admissible": False,
        "source_records": sources,
    }
    path = output / "DEVELOPMENT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    (output / "DEVELOPMENT_RESULT.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    return result


def self_test() -> None:
    row = pd.Series({"um_bid": 99.9, "um_ask": 100.1, "um_bid_amount": 0.01, "um_ask_amount": 100.0})
    price, overrun = forced_exit(row, 1, 1.0)
    assert overrun and price < row.um_bid
    print("cross-margin development self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    result = run(args.pilot_dir, args.output, args.cache)
    print(json.dumps({"stage": result["stage"], "development_gate_pass_count": int(result.get("development_gate_pass_count", 0)), "selection_opened": False, "2026_opened": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
