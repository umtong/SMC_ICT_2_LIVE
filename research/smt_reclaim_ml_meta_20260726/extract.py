from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

import base_probe as base
import rule_engine as rule

FIT_DATES = {
    "2022-01-09", "2022-03-13", "2022-05-08", "2022-07-10", "2022-09-11", "2022-11-13"
}
CALIBRATION_DATES = {
    "2022-02-13", "2022-04-10", "2022-06-12", "2022-08-14", "2022-10-09", "2022-12-11"
}
DEVELOPMENT_DATES = {
    "2023-01-08", "2023-02-12", "2023-03-12", "2023-04-09",
    "2023-05-14", "2023-06-11", "2023-07-09", "2023-08-13"
}
SELECTION_DATES = {"2023-09-24", "2023-10-22", "2023-11-26", "2023-12-31"}
ALL_DATES = FIT_DATES | CALIBRATION_DATES | DEVELOPMENT_DATES | SELECTION_DATES
SYMBOLS = ("BTCUSDT", "SOLUSDT", "XRPUSDT")
FOLLOWERS = ("SOLUSDT", "XRPUSDT")
HORIZONS = (1, 2, 5)
MINIMUM_GAP = 0.0012
LATENCIES = (100, 300)
BINS_PER_SECOND = 10
BINS_PER_DAY = 24 * 60 * 60 * BINS_PER_SECOND
CLAIM_ID = "CLM-20260726-SMT-RECLAIM-ML-001"


def stage_for_date(date: str) -> str:
    if date in FIT_DATES:
        return "FIT"
    if date in CALIBRATION_DATES:
        return "CALIBRATION"
    if date in DEVELOPMENT_DATES:
        return "DEVELOPMENT"
    if date in SELECTION_DATES:
        return "SELECTION_EVIDENCE"
    raise ValueError(f"date outside frozen contract: {date}")


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        if not rows:
            stream.write("")
            return
        fields = sorted({key for row in rows for key in row})
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def rolling_realized_volatility(mark: np.ndarray, window: int = 100) -> np.ndarray:
    price = np.asarray(mark, dtype=np.float64)
    returns = np.full(len(price), np.nan, dtype=np.float64)
    valid = (
        np.isfinite(price[1:])
        & np.isfinite(price[:-1])
        & (price[1:] > 0)
        & (price[:-1] > 0)
    )
    returns[1:][valid] = np.log(price[1:][valid] / price[:-1][valid])
    squared = np.nan_to_num(returns * returns, nan=0.0)
    cumulative = np.concatenate(([0.0], np.cumsum(squared, dtype=np.float64)))
    end = np.arange(1, len(squared) + 1)
    start = np.maximum(0, end - window)
    return np.sqrt(np.maximum(0.0, cumulative[end] - cumulative[start]))


def find_mss_confirmation(
    leader: dict[str, np.ndarray],
    follower: dict[str, np.ndarray],
    leader_age: np.ndarray,
    tape: rule.RawTape,
    event: dict[str, Any],
) -> tuple[int | None, str, np.ndarray, np.ndarray, np.ndarray]:
    residual, leader_move, fresh = rule.event_state(
        leader, follower, leader_age, tape.age_bins, event
    )
    decision = int(event["decision_bin"])
    gap = float(event["gap"])
    direction = int(event["direction"])
    opposite_flow = (
        np.isfinite(tape.flow_imbalance_1s)
        & (direction * tape.flow_imbalance_1s < 0)
        & (tape.trade_count_1s >= 3)
    )
    confirmation_mask = (
        fresh
        & (residual <= 0.8 * gap)
        & (residual > 0.25 * gap)
        & opposite_flow
    )
    confirmation = rule.first_true(confirmation_mask, decision + 1)
    invalidation = rule.first_true(
        fresh & ((residual >= 1.5 * gap) | (leader_move <= 0)),
        decision + 1,
    )
    stale = rule.first_run(~fresh, decision + 1, 10)
    earliest_failure = min(
        [value for value in (invalidation, stale) if value is not None],
        default=None,
    )
    if confirmation is None:
        return None, "NO_MSS_CONFIRMATION", residual, leader_move, fresh
    if earliest_failure is not None and earliest_failure <= confirmation:
        return None, "INVALID_BEFORE_MSS", residual, leader_move, fresh
    return confirmation, "MSS_CONFIRMED", residual, leader_move, fresh


