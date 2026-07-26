from __future__ import annotations

import argparse
import gzip
import hashlib
import itertools
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests

BINS_PER_DAY = 864_000
DEFAULT_DATES = ("2023-01-15", "2023-03-19", "2023-05-21", "2023-07-16")
FIT_DATES = ("2023-01-15", "2023-03-19")
DEV_DATES = ("2023-05-21", "2023-07-16")
DEFAULT_SYMBOLS = ("BTCUSDT", "SOLUSDT", "XRPUSDT")
HORIZONS = (1, 2, 5)
Z_GRID = (3.0, 4.0, 5.0)
BTC_FLOW_GRID = (0.5, 0.7)
ACTIVITY_GRID = (2.0, 4.0)
UNDER_GRID = (0.25, 0.5, 0.75)
FOLLOWER_FLOW_GRID = (0.25, 0.5)
GAP_GRID = (0.0012, 0.0018, 0.0024)
BASE_URL = "https://public.bybit.com/trading/{symbol}/{symbol}{date}.csv.gz"


@dataclass(frozen=True)
class SourceRecord:
    symbol: str
    date: str
    url: str
    http_status: int
    bytes: int
    sha256: str | None
    gzip_valid: bool
    columns: list[str]
    rows: int
    first_timestamp: float | None
    last_timestamp: float | None
    timestamp_monotonic: bool
    day_coverage_valid: bool
    error: str | None


def utc_day_start(date: str) -> float:
    return datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_one(session: requests.Session, cache: Path, symbol: str, date: str) -> tuple[Path, int, str | None]:
    target = cache / symbol / f"{symbol}{date}.csv.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        return target, 200, None
    url = BASE_URL.format(symbol=symbol, date=date)
    errors: list[str] = []
    for attempt in range(4):
        try:
            with session.get(url, stream=True, timeout=(30, 600)) as response:
                status = int(response.status_code)
                if status != 200:
                    errors.append(f"HTTP {status}")
                    if status in (400, 401, 403, 404):
                        return target, status, errors[-1]
                else:
                    tmp = target.with_suffix(target.suffix + ".part")
                    with tmp.open("wb") as out:
                        for chunk in response.iter_content(1 << 20):
                            if chunk:
                                out.write(chunk)
                    tmp.replace(target)
                    return target, status, None
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(2 ** attempt, 8))
    return target, 0, "; ".join(errors[-4:]) or "download failed"


