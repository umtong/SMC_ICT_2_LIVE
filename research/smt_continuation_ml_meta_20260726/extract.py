from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

import acceptance_engine as acc
import base_probe as base

CLAIM_ID = "CLM-20260726-1906-SMT-CONTINUATION-ML-001"
FOLLOWERS = ("SOLUSDT", "XRPUSDT")
SYMBOLS = ("BTCUSDT",) + FOLLOWERS
HORIZONS = (1, 2, 5)
LATENCIES = (100, 300)
MINIMUM_GAP = 0.0012
BINS_PER_SECOND = 10
PROHIBITED_YEARS = {2024, 2025, 2026}


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stage_for_date(date: str) -> str:
    ts = pd.Timestamp(date)
    if ts.year in PROHIBITED_YEARS:
        raise ValueError(f"sealed year requested: {ts.year}")
    if ts.weekday() != 6:
        raise ValueError(f"date is not Sunday: {date}")
    if pd.Timestamp("2022-01-02") <= ts <= pd.Timestamp("2022-06-26"):
        return "FIT"
    if pd.Timestamp("2022-07-03") <= ts <= pd.Timestamp("2022-09-25"):
        return "SCORE_CALIBRATION"
    if pd.Timestamp("2022-10-02") <= ts <= pd.Timestamp("2022-12-25"):
        return "FIT_CONFIRMATION"
    if pd.Timestamp("2023-01-01") <= ts <= pd.Timestamp("2023-08-27"):
        return "DEVELOPMENT"
    raise ValueError(f"date outside frozen chronology: {date}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with __import__("gzip").open(path, "wt", encoding="utf-8") as handle:
            handle.write("")
        return
    fields = sorted({key for row in rows for key in row})
    with __import__("gzip").open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def rolling_realized_volatility(mark: np.ndarray, window: int = 100) -> np.ndarray:
    price = np.asarray(mark, dtype=np.float64)
    returns = np.full(len(price), np.nan, dtype=np.float64)
    valid = (
        np.isfinite(price[1:]) & np.isfinite(price[:-1])
        & (price[1:] > 0) & (price[:-1] > 0)
    )
    returns[1:][valid] = np.log(price[1:][valid] / price[:-1][valid])
    square = np.nan_to_num(returns * returns, nan=0.0)
    cumulative = np.concatenate(([0.0], np.cumsum(square, dtype=np.float64)))
    end = np.arange(1, len(square) + 1)
    start = np.maximum(0, end - window)
    return np.sqrt(np.maximum(0.0, cumulative[end] - cumulative[start]))


def other_follower_residual_bps(
    day_data: dict[str, dict[str, Any]],
    event: dict[str, Any],
    signal_bin: int,
) -> float:
    other = "XRPUSDT" if event["symbol"] == "SOLUSDT" else "SOLUSDT"
    leader = day_data["BTCUSDT"]["arrays"]
    follower = day_data[other]["arrays"]
    features = base.continuous_features(leader, follower, int(event["horizon"]))
    beta = float(features["beta"][int(event["decision_bin"])])
    start = int(event["start_idx"])
    values = (leader.mark[start], leader.mark[signal_bin], follower.mark[start], follower.mark[signal_bin])
    if not np.isfinite(beta) or not all(np.isfinite(value) and value > 0 for value in values):
        return math.nan
    leader_move = math.log(float(leader.mark[signal_bin]) / float(leader.mark[start]))
    follower_move = math.log(float(follower.mark[signal_bin]) / float(follower.mark[start]))
    return int(event["impulse_direction"]) * (follower_move - beta * leader_move) * 10_000.0


def load_date(date: str, cache: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    stage_for_date(date)
    payload: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-smt-continuation-ml/1.0"
        for symbol in SYMBOLS:
            url = base.URL_TEMPLATE.format(symbol=symbol, date=date)
            path = cache / symbol / f"{symbol}{date}.csv.gz"
            raw_payload = base._download(session, url, path)
            arrays, record = base.aggregate(path, symbol, date)
            if not record.timestamp_monotonic:
                raise RuntimeError(f"nonmonotonic source: {url}")
            payload[symbol] = {
                "arrays": arrays,
                "raw": acc.load_raw_trades(path) if symbol in FOLLOWERS else None,
                "signed_1s": acc.rolling_sum(arrays.signed_notional, 10) if symbol in FOLLOWERS else None,
                "total_1s": acc.rolling_sum(arrays.total_notional, 10) if symbol in FOLLOWERS else None,
                "total_3s": acc.rolling_sum(arrays.total_notional, 30) if symbol in FOLLOWERS else None,
                "count_1s": acc.rolling_sum(arrays.trade_count.astype(float), 10) if symbol in FOLLOWERS else None,
                "volatility_10s": rolling_realized_volatility(arrays.mark, 100) if symbol in FOLLOWERS else None,
            }
            item = asdict(record)
            item["download_bytes"] = len(raw_payload)
            records.append(item)
            print(stable_json(item), flush=True)
    return payload, records


def extract(date: str, cache: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    stage = stage_for_date(date)
    payload, records = load_date(date, cache)
    wrapped = {date: payload}
    leader = payload["BTCUSDT"]["arrays"]
    raw_events: list[dict[str, Any]] = []
    for symbol in FOLLOWERS:
        follower = payload[symbol]["arrays"]
        for horizon in HORIZONS:
            raw_events.extend(acc.overreaction_events(date, symbol, leader, follower, horizon, MINIMUM_GAP))
        gc.collect()

    strongest: dict[tuple[str, str, int], dict[str, Any]] = {}
    for event in raw_events:
        key = (date, str(event["symbol"]), int(event["decision_bin"]))
        if key not in strongest or acc.event_priority(event) < acc.event_priority(strongest[key]):
            strongest[key] = event
    events = sorted(strongest.values(), key=lambda item: (item["decision_bin"], acc.event_priority(item)))
    acc.prepare_events(wrapped, events)

    rows: list[dict[str, Any]] = []
    diagnostics = {
        "raw_event_rows": len(raw_events),
        "deduplicated_events": len(events),
        "pullback_events": 0,
        "both_latency_executable": 0,
        "both_latency_target_first": 0,
    }
    for event in events:
        signal_bin = event.get("pullback_signal_bin")
        if signal_bin is None:
            continue
        signal_bin = int(signal_bin)
        diagnostics["pullback_events"] += 1
        symbol = str(event["symbol"])
        follower = payload[symbol]["arrays"]
        state = acc.residual_overextension(leader, follower, event, signal_bin)
        if state is None:
            continue
        residual, leader_move, _ = state
        gap = float(event["gap"])
        direction = int(event["impulse_direction"])
        signed = float(payload[symbol]["signed_1s"][signal_bin])
        total = float(payload[symbol]["total_1s"][signal_bin])
        flow = direction * signed / total if np.isfinite(total) and total > 0 else math.nan
        event_id = hashlib.sha256(
            stable_json([date, symbol, int(event["horizon"]), int(event["decision_bin"])]).encode()
        ).hexdigest()[:24]
        row: dict[str, Any] = {
            "claim_id": CLAIM_ID,
            "stage": stage,
            "date": date,
            "event_id": event_id,
            "event_key": event["event_key"],
            "symbol": symbol,
            "symbol_is_xrp": float(symbol == "XRPUSDT"),
            "horizon_seconds": int(event["horizon"]),
            "decision_bin": int(event["decision_bin"]),
            "signal_bin": signal_bin,
            "signal_time": pd.Timestamp(date, tz="UTC").timestamp() + (signal_bin + 1) / BINS_PER_SECOND,
            "btc_displacement_z": float(event["z"]),
            "btc_activity_ratio": float(event["activity"]),
            "btc_aggressor_alignment": float(event["leader_align"]),
            "follower_aggressor_alignment_at_event": float(event["follower_align"]),
            "frozen_beta": float(event["beta"]),
            "initial_residual_gap_bps": gap * 10_000.0,
            "overreaction_ratio": float(event["overreaction_ratio"]),
            "target_to_btc_trade_count_ratio_30m": float(event["trade_ratio"]),
            "target_to_btc_realized_volatility_ratio_15m": float(event["volatility_ratio"]),
            "pullback_depth_ratio": float(residual / gap),
            "milliseconds_event_to_pullback": float((signal_bin - int(event["decision_bin"])) * 100),
            "reacceleration_flow_strength_1s": flow,
            "reacceleration_trade_count_1s": float(payload[symbol]["count_1s"][signal_bin]),
            "target_realized_volatility_10s": float(payload[symbol]["volatility_10s"][signal_bin]),
            "other_follower_residual_bps": other_follower_residual_bps(payload, event, signal_bin),
            "leader_move_at_entry_bps": float(leader_move * 10_000.0),
            "prior_quote_notional_3s": float(payload[symbol]["total_3s"][signal_bin]),
        }
        executable_both = True
        target_both = True
        for latency in LATENCIES:
            trade, missing = acc.evaluate_event(wrapped, event, "FVG_PULLBACK_CONTINUATION", latency)
            prefix = f"l{latency}"
            if missing is not None or trade is None:
                row[f"{prefix}_trade"] = False
                row[f"{prefix}_unavailable"] = missing is not None
                row[f"{prefix}_target_first"] = False
                row[f"{prefix}_entry_time"] = math.nan
                row[f"{prefix}_exit_time"] = math.nan
                row[f"{prefix}_gross_bps"] = math.nan
                row[f"{prefix}_net24_bps"] = math.nan
                row[f"{prefix}_exit_reason"] = missing["reason"] if missing else "NO_TRADE"
                executable_both = False
                target_both = False
            else:
                target_first = str(trade["exit_reason"]) == "NEXT_LIQUIDITY_EXPANSION"
                row[f"{prefix}_trade"] = True
                row[f"{prefix}_unavailable"] = bool(trade.get("unvalued", False))
                row[f"{prefix}_target_first"] = target_first
                row[f"{prefix}_entry_time"] = float(trade["entry_time"])
                row[f"{prefix}_exit_time"] = float(trade["exit_time"])
                row[f"{prefix}_gross_bps"] = float(trade["gross_bps"])
                row[f"{prefix}_net24_bps"] = float(trade["gross_bps"]) - 24.0
                row[f"{prefix}_exit_reason"] = str(trade["exit_reason"])
                executable_both &= not bool(trade.get("unvalued", False))
                target_both &= target_first and not bool(trade.get("unvalued", False))
        row["label_available"] = executable_both
        row["continuation_label"] = int(target_both) if executable_both else math.nan
        diagnostics["both_latency_executable"] += int(executable_both)
        diagnostics["both_latency_target_first"] += int(target_both)
        rows.append(row)

    summary = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "date": date,
        "stage": stage,
        "row_count": len(rows),
        "diagnostics": diagnostics,
        "source_count": len(records),
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    return rows, records, summary


def self_test() -> None:
    assert stage_for_date("2022-01-02") == "FIT"
    assert stage_for_date("2022-07-03") == "SCORE_CALIBRATION"
    assert stage_for_date("2022-10-02") == "FIT_CONFIRMATION"
    assert stage_for_date("2023-08-27") == "DEVELOPMENT"
    for bad in ("2022-01-03", "2024-01-07"):
        try:
            stage_for_date(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsealed invalid date {bad}")
    mark = np.asarray([100.0, 100.1, 99.9, 100.2], dtype=float)
    assert np.isfinite(rolling_realized_volatility(mark, 2)[-1])
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
    if not args.date or args.cache is None or args.output is None:
        parser.error("--date, --cache and --output are required")
    rows, sources, summary = extract(args.date, args.cache)
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv_gz(args.output / f"matrix_{args.date}.csv.gz", rows)
    (args.output / f"sources_{args.date}.json").write_text(
        json.dumps(sources, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output / f"summary_{args.date}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksums = []
    for path in sorted(args.output.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            checksums.append(f"{sha256_file(path)}  {path.name}")
    (args.output / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(stable_json(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
