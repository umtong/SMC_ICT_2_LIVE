from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/mnt/data")
import channel_independent_audit as a

THRESHOLD = 2.2706072565238586
SUBSET = {("BTCUSDT", 1), ("ETHUSDT", 1), ("ETHUSDT", -1)}
GRID = [
    (0.005, 3.0), (0.01, 5.0), (0.02, 8.0), (0.05, 12.0),
    (0.075, 12.0), (0.10, 12.0), (0.125, 12.0), (0.15, 12.0),
    (0.20, 12.0), (0.30, 12.0), (0.40, 12.0), (0.60, 12.0),
]
PRE_START = pd.Timestamp("2022-01-01T00:00:00Z")
PRE_END = pd.Timestamp("2024-01-01T00:00:00Z")
BLOCK_DAYS = 30
RESAMPLES = 4000
SEED = 202607301238


def bootstrap_summary(log_returns: np.ndarray) -> dict[str, float | int]:
    x = np.asarray(log_returns, dtype=float)
    if x.ndim != 1 or len(x) != 730 or not np.isfinite(x).all():
        raise ValueError("expected 730 finite daily log returns")
    rng = np.random.default_rng(SEED)
    offsets = np.arange(BLOCK_DAYS, dtype=np.int64)
    block_count = math.ceil(len(x) / BLOCK_DAYS)
    means = np.empty(RESAMPLES, dtype=float)
    for i in range(RESAMPLES):
        starts = rng.integers(0, len(x), size=block_count, endpoint=False)
        indices = (starts[:, None] + offsets[None, :]) % len(x)
        means[i] = float(x[indices.reshape(-1)[: len(x)]].mean())
    return {
        "mean_log_growth": float(x.mean()),
        "q05_mean_log_growth": float(np.quantile(means, 0.05)),
        "median_mean_log_growth": float(np.quantile(means, 0.50)),
        "q95_mean_log_growth": float(np.quantile(means, 0.95)),
        "block_days": BLOCK_DAYS,
        "resamples": RESAMPLES,
        "seed": SEED,
    }


def guard(trades: pd.DataFrame) -> tuple[bool, float | None]:
    if trades.empty:
        return True, None
    leverage = trades.leverage.to_numpy(float)
    stop_distance = (trades.entry - trades.stop).abs().to_numpy(float) / trades.entry.to_numpy(float)
    liquidation_distance = np.where(leverage > 0, 1.0 / leverage - 0.0065, np.inf)
    headroom = liquidation_distance - stop_distance - 0.01
    return bool((headroom > 0).all()), float(headroom.min())


def metrics(trades: pd.DataFrame, nav: float, daily: pd.DataFrame, days: int) -> dict[str, object]:
    if trades.empty:
        return {"end_nav": 10000.0, "multiple": 1.0, "trades": 0, "pf": 0.0, "mdd": 0.0,
                "median": 0.0, "mean": 0.0, "g_daily": 0.0, "max_leverage": 0.0, "top5_share": None}
    gains = trades.loc[trades.pnl > 0, "pnl"]
    loss = -float(trades.loc[trades.pnl < 0, "pnl"].sum())
    return {
        "end_nav": float(nav), "multiple": float(nav / 10000.0), "trades": int(len(trades)),
        "pf": float(gains.sum() / loss) if loss > 0 else float("inf"),
        "mdd": float((1.0 - daily.nav / daily.nav.cummax()).max()),
        "median": float(trades.account_return.median()), "mean": float(trades.account_return.mean()),
        "g_daily": float((nav / 10000.0) ** (1.0 / days) - 1.0) if nav > 0 else -1.0,
        "max_leverage": float(trades.leverage.max()),
        "top5_share": float(gains.nlargest(5).sum() / gains.sum()) if gains.sum() > 0 else None,
    }


def half_years(trades: pd.DataFrame, daily: pd.DataFrame) -> list[dict[str, object]]:
    periods = [
        ("2024H1", "2024-01-01", "2024-07-01"), ("2024H2", "2024-07-01", "2025-01-01"),
        ("2025H1", "2025-01-01", "2025-07-01"), ("2025H2", "2025-07-01", "2026-01-01"),
        ("2026H1", "2026-01-01", "2026-07-01"),
    ]
    out = []
    for name, start, end in periods:
        s = pd.Timestamp(start, tz="UTC")
        e = pd.Timestamp(end, tz="UTC")
        start_nav = float(daily.loc[daily.time == s, "nav"].iloc[0])
        end_nav = float(daily.loc[daily.time == e, "nav"].iloc[0])
        out.append({"period": name, "return": end_nav / start_nav - 1.0,
                    "trades": int(((trades.entry_time >= s) & (trades.entry_time < e)).sum())})
    return out