def aggregate(path: Path, out: Path, symbol: str, date: str, http_status: int, download_error: str | None) -> SourceRecord:
    url = BASE_URL.format(symbol=symbol, date=date)
    if http_status != 200 or not path.exists():
        return SourceRecord(symbol, date, url, http_status, 0, None, False, [], 0, None, None, False, False, download_error or "source unavailable")

    first_price = np.full(BINS_PER_DAY, np.nan, dtype=np.float64)
    last_price = np.full(BINS_PER_DAY, np.nan, dtype=np.float64)
    total_notional = np.zeros(BINS_PER_DAY, dtype=np.float64)
    signed_notional = np.zeros(BINS_PER_DAY, dtype=np.float64)
    trade_count = np.zeros(BINS_PER_DAY, dtype=np.int32)
    start = utc_day_start(date)
    end = start + 86400.0
    previous = -math.inf
    rows = 0
    first_ts: float | None = None
    last_ts: float | None = None
    monotonic = True
    columns: list[str] = []
    try:
        with gzip.open(path, "rt", newline="") as handle:
            reader = pd.read_csv(
                handle,
                usecols=["timestamp", "side", "size", "price"],
                dtype={"timestamp": "float64", "side": "string", "size": "float64", "price": "float64"},
                chunksize=500_000,
            )
            columns = ["timestamp", "side", "size", "price"]
            for chunk in reader:
                ts = chunk["timestamp"].to_numpy(np.float64, copy=False)
                if len(ts) == 0:
                    continue
                if ts[0] < previous or np.any(ts[1:] < ts[:-1]):
                    monotonic = False
                    raise ValueError("nonmonotonic timestamps")
                previous = float(ts[-1])
                first_ts = float(ts[0]) if first_ts is None else first_ts
                last_ts = float(ts[-1])
                idx = np.floor((ts - start) * 10.0 + 1e-7).astype(np.int64)
                price = chunk["price"].to_numpy(np.float64, copy=False)
                size = chunk["size"].to_numpy(np.float64, copy=False)
                side = chunk["side"].to_numpy(dtype=str)
                valid = (
                    (idx >= 0) & (idx < BINS_PER_DAY) & np.isfinite(price) & np.isfinite(size) & (price > 0) & (size > 0)
                )
                idx = idx[valid]
                price = price[valid]
                size = size[valid]
                side = side[valid]
                if len(idx) == 0:
                    continue
                notion = price * size
                sign = np.where(side == "Buy", 1.0, -1.0)
                total_notional += np.bincount(idx, weights=notion, minlength=BINS_PER_DAY)
                signed_notional += np.bincount(idx, weights=notion * sign, minlength=BINS_PER_DAY)
                trade_count += np.bincount(idx, minlength=BINS_PER_DAY).astype(np.int32)
                unique, first_pos = np.unique(idx, return_index=True)
                missing = np.isnan(first_price[unique])
                if missing.any():
                    first_price[unique[missing]] = price[first_pos[missing]]
                rev_unique, rev_pos = np.unique(idx[::-1], return_index=True)
                last_pos = len(idx) - 1 - rev_pos
                last_price[rev_unique] = price[last_pos]
                rows += len(idx)
        digest = sha256_file(path)
        occupied = trade_count > 0
        last_idx = np.maximum.accumulate(np.where(occupied, np.arange(BINS_PER_DAY, dtype=np.int32), -1))
        age = np.arange(BINS_PER_DAY, dtype=np.int32) - last_idx
        mark = np.full(BINS_PER_DAY, np.nan, dtype=np.float64)
        valid_mark = (last_idx >= 0) & (age <= 20)
        mark[valid_mark] = last_price[last_idx[valid_mark]]
        out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            out,
            symbol=np.array(symbol),
            date=np.array(date),
            source_name=np.array(path.name),
            source_sha256=np.array(digest),
            first_price=first_price,
            last_price=last_price,
            total_notional=total_notional,
            signed_notional=signed_notional,
            trade_count=trade_count,
            mark=mark,
        )
        coverage = bool(first_ts is not None and last_ts is not None and start <= first_ts < start + 60 and end - 60 < last_ts < end)
        return SourceRecord(symbol, date, url, http_status, path.stat().st_size, digest, True, columns, rows, first_ts, last_ts, monotonic, coverage, None)
    except Exception as exc:
        digest = sha256_file(path) if path.exists() else None
        return SourceRecord(symbol, date, url, http_status, path.stat().st_size if path.exists() else 0, digest, False, columns, rows, first_ts, last_ts, monotonic, False, f"{type(exc).__name__}: {exc}")


def rolling_sum_end(x: np.ndarray, w: int) -> np.ndarray:
    cs = np.concatenate(([0.0], np.cumsum(np.nan_to_num(x, nan=0.0), dtype=np.float64)))
    out = np.full(len(x), np.nan, dtype=np.float64)
    out[w - 1 :] = cs[w:] - cs[:-w]
    return out


def load_npz(path: Path) -> dict[str, np.ndarray]:
    z = np.load(path)
    return {k: z[k] for k in z.files}