def other_follower_residual_bps(
    arrays: dict[str, dict[str, np.ndarray]],
    features_by_symbol_horizon: dict[tuple[str, int], dict[str, np.ndarray]],
    event_symbol: str,
    horizon: int,
    event: dict[str, Any],
    confirmation: int,
) -> float:
    other = "XRPUSDT" if event_symbol == "SOLUSDT" else "SOLUSDT"
    other_features = features_by_symbol_horizon[(other, horizon)]
    decision = int(event["decision_bin"])
    start = int(event["start_idx"])
    direction = int(event["direction"])
    beta = float(other_features["beta"][decision])
    leader_mark = arrays["BTCUSDT"]["mark"]
    other_mark = arrays[other]["mark"]
    values = (leader_mark[start], leader_mark[confirmation], other_mark[start], other_mark[confirmation], beta)
    if not all(np.isfinite(value) and value > 0 for value in values[:4]) or not np.isfinite(beta):
        return math.nan
    btc_move = math.log(float(leader_mark[confirmation]) / float(leader_mark[start]))
    other_move = math.log(float(other_mark[confirmation]) / float(other_mark[start]))
    return direction * (other_move - beta * btc_move) * 10_000.0


def load_date(date: str, cache: Path) -> tuple[
    dict[str, dict[str, np.ndarray]], dict[str, rule.RawTape], list[dict[str, Any]]
]:
    arrays: dict[str, dict[str, np.ndarray]] = {}
    tapes: dict[str, rule.RawTape] = {}
    sources: list[dict[str, Any]] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-smt-reclaim-ml-extract/1.0"
        for symbol in SYMBOLS:
            url = f"https://public.bybit.com/trading/{symbol}/{symbol}{date}.csv.gz"
            target = cache / symbol / f"{symbol}{date}.csv.gz"
            payload = base._download(session, url, target)
            record = base.inspect_source(target, symbol, date, url, payload)
            if not record.timestamp_monotonic:
                raise RuntimeError(f"nonmonotonic source: {url}")
            arrays[symbol] = base.aggregate(target, date)
            sources.append(asdict(record))
            if symbol in FOLLOWERS:
                tapes[symbol] = rule.load_raw_tape(target, date)
            print(stable_json(asdict(record)), flush=True)
    return arrays, tapes, sources