def episode_summary(trades: pd.DataFrame) -> dict[str, object]:
    x = trades.copy()
    x["month"] = pd.to_datetime(x.entry_time, utc=True).dt.strftime("%Y-%m")
    monthly = x.groupby("month", sort=True).agg(trades=("pnl", "size"), pnl=("pnl", "sum")).reset_index()
    positive = monthly.loc[monthly.pnl > 0, "pnl"]
    return {
        "months_with_trades": int(len(monthly)),
        "positive_months": int((monthly.pnl > 0).sum()),
        "negative_months": int((monthly.pnl < 0).sum()),
        "top3_positive_month_share": float(positive.nlargest(3).sum() / positive.sum()) if positive.sum() > 0 else None,
    }


def daytrading_diagnosis(trades: pd.DataFrame) -> dict[str, object]:
    x = trades.copy()
    x["entry_time"] = pd.to_datetime(x.entry_time, utc=True)
    x["exit_time"] = pd.to_datetime(x.exit_time, utc=True)
    x["hold_hours"] = (x.exit_time - x.entry_time).dt.total_seconds() / 3600.0
    positive = x.loc[x.pnl > 0]
    by_reason = {}
    for reason, group in x.groupby("exit_reason"):
        by_reason[str(reason)] = {"trades": int(len(group)), "wins": int((group.pnl > 0).sum()),
                                  "pnl": float(group.pnl.sum()), "median_hold_hours": float(group.hold_hours.median())}
    return {
        "trades_per_calendar_day": float(len(x) / 912.0),
        "wins": int((x.pnl > 0).sum()), "losses": int((x.pnl < 0).sum()),
        "median_hold_hours": float(x.hold_hours.median()),
        "same_day_exits": int((x.entry_time.dt.date == x.exit_time.dt.date).sum()),
        "within_24h": int((x.hold_hours <= 24).sum()),
        "within_48h": int((x.hold_hours <= 48).sum()),
        "within_48h_wins": int(((x.hold_hours <= 48) & (x.pnl > 0)).sum()),
        "within_48h_pnl": float(x.loc[x.hold_hours <= 48, "pnl"].sum()),
        "over_120h_count": int((x.hold_hours > 120).sum()),
        "over_120h_positive_pnl_share": float(x.loc[(x.hold_hours > 120) & (x.pnl > 0), "pnl"].sum() / positive.pnl.sum()),
        "top10_positive_pnl_share": float(positive.nlargest(10, "pnl").pnl.sum() / positive.pnl.sum()),
        "exit_reason": by_reason,
    }