def prior_second_features(leader: dict[str, np.ndarray], follower: dict[str, np.ndarray], h: int) -> pd.DataFrame:
    leader_mark = leader["mark"][9::10]
    follower_mark = follower["mark"][9::10]
    leader_return = pd.Series(np.log(leader_mark)).diff()
    follower_return = pd.Series(np.log(follower_mark)).diff()
    pair = leader_return.notna() & follower_return.notna()
    x = leader_return.where(pair)
    y = follower_return.where(pair)
    roll = 1800
    mean_x = x.rolling(roll, min_periods=1200).mean()
    mean_y = y.rolling(roll, min_periods=1200).mean()
    mean_xy = (x * y).rolling(roll, min_periods=1200).mean()
    mean_x2 = (x * x).rolling(roll, min_periods=1200).mean()
    covariance = mean_xy - mean_x * mean_y
    variance = mean_x2 - mean_x * mean_x
    beta = (covariance / variance).clip(0.1, 3.0)
    pair_count = pair.astype(np.int16).rolling(roll, min_periods=1).sum()
    nonzero_count = (leader_return.fillna(0).abs() > 0).astype(np.int16).rolling(roll, min_periods=1).sum()
    beta[(pair_count < 1200) | (nonzero_count < 100) | ~(variance > 0)] = np.nan

    finite = leader_return.notna()
    finite_count = finite.astype(np.int16).rolling(900, min_periods=1).sum()
    nonzero_scale_count = (leader_return.fillna(0).abs() > 0).astype(np.int16).rolling(900, min_periods=1).sum()
    sum_squares = (leader_return.fillna(0) ** 2).rolling(900, min_periods=1).sum()
    scale = np.sqrt(h / 900.0 * sum_squares)
    scale[(finite_count < 600) | (nonzero_scale_count < 60) | ~(scale > 0)] = np.nan

    second_notional = pd.Series(leader["total_notional"].reshape(-1, 10).sum(axis=1))
    h_notional = second_notional.rolling(h, min_periods=h).sum()
    positive_h_notional = h_notional.where(h_notional > 0)
    activity_median = positive_h_notional.rolling(900, min_periods=300).median()
    positive_count = positive_h_notional.notna().astype(np.int16).rolling(900, min_periods=1).sum()
    activity_median[positive_count < 300] = np.nan
    return pd.DataFrame({"beta": beta.to_numpy(), "scale": scale.to_numpy(), "activity_med": activity_median.to_numpy()})


def continuous_events(
    leader: dict[str, np.ndarray], follower: dict[str, np.ndarray], date: str, follower_symbol: str, h: int
) -> tuple[pd.DataFrame, dict]:
    horizon_bins = h * 10
    prior = prior_second_features(leader, follower, h)
    decision_bin = np.arange(BINS_PER_DAY, dtype=np.int32)
    start_boundary = decision_bin + 1 - horizon_bins
    start_mark_index = decision_bin - horizon_bins
    valid_start = start_mark_index >= 0

    leader_return = np.full(BINS_PER_DAY, np.nan)
    follower_return = np.full(BINS_PER_DAY, np.nan)
    valid = valid_start & np.isfinite(leader["mark"])
    valid[valid_start] &= np.isfinite(leader["mark"][start_mark_index[valid_start]])
    index = np.flatnonzero(valid)
    leader_return[index] = np.log(leader["mark"][index] / leader["mark"][start_mark_index[index]])
    valid = valid_start & np.isfinite(follower["mark"])
    valid[valid_start] &= np.isfinite(follower["mark"][start_mark_index[valid_start]])
    index = np.flatnonzero(valid)
    follower_return[index] = np.log(follower["mark"][index] / follower["mark"][start_mark_index[index]])

    leader_notional = rolling_sum_end(leader["total_notional"], horizon_bins)
    leader_signed = rolling_sum_end(leader["signed_notional"], horizon_bins)
    follower_notional = rolling_sum_end(follower["total_notional"], horizon_bins)
    follower_signed = rolling_sum_end(follower["signed_notional"], horizon_bins)
    leader_imbalance = np.divide(leader_signed, leader_notional, out=np.full(BINS_PER_DAY, np.nan), where=leader_notional > 0)
    follower_imbalance = np.divide(follower_signed, follower_notional, out=np.full(BINS_PER_DAY, np.nan), where=follower_notional > 0)

    prior_second = start_boundary // 10 - 1
    prior_valid = (prior_second >= 0) & (prior_second < len(prior))
    beta = np.full(BINS_PER_DAY, np.nan)
    scale = np.full(BINS_PER_DAY, np.nan)
    activity_median = np.full(BINS_PER_DAY, np.nan)
    prior_beta = prior["beta"].to_numpy()
    prior_scale = prior["scale"].to_numpy()
    prior_activity = prior["activity_med"].to_numpy()
    beta[prior_valid] = prior_beta[prior_second[prior_valid]]
    scale[prior_valid] = prior_scale[prior_second[prior_valid]]
    activity_median[prior_valid] = prior_activity[prior_second[prior_valid]]

    direction = np.sign(leader_return)
    expected = np.abs(beta * leader_return)
    gap = direction * (beta * leader_return - follower_return)
    underreaction = np.divide(direction * follower_return, expected, out=np.full(BINS_PER_DAY, np.nan), where=expected > 0)
    z_score = np.divide(np.abs(leader_return), scale, out=np.full(BINS_PER_DAY, np.nan), where=scale > 0)
    activity = np.divide(leader_notional, activity_median, out=np.full(BINS_PER_DAY, np.nan), where=activity_median > 0)
    leader_alignment = direction * leader_imbalance
    follower_alignment = direction * follower_imbalance
    base = (
        np.isfinite(z_score)
        & np.isfinite(activity)
        & np.isfinite(underreaction)
        & np.isfinite(gap)
        & (direction != 0)
        & (expected > 0)
    )
    keep = (
        base
        & (z_score >= 3)
        & (leader_alignment >= 0.5)
        & (activity >= 2)
        & (underreaction <= 0.75)
        & (follower_alignment <= 0.5)
        & (gap >= 0.0012)
    )
    raw_summary = {
        "date": date,
        "follower": follower_symbol,
        "h": h,
        "base_valid": int(base.sum()),
        "raw_gap12": int((base & (gap >= 0.0012)).sum()),
        "raw_gap18": int((base & (gap >= 0.0018)).sum()),
        "raw_gap24": int((base & (gap >= 0.0024)).sum()),
    }
    retained = np.flatnonzero(keep)
    frame = pd.DataFrame(
        {
            "date": date,
            "follower": follower_symbol,
            "h": h,
            "decision_bin": retained,
            "decision_ms": (retained.astype(np.int64) + 1) * 100,
            "direction": direction[retained].astype(np.int8),
            "leader_return": leader_return[retained],
            "follower_return": follower_return[retained],
            "beta": beta[retained],
            "z": z_score[retained],
            "activity": activity[retained],
            "leader_flow_alignment": leader_alignment[retained],
            "follower_flow_alignment": follower_alignment[retained],
            "underreaction_ratio": underreaction[retained],
            "expected_response": expected[retained],
            "remaining_gap": gap[retained],
        }
    )
    raw_summary["full_filter_events"] = int(len(frame))
    return frame, raw_summary