def extract(date: str, cache: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    arrays, tapes, sources = load_date(date, cache)
    leader = arrays["BTCUSDT"]
    leader_age = rule.age_from_count(leader["trade_count"])
    features_by_symbol_horizon: dict[tuple[str, int], dict[str, np.ndarray]] = {}
    attention_by_symbol_horizon: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}
    target_volatility: dict[str, np.ndarray] = {}
    for symbol in FOLLOWERS:
        target_volatility[symbol] = rolling_realized_volatility(arrays[symbol]["mark"], 100)
        for horizon in HORIZONS:
            features_by_symbol_horizon[(symbol, horizon)] = base.continuous_features(
                leader, arrays[symbol], horizon
            )
            attention_by_symbol_horizon[(symbol, horizon)] = rule.attention(
                leader, arrays[symbol], horizon
            )

    rows: list[dict[str, Any]] = []
    diagnostics = {
        "raw_overreaction_events": 0,
        "mss_confirmed_events": 0,
        "no_mss_confirmation": 0,
        "invalid_before_mss": 0,
    }
    day_start = float(base.utc_start(date))
    for symbol in FOLLOWERS:
        follower = arrays[symbol]
        tape = tapes[symbol]
        for horizon in HORIZONS:
            features = features_by_symbol_horizon[(symbol, horizon)]
            trade_ratio, volatility_ratio = attention_by_symbol_horizon[(symbol, horizon)]
            events = rule.select_overreaction_events(
                features, trade_ratio, volatility_ratio, MINIMUM_GAP
            )
            diagnostics["raw_overreaction_events"] += len(events)
            for event in events:
                event.update(
                    {
                        "date": date,
                        "symbol": symbol,
                        "horizon": horizon,
                        "gap_floor_bps": 12,
                    }
                )
                event["event_id"] = hashlib.sha256(
                    stable_json([date, symbol, horizon, event["decision_bin"]]).encode()
                ).hexdigest()[:24]
                confirmation, status, residual, leader_move, fresh = find_mss_confirmation(
                    leader, follower, leader_age, tape, event
                )
                if confirmation is None:
                    if status == "NO_MSS_CONFIRMATION":
                        diagnostics["no_mss_confirmation"] += 1
                    else:
                        diagnostics["invalid_before_mss"] += 1
                    continue
                diagnostics["mss_confirmed_events"] += 1
                decision = int(event["decision_bin"])
                gap = float(event["gap"])
                direction = int(event["direction"])
                confirmation_time = day_start + (confirmation + 1) / BINS_PER_SECOND
                seconds = confirmation_time % (24 * 60 * 60)
                angle = 2 * math.pi * seconds / (24 * 60 * 60)
                row: dict[str, Any] = {
                    "claim_id": CLAIM_ID,
                    "stage": stage_for_date(date),
                    "date": date,
                    "event_id": event["event_id"],
                    "symbol": symbol,
                    "horizon_seconds": horizon,
                    "decision_bin": decision,
                    "confirmation_bin": confirmation,
                    "confirmation_time": confirmation_time,
                    "btc_displacement_z": float(event["z"]),
                    "btc_activity_ratio": float(event["activity"]),
                    "btc_aggressor_alignment": float(event["leader_align"]),
                    "follower_aggressor_alignment_at_event": float(event["follower_align"]),
                    "frozen_beta": float(event["beta"]),
                    "initial_residual_gap_bps": gap * 10_000.0,
                    "overreaction_ratio": float(event["under"]),
                    "target_to_btc_trade_count_ratio_30m": float(event["trade_ratio"]),
                    "target_to_btc_realized_volatility_ratio_15m": float(event["volatility_ratio"]),
                    "mss_residual_contraction_ratio": float(residual[confirmation] / gap),
                    "milliseconds_event_to_mss": float((confirmation - decision) * 100),
                    "opposite_flow_strength_1s": float(-direction * tape.flow_imbalance_1s[confirmation]),
                    "opposite_flow_trade_count_1s": float(tape.trade_count_1s[confirmation]),
                    "target_realized_volatility_10s": float(target_volatility[symbol][confirmation]),
                    "target_trade_count_1s": float(tape.trade_count_1s[confirmation]),
                    "other_follower_residual_bps": other_follower_residual_bps(
                        arrays,
                        features_by_symbol_horizon,
                        symbol,
                        horizon,
                        event,
                        confirmation,
                    ),
                    "utc_time_sine": math.sin(angle),
                    "utc_time_cosine": math.cos(angle),
                    "leader_move_at_mss_bps": float(leader_move[confirmation] * 10_000.0),
                    "fresh_state_at_mss": bool(fresh[confirmation]),
                }
                for latency in LATENCIES:
                    trade, outcome_status = rule.simulate_event(
                        leader,
                        follower,
                        leader_age,
                        tape,
                        event,
                        "mss",
                        latency,
                    )
                    prefix = f"l{latency}"
                    row[f"{prefix}_status"] = outcome_status
                    if trade is None:
                        row[f"{prefix}_trade"] = False
                        row[f"{prefix}_entry_time"] = math.nan
                        row[f"{prefix}_exit_time"] = math.nan
                        row[f"{prefix}_gross_bps"] = math.nan
                        row[f"{prefix}_net24_bps"] = math.nan
                        row[f"{prefix}_unavailable"] = outcome_status.startswith("UNAVAILABLE")
                        row[f"{prefix}_boundary_loss"] = False
                        row[f"{prefix}_exit_reason"] = outcome_status
                    else:
                        row[f"{prefix}_trade"] = True
                        row[f"{prefix}_entry_time"] = float(trade["entry_time"])
                        row[f"{prefix}_exit_time"] = float(trade["exit_time"])
                        row[f"{prefix}_gross_bps"] = float(trade["gross_bps"])
                        row[f"{prefix}_net24_bps"] = float(trade["gross_bps"]) - 24.0
                        row[f"{prefix}_unavailable"] = bool(trade["unavailable"])
                        row[f"{prefix}_boundary_loss"] = bool(trade["boundary_loss"])
                        row[f"{prefix}_exit_reason"] = str(trade["exit_reason"])
                rows.append(row)
    summary = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "date": date,
        "stage": stage_for_date(date),
        "row_count": len(rows),
        "source_count": len(sources),
        "diagnostics": diagnostics,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    return rows, sources, summary


def self_test() -> None:
    assert len(ALL_DATES) == 24
    assert stage_for_date("2022-01-09") == "FIT"
    assert stage_for_date("2023-12-31") == "SELECTION_EVIDENCE"
    mark = np.array([100.0, 101.0, 100.5, 102.0])
    volatility = rolling_realized_volatility(mark, 2)
    assert len(volatility) == len(mark)
    assert np.isfinite(volatility[-1])
    print("SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.date not in ALL_DATES:
        parser.error("--date must be one of the 24 frozen dates")
    if args.cache is None or args.output is None:
        parser.error("--cache and --output are required")
    started = time.time()
    rows, sources, summary = extract(args.date, args.cache)
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv_gz(args.output / f"matrix_{args.date}.csv.gz", rows)
    (args.output / f"sources_{args.date}.json").write_text(
        json.dumps(sources, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary["elapsed_seconds"] = time.time() - started
    (args.output / f"summary_{args.date}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    hashes = []
    for path in sorted(args.output.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            hashes.append(f"{sha256_file(path)}  {path.name}")
    (args.output / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")
    print(stable_json(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