def build_candidates() -> tuple[pd.DataFrame, dict[str, object]]:
    data = {symbol: a.prepare_symbol(symbol) for symbol in a.SYMBOLS}
    a.add_cross_features(data)
    candidates = a.build_candidates(data)
    expected = {2021: 538, 2022: 511, 2023: 369, 2024: 578, 2025: 598, 2026: 261}
    observed = {int(k): int(v) for k, v in candidates.groupby("year").size().to_dict().items()}
    if len(candidates) != 2855 or observed != expected:
        raise RuntimeError(f"candidate parity failed: {len(candidates)} {observed}")
    return candidates, data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    candidates, data = build_candidates()
    allowed = candidates.apply(lambda row: (row.symbol, int(row.side)) in SUBSET, axis=1)
    candidates["rule"] = np.where((candidates.volume_z168 > THRESHOLD) & allowed, 1.0, -1.0)
    candidates.to_pickle(args.output / "candidates_raw.pkl.gz", compression="gzip")

    result: dict[str, object] = {
        "schema_version": 1,
        "result_id": "RES-20260730-BYBIT-VOLUME-SPONSORED-ROBUST-RISK-001",
        "claim_id": "CLM-20260730-VOLUME-SPONSORED-ROBUST-RISK-001",
        "status": "ROBUST_PRE2024_SIZING_POSITIVE_BUT_REMAINS_EXPANSION_NOT_DAYTRADING_CORE_TARGET_NOT_MET",
        "threshold": THRESHOLD,
        "subset": [f"{symbol}:{side}" for symbol, side in sorted(SUBSET)],
        "grid": [{"risk": risk, "cap": cap} for risk, cap in GRID],
        "pre2024": {}, "selected": None, "official": {},
    }
    ranking = []
    for risk, cap in GRID:
        trades, nav = a.replay(candidates, "rule", PRE_START, PRE_END, 24.0, risk, cap, filtered=True)
        daily = a.daily_nav(trades, data, PRE_START, PRE_END, 24.0)
        item = metrics(trades, nav, daily, 730)
        passed, headroom = guard(trades)
        item["liquidation_guard_pass"] = passed
        item["minimum_liquidation_headroom"] = headroom
        if passed and nav > 0 and len(daily) == 731 and bool((daily.nav > 0).all()):
            item["bootstrap"] = bootstrap_summary(np.diff(np.log(daily.nav.to_numpy(float))))
            ranking.append((item["bootstrap"]["q05_mean_log_growth"], item["bootstrap"]["mean_log_growth"], -risk, -cap))
        key = f"r{risk:g}_c{cap:g}"
        result["pre2024"][key] = item
        trades.to_csv(args.output / f"pre2024_{key}_trades.csv", index=False)
        daily.to_csv(args.output / f"pre2024_{key}_daily.csv", index=False)
    if not ranking:
        raise RuntimeError("no eligible registered path")
    best = max(ranking)
    selected_risk, selected_cap = -best[2], -best[3]
    result["selected"] = {"key": f"r{selected_risk:g}_c{selected_cap:g}", "risk": selected_risk, "cap": selected_cap}

    for cost in (13.0, 18.0, 24.0):
        trades, nav = a.replay(candidates, "rule", a.OFFICIAL_START, a.END, cost, selected_risk, selected_cap, filtered=True)
        daily = a.daily_nav(trades, data, a.OFFICIAL_START, a.END, cost)
        item = metrics(trades, nav, daily, 912)
        item["half_years"] = half_years(trades, daily)
        item["episodes"] = episode_summary(trades)
        passed, headroom = guard(trades)
        item["liquidation_guard_pass"] = passed
        item["minimum_liquidation_headroom"] = headroom
        count = max(1, math.ceil(0.10 * len(trades)))
        removed = set(trades.nlargest(count, "pnl").event_key.astype(str))
        rerouted, rerouted_nav = a.replay(candidates, "rule", a.OFFICIAL_START, a.END, cost, selected_risk, selected_cap, filtered=True, exclude=removed)
        rerouted_daily = a.daily_nav(rerouted, data, a.OFFICIAL_START, a.END, cost)
        winner_removed = metrics(rerouted, rerouted_nav, rerouted_daily, 912)
        winner_removed["removed_count"] = count
        winner_removed["half_years"] = half_years(rerouted, rerouted_daily)
        winner_removed["episodes"] = episode_summary(rerouted)
        item["winner_removed"] = winner_removed
        if cost == 24.0:
            item["daytrading_diagnosis"] = daytrading_diagnosis(trades)
        result["official"][str(int(cost))] = item
        trades.to_csv(args.output / f"official_{int(cost)}bp_trades.csv", index=False)
        daily.to_csv(args.output / f"official_{int(cost)}bp_daily.csv", index=False)
        rerouted.to_csv(args.output / f"official_{int(cost)}bp_winner_removed_trades.csv", index=False)
        rerouted_daily.to_csv(args.output / f"official_{int(cost)}bp_winner_removed_daily.csv", index=False)

    base_trades, base_nav = a.replay(candidates, "rule", a.OFFICIAL_START, a.END, 24.0, 0.10, 12.0, filtered=True)
    if abs(base_nav / 10000.0 - 12.241463081010323) > 1e-12 or len(base_trades) != 110:
        raise RuntimeError("base PR #472 path parity failed")
    result["base_path_exact_reproduction"] = {"multiple_24bp": base_nav / 10000.0, "trades": len(base_trades)}
    official24 = result["official"]["24"]
    result["decision"] = {
        "target_met": bool(official24["g_daily"] >= 0.01),
        "ranking_change": False,
        "daytrading_core": False,
        "classification": "ROBUST_SIZING_DIAGNOSTIC_POSITIVE_BUT_MULTI_DAY_EXPANSION_TARGET_NOT_MET",
    }
    (args.output / "RESULT.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"selected": result["selected"], "decision": result["decision"], "official24": official24}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