def cell_key(h: int, z: float, leader_flow: float, activity: float, under: float, follower_flow: float, gap: float) -> str:
    return f"h{h}_z{z:g}_lf{leader_flow:g}_a{activity:g}_u{under:g}_ff{follower_flow:g}_g{gap:.4f}"


def evaluate_events(frames: list[pd.DataFrame], raw_summaries: list[dict], followers: Iterable[str]) -> tuple[dict, pd.DataFrame]:
    all_events = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-1015-XASSET-ALT-MICROSHOCK-001",
        "strategy_pnl_computed": False,
        "frozen_validation_opened": False,
        "2024_2026_opened": False,
        "followers": {},
    }
    for follower in followers:
        follower_events = all_events[all_events.follower == follower] if len(all_events) else pd.DataFrame()
        development = follower_events[follower_events.date.isin(DEV_DATES)] if len(follower_events) else pd.DataFrame()
        fit = follower_events[follower_events.date.isin(FIT_DATES)] if len(follower_events) else pd.DataFrame()
        counts: dict[str, dict[str, int]] = {}
        for h, z, leader_flow, activity, under, follower_flow, gap in itertools.product(
            HORIZONS, Z_GRID, BTC_FLOW_GRID, ACTIVITY_GRID, UNDER_GRID, FOLLOWER_FLOW_GRID, GAP_GRID
        ):
            key = cell_key(h, z, leader_flow, activity, under, follower_flow, gap)
            counts[key] = {}
            for date in DEV_DATES:
                subset = development[(development.date == date) & (development.h == h)] if len(development) else development
                count = (
                    int(
                        (
                            (subset.z >= z)
                            & (subset.leader_flow_alignment >= leader_flow)
                            & (subset.activity >= activity)
                            & (subset.underreaction_ratio <= under)
                            & (subset.follower_flow_alignment <= follower_flow)
                            & (subset.remaining_gap >= gap)
                        ).sum()
                    )
                    if len(subset)
                    else 0
                )
                counts[key][date] = count
        ranked = sorted(counts.items(), key=lambda item: (sum(item[1].values()), min(item[1].values()), item[0]), reverse=True)
        best_key, best_by_date = ranked[0]
        best_total = sum(best_by_date.values())
        best_minimum_date = min(best_by_date.values())
        raw_gap24 = int(
            sum(
                item["raw_gap24"]
                for item in raw_summaries
                if item["follower"] == follower and item["date"] in DEV_DATES
            )
        )
        gate_passed = bool(best_total >= 30 and best_minimum_date >= 10 and raw_gap24 >= 20)
        result["followers"][follower] = {
            "fit_full_filter_events": int(len(fit)),
            "development_full_filter_events": int(len(development)),
            "development_by_date": {date: int((development.date == date).sum()) if len(development) else 0 for date in DEV_DATES},
            "development_raw_gap24_events_before_flow_activity_filters": raw_gap24,
            "best_cell": best_key,
            "best_cell_by_date": best_by_date,
            "best_cell_total": best_total,
            "best_cell_minimum_date_count": best_minimum_date,
            "fatal_event_availability_gate_passed": gate_passed,
            "top_20_cells": [
                {"cell": key, "by_date": by_date, "total": sum(by_date.values())} for key, by_date in ranked[:20]
            ],
        }
    result["any_follower_passed"] = any(
        value["fatal_event_availability_gate_passed"] for value in result["followers"].values()
    )
    result["next_action"] = "Implement frozen state-exit PnL only for passing followers; otherwise stop without opening validation."
    return result, all_events


