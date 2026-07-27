#!/usr/bin/env python3
"""Higher-density causal SMC/ICT system without changing the core thesis.

V3 adds causally available 1m/3m structures and richer external-liquidity
references (weekly, 4h, opening-range and confirmed equal highs/lows).  The
entry/exit ontology remains liquidity raid -> displacement/MSS -> FVG/OB
revisit -> opposing liquidity delivery.
"""
from __future__ import annotations

import importlib.util
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("swipalnam_v2_fixed", HERE / "liquidity_delivery_ml_v2_fixed.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load V2 fixed module")
v2f = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v2f)
v1 = v2f.v1

ORIGINAL_ENRICH = v1.enrich
ORIGINAL_SWEPT_LEVEL = v1.swept_level


def enrich_v3(frame: pd.DataFrame, minutes: int, streams: dict[str, pd.DataFrame], one_minute: pd.DataFrame) -> pd.DataFrame:
    out = ORIGINAL_ENRICH(frame, minutes, streams, one_minute)
    dt = pd.to_datetime(out["start_time_ms"], unit="ms", utc=True)

    week = dt.to_period("W-SUN").start_time.tz_localize("UTC")
    weekly = out.assign(week=week).groupby("week").agg(week_high=("high", "max"), week_low=("low", "min")).shift(1)
    out["prev_week_high"] = weekly["week_high"].reindex(week).to_numpy()
    out["prev_week_low"] = weekly["week_low"].reindex(week).to_numpy()

    four_hour = (out["start_time_ms"] // (240 * v1.MINUTE_MS)).astype("int64")
    h4 = out.assign(h4=four_hour).groupby("h4").agg(h4_high=("high", "max"), h4_low=("low", "min")).shift(1)
    out["prev_4h_high"] = h4["h4_high"].reindex(four_hour).to_numpy()
    out["prev_4h_low"] = h4["h4_low"].reindex(four_hour).to_numpy()

    hour = dt.hour.to_numpy()
    bucket = np.select([hour < 7, hour < 13, hour < 21], [0, 1, 2], default=3)
    day_no = (dt.floor("D").astype("int64") // (v1.DAY_MS * 1_000_000)).to_numpy()
    sid = day_no * 4 + bucket
    out["session_id_v3"] = sid
    rank = out.groupby("session_id_v3").cumcount()
    opening_bars = max(1, int(math.ceil(60 / minutes)))
    first_hour = rank < opening_bars
    opening_high = out["high"].where(first_hour).groupby(out["session_id_v3"]).transform("max")
    opening_low = out["low"].where(first_hour).groupby(out["session_id_v3"]).transform("min")
    out["opening_range_high"] = opening_high.where(rank >= opening_bars)
    out["opening_range_low"] = opening_low.where(rank >= opening_bars)

    swing_high_event = out["last_swing_high"].where(out["new_swing_high"])
    swing_low_event = out["last_swing_low"].where(out["new_swing_low"])
    prior_high = swing_high_event.ffill().shift(1)
    prior_low = swing_low_event.ffill().shift(1)
    tolerance = out["atr"] * 0.18
    out["equal_high_level"] = ((out["last_swing_high"] + prior_high) / 2).where(
        out["new_swing_high"] & ((out["last_swing_high"] - prior_high).abs() <= tolerance)
    ).ffill()
    out["equal_low_level"] = ((out["last_swing_low"] + prior_low) / 2).where(
        out["new_swing_low"] & ((out["last_swing_low"] - prior_low).abs() <= tolerance)
    ).ffill()
    return out.drop(columns=["session_id_v3"])


def swept_level_v3(row: pd.Series, direction: int) -> tuple[str, float, float, int] | None:
    atr = float(row["atr"])
    if not np.isfinite(atr) or atr <= 0:
        return None
    names = (
        ["last_swing_low", "equal_low_level", "opening_range_low", "prev_4h_low", "prev_session_low", "prev_day_low", "prev_week_low"]
        if direction > 0
        else ["last_swing_high", "equal_high_level", "opening_range_high", "prev_4h_high", "prev_session_high", "prev_day_high", "prev_week_high"]
    )
    hit: list[tuple[str, float, float]] = []
    for name in names:
        level = float(row.get(name, np.nan))
        if not np.isfinite(level):
            continue
        if direction > 0 and float(row["low"]) < level < float(row["close"]):
            hit.append((name, level, (level - float(row["low"])) / atr))
        if direction < 0 and float(row["high"]) > level > float(row["close"]):
            hit.append((name, level, (float(row["high"]) - level) / atr))
    if not hit:
        return None
    levels = np.array([item[1] for item in hit], dtype=float)
    tolerance = max(atr * 0.12, float(row["close"]) * 0.0003)
    confluence = max(int(np.sum(np.abs(levels - level) <= tolerance)) for level in levels)
    chosen = max(hit, key=lambda item: item[2])
    return chosen[0], chosen[1], chosen[2], confluence


def setup_grid_v3() -> list[Any]:
    return [
        v1.SetupConfig(tf, sweep, body, fvg, retrace, require_pd, require_overlap)
        for tf in (1, 3, 5, 15)
        for sweep in (0.00, 0.04, 0.10, 0.18)
        for body in (0.30, 0.50, 0.75, 1.05)
        for fvg in (0.00, 0.025, 0.07)
        for retrace in (0.50, 0.62, 0.705, 0.79)
        for require_pd in (False, True)
        for require_overlap in ((False, True) if fvg > 0 else (False,))
    ]


def account_grid_v3() -> list[Any]:
    return [
        v1.AccountConfig(risk, leverage)
        for risk in (0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.16, 0.20, 0.25, 0.30)
        for leverage in (3, 5, 10, 20, 30, 50, 75, 100)
    ]


def main_v3() -> int:
    args = v1.parse_args()
    if args.self_test:
        v1.self_test()
        tiny = pd.DataFrame({
            "start_time_ms": np.arange(120) * v1.MINUTE_MS + v1.utc_ms("2023-01-01"),
            "available_at_ms": np.arange(120) * v1.MINUTE_MS + v1.utc_ms("2023-01-01") + v1.MINUTE_MS,
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0, "turnover": 100.0,
        })
        enriched = enrich_v3(v1.resample(tiny, 3), 3, {}, tiny)
        assert {"prev_week_high", "prev_4h_high", "opening_range_high", "equal_high_level"}.issubset(enriched.columns)
        print("V3_SELF_TEST_PASS")
        return 0
    if args.data_root is None:
        raise SystemExit("--data-root is required")

    train_start = v1.utc_ms(args.train_start)
    train_end = v1.utc_ms(args.train_end_exclusive)
    eval_start = v1.utc_ms(args.evaluation_start)
    eval_end = v1.utc_ms(args.evaluation_end_exclusive)
    timeframes = (1, 3, 5, 15)
    minute_by_symbol: dict[str, pd.DataFrame] = {}
    setup_frames: dict[tuple[str, int], pd.DataFrame] = {}
    data_summary: dict[str, Any] = {}

    for symbol in args.symbols:
        bar_parts: list[pd.DataFrame] = []
        stream_parts: dict[str, list[pd.DataFrame]] = {name: [] for name in ("open_interest", "account_ratio", "funding", "mark", "index", "premium")}
        for segment in [*args.train_segments, *args.evaluation_segments]:
            bars, streams = v1.load_segment(args.data_root, segment, symbol)
            bar_parts.append(bars)
            for name, stream in streams.items():
                stream_parts[name].append(stream)
        minute = v1.concatenate(bar_parts, "start_time_ms")
        minute = minute[(minute["start_time_ms"] >= train_start) & (minute["start_time_ms"] < eval_end)].reset_index(drop=True)
        if minute.empty:
            raise v1.ResearchError(f"no data for {symbol}")
        streams = {name: v1.concatenate(parts, "available_at_ms") for name, parts in stream_parts.items()}
        minute_by_symbol[symbol] = minute
        data_summary[symbol] = {
            "rows_1m": len(minute),
            "first": v1.iso_ms(int(minute["start_time_ms"].iloc[0])),
            "last": v1.iso_ms(int(minute["start_time_ms"].iloc[-1])),
            "streams": {name: len(stream) for name, stream in streams.items()},
        }
        for tf in timeframes:
            setup_frames[(symbol, tf)] = enrich_v3(v1.resample(minute, tf), tf, streams, minute)

    for tf in timeframes:
        mapping = {symbol: setup_frames[(symbol, tf)] for symbol in args.symbols}
        v1.add_smt(mapping)
        for symbol, frame in mapping.items():
            setup_frames[(symbol, tf)] = frame

    v1.swept_level = swept_level_v3
    candidate_parts = [
        v1.raw_candidates(symbol, setup_frames[(symbol, tf)])
        for symbol in args.symbols
        for tf in timeframes
    ]
    candidate_parts = [part for part in candidate_parts if not part.empty]
    if not candidate_parts:
        raise v1.ResearchError("zero V3 SMC/ICT candidates")
    candidates = pd.concat(candidate_parts, ignore_index=True).sort_values("decision_time_ms", kind="stable").reset_index(drop=True)
    candidates = candidates[(candidates["decision_time_ms"] >= train_start) & (candidates["decision_time_ms"] < eval_end)].reset_index(drop=True)

    grids = setup_grid_v3()
    geometry_paths: dict[float, pd.DataFrame] = {}
    for retrace in sorted({config.retrace for config in grids}):
        geometry = v1.SetupConfig(1, 0, 0, 0, retrace, False, False)
        records = [
            v1.simulate(
                row,
                minute_by_symbol[row["symbol"]],
                setup_frames[(row["symbol"], int(row["timeframe_min"]))],
                geometry,
                eval_end,
            )
            for row in candidates.to_dict("records")
        ]
        geometry_paths[retrace] = pd.DataFrame(records)

    trials: dict[float, pd.DataFrame] = {}
    for retrace, paths in geometry_paths.items():
        trial = candidates.merge(paths, on=["candidate_id", "symbol", "direction", "decision_time_ms"], how="left")
        trial["label_end_time_ms"] = trial["exit_time_ms"].fillna(trial["order_end_time_ms"])
        trials[retrace] = trial

    cheap: list[dict[str, Any]] = []
    for config in grids:
        trial = trials[config.retrace]
        mask = v1.setup_mask(trial, config)
        resolved = mask & trial["filled"].fillna(False) & trial["resolved"].fillna(False) & (trial["label_end_time_ms"] < train_end) & trial["net_r"].notna()
        if int(resolved.sum()) < args.minimum_candidates:
            continue
        sample = trial.loc[resolved, ["decision_time_ms", "net_r"]]
        fourths = np.linspace(train_start, train_end, 5, dtype=np.int64)
        means = []
        positive_periods = 0
        for left, right in zip(fourths[:-1], fourths[1:]):
            segment = sample[(sample["decision_time_ms"] >= left) & (sample["decision_time_ms"] < right)]["net_r"]
            mean = float(segment.mean()) if len(segment) else -10.0
            means.append(mean)
            positive_periods += int(mean > 0)
        score = (
            0.42 * float(sample["net_r"].mean())
            + 0.28 * min(means)
            + 0.15 * float(sample["net_r"].median())
            + 0.08 * positive_periods
            + 0.02 * math.log1p(len(sample))
        )
        cheap.append({"config": asdict(config), "key": config.key, "score": score, "count": int(len(sample)), "quarter_means": means})
    if not cheap:
        raise v1.ResearchError("no V3 configuration survived chronological screening")
    cheap.sort(key=lambda item: item["score"], reverse=True)

    prediction_start = train_start + 120 * v1.DAY_MS
    ml_results: list[dict[str, Any]] = []
    for screen in cheap[:24]:
        config = v1.SetupConfig(**screen["config"])
        trial = trials[config.retrace].copy()
        eligible = v1.setup_mask(trial, config)
        for policy in ("monthly", "quarterly", "frozen"):
            scores = v1.prequential_scores(trial, eligible, prediction_start, train_end, policy)
            available = scores[eligible & (trial["decision_time_ms"] >= prediction_start) & (trial["decision_time_ms"] < train_end)].dropna()
            if len(available) < 30:
                continue
            thresholds = sorted({float(available.quantile(q)) for q in (0.20, 0.35, 0.50, 0.65, 0.78, 0.88, 0.94)})
            for threshold in thresholds:
                trial["ml_score"] = scores
                metrics = v1.account_sim(trial[eligible], minute_by_symbol, v1.AccountConfig(0.01, 10), prediction_start, train_end, threshold)
                if metrics["completed_trades"] < 15 or metrics["liquidation_events"]:
                    continue
                concentration = max(0.0, float(metrics["top_5_pnl_share"] or 0.0) - 0.70)
                objective = metrics["geometric_daily_growth"] * 10_000 + metrics["max_drawdown"] * 0.30 + 0.03 * math.log1p(metrics["completed_trades"]) - 0.20 * concentration
                ml_results.append({"config": asdict(config), "key": config.key, "policy": policy, "threshold": threshold, "objective": objective, "metrics": v1.compact(metrics), "screen": screen})
    if not ml_results:
        raise v1.ResearchError("no V3 decision-ready pre-2024 ML configuration")
    ml_results.sort(key=lambda item: item["objective"], reverse=True)
    selected = ml_results[0]
    config = v1.SetupConfig(**selected["config"])
    trial = trials[config.retrace].copy()
    eligible = v1.setup_mask(trial, config)
    trial["ml_score"] = v1.prequential_scores(trial, eligible, prediction_start, eval_end, selected["policy"])

    pre = trial[eligible & (trial["decision_time_ms"] < train_end)]
    risk_results: list[dict[str, Any]] = []
    for account in account_grid_v3():
        metrics = v1.account_sim(pre, minute_by_symbol, account, prediction_start, train_end, float(selected["threshold"]))
        if metrics["completed_trades"] < 15 or metrics["liquidation_events"] or metrics["final_nav"] <= 0:
            continue
        concentration = max(0.0, float(metrics["top_5_pnl_share"] or 0.0) - 0.75)
        objective = metrics["geometric_daily_growth"] * 10_000 + metrics["max_drawdown"] * 0.25 - 0.20 * concentration
        risk_results.append({"config": asdict(account), "key": account.key, "objective": objective, "metrics": v1.compact(metrics)})
    if not risk_results:
        raise v1.ResearchError("V3 alpha failed account sizing/liquidation checks")
    risk_results.sort(key=lambda item: item["objective"], reverse=True)
    account = v1.AccountConfig(**risk_results[0]["config"])
    pre_metrics = v1.account_sim(pre, minute_by_symbol, account, prediction_start, train_end, float(selected["threshold"]))
    evaluation = trial[eligible & (trial["decision_time_ms"] >= eval_start) & (trial["decision_time_ms"] < eval_end)]
    h1_metrics = v1.account_sim(evaluation, minute_by_symbol, account, eval_start, eval_end, float(selected["threshold"]))
    decision = "ADVANCE_FULL_CAUSAL_EVALUATION" if h1_metrics["geometric_daily_growth"] > 0 and h1_metrics["completed_trades"] >= 40 and not h1_metrics["liquidation_events"] else "REVISE_CORE_SYSTEMIZATION"
    summary = {
        "schema_version": 3,
        "system_id": "SYS-SWIPALNAM-LIQUIDITY-DELIVERY-ML-V3",
        "decision": decision,
        "target_hit_2024h1": bool(h1_metrics["geometric_daily_growth"] >= 0.01),
        "fixed_latency_ms": v1.LATENCY_MS,
        "timeframes_min": list(timeframes),
        "liquidity_references": ["confirmed swing", "confirmed equal highs/lows", "opening range", "previous 4h", "previous session", "previous day", "previous week"],
        "data": data_summary,
        "periods": {"train_start": args.train_start, "train_end_exclusive": args.train_end_exclusive, "evaluation_start": args.evaluation_start, "evaluation_end_exclusive": args.evaluation_end_exclusive},
        "candidate_count": len(candidates),
        "configuration_count": len(grids),
        "configuration_screen_survivors": len(cheap),
        "selected_structural_configuration": asdict(config),
        "selected_structural_key": config.key,
        "selected_retraining_policy": selected["policy"],
        "selected_ml_score_threshold": selected["threshold"],
        "selected_account_configuration": asdict(account),
        "selected_account_key": account.key,
        "pre2024_metrics": v1.compact(pre_metrics),
        "provisional_2024h1_metrics": v1.compact(h1_metrics),
        "top_structural_screens": cheap[:30],
        "top_ml_alternatives": ml_results[:20],
        "top_account_alternatives": risk_results[:20],
        "causality_notes": [
            "all pivots/equal-high-low levels require right-side confirmation",
            "higher-timeframe and derivative state is backward as-of joined by availability time",
            "orders activate after fixed 500 ms",
            "touch confirmation fills only at the next full minute open",
            "resting orders cancel only on structural/session liquidity-map refresh",
            "positions have no elapsed-time forced exit",
            "same-minute ambiguity is stop-first",
            "labels train only after outcome resolution",
            "one global pending/position slot",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    v1.write_json(args.output / "RUN_SUMMARY.json", summary)
    pd.DataFrame(pre_metrics["trades"]).to_csv(args.output / "PRE2024_TRADES.csv", index=False)
    pd.DataFrame(h1_metrics["trades"]).to_csv(args.output / "2024H1_TRADES.csv", index=False)
    pd.DataFrame(pre_metrics["daily_nav"]).to_csv(args.output / "PRE2024_DAILY_NAV.csv", index=False)
    pd.DataFrame(h1_metrics["daily_nav"]).to_csv(args.output / "2024H1_DAILY_NAV.csv", index=False)
    print(json.dumps({
        "decision": decision,
        "target_hit_2024h1": summary["target_hit_2024h1"],
        "candidate_count": len(candidates),
        "pre2024": v1.compact(pre_metrics),
        "provisional_2024h1": v1.compact(h1_metrics),
        "structural_key": config.key,
        "account_key": account.key,
    }, ensure_ascii=False, indent=2, default=v1.json_default))
    return 0


v1.enrich = enrich_v3
v1.swept_level = swept_level_v3
v1.setup_grid = setup_grid_v3
v1.account_grid = account_grid_v3

if __name__ == "__main__":
    raise SystemExit(main_v3())