def run(output: Path, cache: Path, dates: tuple[str, ...], symbols: tuple[str, ...], skip_download: bool = False) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    aggregate_dir = output / "aggregates"
    aggregate_dir.mkdir(exist_ok=True)
    records: list[SourceRecord] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-xasset-alt-microshock/1.0"
        for date in dates:
            for symbol in symbols:
                path = cache / symbol / f"{symbol}{date}.csv.gz"
                if skip_download:
                    status, error = (200, None) if path.exists() else (404, "missing local source")
                else:
                    path, status, error = download_one(session, cache, symbol, date)
                record = aggregate(path, aggregate_dir / f"{symbol}{date}_100ms.npz", symbol, date, status, error)
                records.append(record)
                print(json.dumps(asdict(record), sort_keys=True), flush=True)
    source_ok = all(
        record.http_status == 200
        and record.gzip_valid
        and record.timestamp_monotonic
        and record.day_coverage_valid
        and record.rows > 0
        and record.error is None
        for record in records
    )
    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-1015-XASSET-ALT-MICROSHOCK-001",
        "records": [asdict(record) for record in records],
        "all_required_sources_usable": source_ok,
    }
    manifest_path = output / "SOURCE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if not source_ok:
        result = {
            "schema_version": 1,
            "claim_id": manifest["claim_id"],
            "stage": "SOURCE_PROBE",
            "all_required_sources_usable": False,
            "strategy_pnl_computed": False,
            "frozen_validation_opened": False,
            "2024_2026_opened": False,
        }
        (output / "EVENT_AVAILABILITY.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result

    followers = tuple(symbol for symbol in symbols if symbol != "BTCUSDT")
    frames: list[pd.DataFrame] = []
    raw_summaries: list[dict] = []
    for date in dates:
        leader = load_npz(aggregate_dir / f"BTCUSDT{date}_100ms.npz")
        for follower in followers:
            follower_data = load_npz(aggregate_dir / f"{follower}{date}_100ms.npz")
            for h in HORIZONS:
                frame, raw_summary = continuous_events(leader, follower_data, date, follower, h)
                frames.append(frame)
                raw_summaries.append(raw_summary)
                print(json.dumps(raw_summary, sort_keys=True), flush=True)
    result, events = evaluate_events(frames, raw_summaries, followers)
    result["raw_feature_summaries"] = raw_summaries
    result["all_required_sources_usable"] = True
    result_path = output / "EVENT_AVAILABILITY.json"
    events_path = output / "ECONOMIC_EVENTS.csv"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    events.to_csv(events_path, index=False)
    for path in (manifest_path, result_path, events_path):
        (output / (path.name + ".sha256")).write_text(f"{sha256_file(path)}  {path.name}\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--dates", nargs="*", default=list(DEFAULT_DATES))
    parser.add_argument("--symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()
    result = run(args.output, args.cache, tuple(args.dates), tuple(args.symbols), args.skip_download)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
