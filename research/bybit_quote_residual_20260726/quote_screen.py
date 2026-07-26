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

import numpy as np
import pandas as pd
import requests

BINS_PER_DAY = 864_000
GRID_US = 100_000
DEFAULT_DATES = ("2023-01-01", "2023-03-01", "2023-05-01", "2023-07-01")
FIT_DATES = ("2023-01-01", "2023-03-01")
DEV_DATES = ("2023-05-01", "2023-07-01")
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
LEADERS = ("BTCUSDT", "ETHUSDT")
FOLLOWERS = ("SOLUSDT", "XRPUSDT")
HORIZON_MS = (500, 1000, 2000, 5000)
COMMON_Z_GRID = (2.0, 3.0, 4.0)
BALANCE_GRID = (0.25, 0.5)
AVG_QUEUE_GRID = (0.0, 0.25)
MIN_QUEUE_GRID = (-0.25, 0.0)
INTENSITY_GRID = (1.5, 3.0)
UNDER_GRID = (0.25, 0.5, 0.75)
FOLLOWER_QUEUE_GRID = (0.25, 0.5)
SPREAD_GRID_BPS = (3.0, 6.0)
GAP_GRID = (0.0012, 0.0018, 0.0024)
COOLDOWN_US = 5_000_000
BASE_URL = "https://datasets.tardis.dev/v1/bybit/quotes/{year}/{month}/{day}/{symbol}.csv.gz"


@dataclass(frozen=True, slots=True)
class SourceRecord:
    symbol: str
    date: str
    url: str
    http_status: int
    bytes: int
    sha256: str | None
    gzip_valid: bool
    columns: list[str]
    parsed_rows: int
    valid_quote_rows: int
    crossed_or_invalid_rows: int
    first_local_timestamp: int | None
    last_local_timestamp: int | None
    local_timestamp_monotonic: bool
    day_coverage_valid: bool
    error: str | None


def day_start_us(date: str) -> int:
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1_000_000)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_url(symbol: str, date: str) -> str:
    year, month, day = date.split("-")
    return BASE_URL.format(year=year, month=month, day=day, symbol=symbol)


def download_one(session: requests.Session, cache: Path, symbol: str, date: str) -> tuple[Path, int, str | None]:
    url = source_url(symbol, date)
    target = cache / symbol / f"{symbol}-{date}-quotes.csv.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        return target, 200, None
    failures: list[str] = []
    for attempt in range(4):
        try:
            with session.get(url, stream=True, timeout=(30, 600)) as response:
                status = int(response.status_code)
                if status == 200:
                    temporary = target.with_suffix(target.suffix + ".part")
                    with temporary.open("wb") as output:
                        for chunk in response.iter_content(1 << 20):
                            if chunk:
                                output.write(chunk)
                    temporary.replace(target)
                    return target, status, None
                failures.append(f"HTTP {status}")
                if status in (400, 401, 403, 404):
                    return target, status, failures[-1]
        except requests.RequestException as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(2**attempt, 8))
    return target, 0, "; ".join(failures[-4:]) or "download failed"


def aggregate_quotes(path: Path, output: Path, symbol: str, date: str, status: int, download_error: str | None) -> SourceRecord:
    url = source_url(symbol, date)
    if status != 200 or not path.exists():
        return SourceRecord(symbol, date, url, status, 0, None, False, [], 0, 0, 0, None, None, False, False, download_error or "source unavailable")
    first_bid = np.full(BINS_PER_DAY, np.nan)
    first_ask = np.full(BINS_PER_DAY, np.nan)
    first_bid_amount = np.full(BINS_PER_DAY, np.nan)
    first_ask_amount = np.full(BINS_PER_DAY, np.nan)
    first_local_us = np.full(BINS_PER_DAY, -1, dtype=np.int64)
    last_bid = np.full(BINS_PER_DAY, np.nan)
    last_ask = np.full(BINS_PER_DAY, np.nan)
    last_bid_amount = np.full(BINS_PER_DAY, np.nan)
    last_ask_amount = np.full(BINS_PER_DAY, np.nan)
    last_local_us = np.full(BINS_PER_DAY, -1, dtype=np.int64)
    update_count = np.zeros(BINS_PER_DAY, dtype=np.int32)
    start = day_start_us(date)
    end = start + 86_400_000_000
    required = ["exchange", "symbol", "timestamp", "local_timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"]
    parsed_rows = valid_rows = invalid_rows = 0
    first_seen = last_seen = None
    previous = -1
    monotonic = True
    columns: list[str] = []
    try:
        with gzip.open(path, "rt", newline="") as raw:
            reader = pd.read_csv(raw, usecols=required, dtype={"exchange": "string", "symbol": "string", "timestamp": "int64", "local_timestamp": "int64", "ask_amount": "float64", "ask_price": "float64", "bid_price": "float64", "bid_amount": "float64"}, chunksize=500_000)
            columns = required
            for chunk in reader:
                if chunk.empty:
                    continue
                local = chunk["local_timestamp"].to_numpy(np.int64, copy=False)
                parsed_rows += len(local)
                if local[0] < previous or np.any(local[1:] < local[:-1]):
                    monotonic = False
                    raise ValueError("local_timestamp is not monotonic")
                previous = int(local[-1])
                first_seen = int(local[0]) if first_seen is None else first_seen
                last_seen = int(local[-1])
                bid = chunk["bid_price"].to_numpy(np.float64, copy=False)
                ask = chunk["ask_price"].to_numpy(np.float64, copy=False)
                bid_amount = chunk["bid_amount"].to_numpy(np.float64, copy=False)
                ask_amount = chunk["ask_amount"].to_numpy(np.float64, copy=False)
                index = ((local - start) // GRID_US).astype(np.int64)
                valid = (index >= 0) & (index < BINS_PER_DAY) & np.isfinite(bid) & np.isfinite(ask) & np.isfinite(bid_amount) & np.isfinite(ask_amount) & (bid > 0) & (ask > 0) & (ask >= bid) & (bid_amount >= 0) & (ask_amount >= 0)
                invalid_rows += int((~valid).sum())
                index, local, bid, ask, bid_amount, ask_amount = index[valid], local[valid], bid[valid], ask[valid], bid_amount[valid], ask_amount[valid]
                if len(index) == 0:
                    continue
                valid_rows += len(index)
                update_count += np.bincount(index, minlength=BINS_PER_DAY).astype(np.int32)
                unique, first_position = np.unique(index, return_index=True)
                missing_first = first_local_us[unique] < 0
                if missing_first.any():
                    u, p = unique[missing_first], first_position[missing_first]
                    first_bid[u], first_ask[u] = bid[p], ask[p]
                    first_bid_amount[u], first_ask_amount[u] = bid_amount[p], ask_amount[p]
                    first_local_us[u] = local[p]
                reverse_unique, reverse_position = np.unique(index[::-1], return_index=True)
                last_position = len(index) - 1 - reverse_position
                last_bid[reverse_unique], last_ask[reverse_unique] = bid[last_position], ask[last_position]
                last_bid_amount[reverse_unique], last_ask_amount[reverse_unique] = bid_amount[last_position], ask_amount[last_position]
                last_local_us[reverse_unique] = local[last_position]
        digest = sha256_file(path)
        coverage = bool(first_seen is not None and last_seen is not None and start <= first_seen < start + 300_000_000 and end - 300_000_000 < last_seen < end)
        output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(output, symbol=np.array(symbol), date=np.array(date), source_name=np.array(path.name), source_sha256=np.array(digest), first_bid=first_bid, first_ask=first_ask, first_bid_amount=first_bid_amount, first_ask_amount=first_ask_amount, first_local_us=first_local_us, last_bid=last_bid, last_ask=last_ask, last_bid_amount=last_bid_amount, last_ask_amount=last_ask_amount, last_local_us=last_local_us, update_count=update_count)
        return SourceRecord(symbol, date, url, status, path.stat().st_size, digest, True, columns, parsed_rows, valid_rows, invalid_rows, first_seen, last_seen, monotonic, coverage, None)
    except Exception as exc:
        digest = sha256_file(path) if path.exists() else None
        return SourceRecord(symbol, date, url, status, path.stat().st_size if path.exists() else 0, digest, False, columns, parsed_rows, valid_rows, invalid_rows, first_seen, last_seen, monotonic, False, f"{type(exc).__name__}: {exc}")


def load_aggregate(path: Path) -> dict[str, np.ndarray]:
    with np.load(path) as archive:
        return {key: archive[key] for key in archive.files}


def carried_quote(data: dict[str, np.ndarray], max_age_bins: int) -> dict[str, np.ndarray]:
    occupied = data["update_count"] > 0
    index = np.arange(BINS_PER_DAY, dtype=np.int32)
    last_index = np.maximum.accumulate(np.where(occupied, index, -1))
    age = index - last_index
    valid = (last_index >= 0) & (age <= max_age_bins)
    safe = np.maximum(last_index, 0)
    bid, ask, bid_amount, ask_amount = (np.full(BINS_PER_DAY, np.nan) for _ in range(4))
    bid[valid], ask[valid] = data["last_bid"][safe[valid]], data["last_ask"][safe[valid]]
    bid_amount[valid], ask_amount[valid] = data["last_bid_amount"][safe[valid]], data["last_ask_amount"][safe[valid]]
    mid = (bid + ask) / 2
    spread = np.log(ask / bid)
    total = bid_amount + ask_amount
    queue = np.divide(bid_amount - ask_amount, total, out=np.full(BINS_PER_DAY, np.nan), where=total > 0)
    microprice = np.divide(ask * bid_amount + bid * ask_amount, total, out=np.full(BINS_PER_DAY, np.nan), where=total > 0)
    return {"bid": bid, "ask": ask, "mid": mid, "spread": spread, "queue": queue, "microprice": microprice, "age_bins": age, "valid": valid}


def first_quote_after(data: dict[str, np.ndarray], eligible_bin: np.ndarray, timeout_bins: int = 5) -> dict[str, np.ndarray]:
    occupied = data["update_count"] > 0
    reverse = np.minimum.accumulate(np.where(occupied, np.arange(BINS_PER_DAY), BINS_PER_DAY)[::-1])[::-1]
    eligible = np.asarray(eligible_bin, dtype=np.int64)
    safe_eligible = np.clip(eligible, 0, BINS_PER_DAY - 1)
    selected = reverse[safe_eligible]
    valid = (eligible >= 0) & (eligible < BINS_PER_DAY) & (selected < BINS_PER_DAY) & ((selected - eligible) <= timeout_bins)
    safe = np.minimum(selected, BINS_PER_DAY - 1)
    result: dict[str, np.ndarray] = {"selected_bin": selected.astype(np.int64), "valid": valid}
    for source, target in (("first_bid", "bid"), ("first_ask", "ask"), ("first_bid_amount", "bid_amount"), ("first_ask_amount", "ask_amount"), ("first_local_us", "local_us")):
        values = np.full(len(eligible), -1, dtype=np.int64) if source == "first_local_us" else np.full(len(eligible), np.nan)
        values[valid] = data[source][safe[valid]]
        result[target] = values
    result["spread"] = np.log(result["ask"] / result["bid"])
    total = result["bid_amount"] + result["ask_amount"]
    result["queue"] = np.divide(result["bid_amount"] - result["ask_amount"], total, out=np.full(len(eligible), np.nan), where=total > 0)
    return result


def rolling_sum_end(values: np.ndarray, window: int) -> np.ndarray:
    cumulative = np.concatenate(([0.0], np.cumsum(np.nan_to_num(values, nan=0.0))))
    result = np.full(len(values), np.nan)
    result[window - 1:] = cumulative[window:] - cumulative[:-window]
    return result


def second_return(state: dict[str, np.ndarray]) -> pd.Series:
    return pd.Series(np.log(state["mid"][9::10])).diff()


def prior_ridge_model(btc_state: dict[str, np.ndarray], eth_state: dict[str, np.ndarray], follower_state: dict[str, np.ndarray]) -> pd.DataFrame:
    btc, eth, follower = second_return(btc_state), second_return(eth_state), second_return(follower_state)
    valid = btc.notna() & eth.notna() & follower.notna()
    btc, eth, follower = btc.where(valid), eth.where(valid), follower.where(valid)
    window, minimum = 1800, 1200
    mb, me, mf = btc.rolling(window, min_periods=minimum).mean(), eth.rolling(window, min_periods=minimum).mean(), follower.rolling(window, min_periods=minimum).mean()
    vbb = (btc * btc).rolling(window, min_periods=minimum).mean() - mb * mb
    vee = (eth * eth).rolling(window, min_periods=minimum).mean() - me * me
    cbe = (btc * eth).rolling(window, min_periods=minimum).mean() - mb * me
    cbf = (btc * follower).rolling(window, min_periods=minimum).mean() - mb * mf
    cef = (eth * follower).rolling(window, min_periods=minimum).mean() - me * mf
    ridge = 0.05 * (vbb + vee) / 2
    a, d = vbb + ridge, vee + ridge
    determinant = a * d - cbe * cbe
    beta_btc = (d * cbf - cbe * cef) / determinant
    beta_eth = (a * cef - cbe * cbf) / determinant
    count = valid.astype(np.int16).rolling(window, min_periods=1).sum()
    btc_nonzero = (btc.fillna(0).abs() > 0).astype(np.int16).rolling(window, min_periods=1).sum()
    eth_nonzero = (eth.fillna(0).abs() > 0).astype(np.int16).rolling(window, min_periods=1).sum()
    invalid = (count < minimum) | (btc_nonzero < 100) | (eth_nonzero < 100) | ~(determinant > 0) | ~np.isfinite(beta_btc) | ~np.isfinite(beta_eth)
    beta_btc, beta_eth = beta_btc.clip(-2, 4), beta_eth.clip(-2, 4)
    beta_btc[invalid], beta_eth[invalid] = np.nan, np.nan
    return pd.DataFrame({"beta_btc": beta_btc.to_numpy(), "beta_eth": beta_eth.to_numpy()})


def prior_scale_and_intensity(data: dict[str, np.ndarray], state: dict[str, np.ndarray], horizon_bins: int) -> pd.DataFrame:
    returns = second_return(state)
    finite_count = returns.notna().astype(np.int16).rolling(900, min_periods=1).sum()
    nonzero_count = (returns.fillna(0).abs() > 0).astype(np.int16).rolling(900, min_periods=1).sum()
    sum_squares = (returns.fillna(0) ** 2).rolling(900, min_periods=1).sum()
    scale = np.sqrt((horizon_bins / 10) / 900 * sum_squares)
    scale[(finite_count < 600) | (nonzero_count < 60) | ~(scale > 0)] = np.nan
    horizon_updates = rolling_sum_end(data["update_count"].astype(float), horizon_bins)
    positive = pd.Series(horizon_updates[9::10]).where(lambda series: series > 0)
    median = positive.rolling(900, min_periods=300).median()
    count = positive.notna().astype(np.int16).rolling(900, min_periods=1).sum()
    median[count < 300] = np.nan
    return pd.DataFrame({"scale": scale.to_numpy(), "intensity_median": median.to_numpy()})


def horizon_return(mid: np.ndarray, horizon_bins: int) -> tuple[np.ndarray, np.ndarray]:
    index = np.arange(BINS_PER_DAY, dtype=np.int32)
    start = index - horizon_bins
    result, start_mid = np.full(BINS_PER_DAY, np.nan), np.full(BINS_PER_DAY, np.nan)
    rows = np.flatnonzero((start >= 0) & np.isfinite(mid))
    rows = rows[np.isfinite(mid[start[rows]])]
    result[rows], start_mid[rows] = np.log(mid[rows] / mid[start[rows]]), mid[start[rows]]
    return result, start_mid


def map_prior(values: np.ndarray, horizon_bins: int) -> np.ndarray:
    index = np.arange(BINS_PER_DAY, dtype=np.int32)
    prior_second = (index + 1 - horizon_bins) // 10 - 1
    output = np.full(BINS_PER_DAY, np.nan)
    valid = (prior_second >= 0) & (prior_second < len(values))
    output[valid] = values[prior_second[valid]]
    return output


def build_event_frame(aggregate_dir: Path, date: str, follower_symbol: str, horizon_ms: int) -> tuple[pd.DataFrame, dict]:
    horizon_bins = horizon_ms // 100
    raw = {symbol: load_aggregate(aggregate_dir / f"{symbol}-{date}-quotes-100ms.npz") for symbol in (*LEADERS, follower_symbol)}
    prior_state = {symbol: carried_quote(raw[symbol], 10) for symbol in (*LEADERS, follower_symbol)}
    decision_state = {symbol: carried_quote(raw[symbol], 5) for symbol in (*LEADERS, follower_symbol)}
    model = prior_ridge_model(prior_state["BTCUSDT"], prior_state["ETHUSDT"], prior_state[follower_symbol])
    btc_prior = prior_scale_and_intensity(raw["BTCUSDT"], prior_state["BTCUSDT"], horizon_bins)
    eth_prior = prior_scale_and_intensity(raw["ETHUSDT"], prior_state["ETHUSDT"], horizon_bins)
    btc_return, _ = horizon_return(decision_state["BTCUSDT"]["mid"], horizon_bins)
    eth_return, _ = horizon_return(decision_state["ETHUSDT"]["mid"], horizon_bins)
    follower_return, follower_start_mid = horizon_return(decision_state[follower_symbol]["mid"], horizon_bins)
    beta_btc = map_prior(model["beta_btc"].to_numpy(), horizon_bins)
    beta_eth = map_prior(model["beta_eth"].to_numpy(), horizon_bins)
    btc_scale = map_prior(btc_prior["scale"].to_numpy(), horizon_bins)
    eth_scale = map_prior(eth_prior["scale"].to_numpy(), horizon_bins)
    btc_intensity_median = map_prior(btc_prior["intensity_median"].to_numpy(), horizon_bins)
    eth_intensity_median = map_prior(eth_prior["intensity_median"].to_numpy(), horizon_bins)
    btc_updates = rolling_sum_end(raw["BTCUSDT"]["update_count"].astype(float), horizon_bins)
    eth_updates = rolling_sum_end(raw["ETHUSDT"]["update_count"].astype(float), horizon_bins)
    direction = np.sign(btc_return)
    same_direction = (np.sign(btc_return) == np.sign(eth_return)) & (direction != 0)
    btc_z = np.divide(np.abs(btc_return), btc_scale, out=np.full(BINS_PER_DAY, np.nan), where=btc_scale > 0)
    eth_z = np.divide(np.abs(eth_return), eth_scale, out=np.full(BINS_PER_DAY, np.nan), where=eth_scale > 0)
    common_score = np.divide(btc_z + eth_z, math.sqrt(2), out=np.full(BINS_PER_DAY, np.nan), where=np.isfinite(btc_z) & np.isfinite(eth_z))
    leader_balance = np.divide(np.minimum(btc_z, eth_z), np.maximum(btc_z, eth_z), out=np.full(BINS_PER_DAY, np.nan), where=np.maximum(btc_z, eth_z) > 0)
    btc_queue, eth_queue = direction * decision_state["BTCUSDT"]["queue"], direction * decision_state["ETHUSDT"]["queue"]
    average_queue, minimum_queue = (btc_queue + eth_queue) / 2, np.minimum(btc_queue, eth_queue)
    btc_intensity = np.divide(btc_updates, btc_intensity_median, out=np.full(BINS_PER_DAY, np.nan), where=btc_intensity_median > 0)
    eth_intensity = np.divide(eth_updates, eth_intensity_median, out=np.full(BINS_PER_DAY, np.nan), where=eth_intensity_median > 0)
    intensity_consensus = np.sqrt(np.maximum(btc_intensity, 0) * np.maximum(eth_intensity, 0))
    expected_return = beta_btc * btc_return + beta_eth * eth_return
    underreaction = np.divide(direction * follower_return, np.abs(expected_return), out=np.full(BINS_PER_DAY, np.nan), where=np.abs(expected_return) > 0)
    follower_queue = direction * decision_state[follower_symbol]["queue"]
    index = np.arange(BINS_PER_DAY, dtype=np.int64)
    entry = first_quote_after(raw[follower_symbol], index + 2, 5)
    entry_price = np.where(direction > 0, entry["ask"], entry["bid"])
    target_mid = follower_start_mid * np.exp(expected_return)
    target_exit = target_mid * np.exp(-direction * entry["spread"] / 2)
    executable_gap = direction * (np.log(target_exit) - np.log(entry_price))
    follower_spread_bps = entry["spread"] * 10_000
    leader_spread_ok = (decision_state["BTCUSDT"]["spread"] * 10_000 <= 5) & (decision_state["ETHUSDT"]["spread"] * 10_000 <= 5)
    base = same_direction & leader_spread_ok & np.isfinite(common_score) & np.isfinite(leader_balance) & np.isfinite(average_queue) & np.isfinite(minimum_queue) & np.isfinite(intensity_consensus) & np.isfinite(expected_return) & (direction * expected_return > 0) & np.isfinite(underreaction) & np.isfinite(follower_queue) & entry["valid"] & np.isfinite(executable_gap) & np.isfinite(follower_spread_bps)
    loose = base & (common_score >= 2) & (leader_balance >= 0.25) & (average_queue >= 0) & (minimum_queue >= -0.25) & (intensity_consensus >= 1.5) & (underreaction <= 0.75) & (follower_queue <= 0.5) & (follower_spread_bps <= 6) & (executable_gap >= 0.0012)
    retained = np.flatnonzero(loose)
    frame = pd.DataFrame({"date": date, "follower": follower_symbol, "horizon_ms": horizon_ms, "decision_bin": retained, "decision_local_us": day_start_us(date) + (retained.astype(np.int64) + 1) * GRID_US, "entry_local_us": entry["local_us"][retained], "direction": direction[retained].astype(np.int8), "common_score": common_score[retained], "leader_balance": leader_balance[retained], "average_leader_queue": average_queue[retained], "minimum_leader_queue": minimum_queue[retained], "intensity_consensus": intensity_consensus[retained], "underreaction_ratio": underreaction[retained], "follower_queue_alignment": follower_queue[retained], "follower_spread_bps": follower_spread_bps[retained], "executable_gap": executable_gap[retained], "expected_return": expected_return[retained], "follower_return": follower_return[retained], "entry_price": entry_price[retained], "target_exit_price": target_exit[retained], "beta_btc": beta_btc[retained], "beta_eth": beta_eth[retained], "btc_return": btc_return[retained], "eth_return": eth_return[retained]})
    summary = {"date": date, "follower": follower_symbol, "horizon_ms": horizon_ms, "base_valid": int(base.sum()), "raw_executable_gap12": int((base & (executable_gap >= 0.0012)).sum()), "raw_executable_gap18": int((base & (executable_gap >= 0.0018)).sum()), "raw_executable_gap24": int((base & (executable_gap >= 0.0024)).sum()), "full_filter_rows": int(len(frame))}
    return frame, summary


def thinned_count(local_us: np.ndarray) -> int:
    if len(local_us) == 0:
        return 0
    count, next_eligible = 0, -1
    for timestamp in np.sort(local_us.astype(np.int64, copy=False)):
        if timestamp >= next_eligible:
            count += 1
            next_eligible = int(timestamp) + COOLDOWN_US
    return count


def cell_name(values: tuple) -> str:
    horizon, common, balance, average_queue, minimum_queue, intensity, under, follower_queue, spread, gap = values
    return f"h{horizon}_c{common:g}_b{balance:g}_aq{average_queue:g}_mq{minimum_queue:g}_i{intensity:g}_u{under:g}_fq{follower_queue:g}_s{spread:g}_g{gap:.4f}"


def evaluate(frames: list[pd.DataFrame], raw_summaries: list[dict]) -> tuple[dict, pd.DataFrame]:
    events = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    grid = list(itertools.product(HORIZON_MS, COMMON_Z_GRID, BALANCE_GRID, AVG_QUEUE_GRID, MIN_QUEUE_GRID, INTENSITY_GRID, UNDER_GRID, FOLLOWER_QUEUE_GRID, SPREAD_GRID_BPS, GAP_GRID))
    if len(grid) != 6912:
        raise AssertionError(f"unexpected grid size {len(grid)}")
    result = {"schema_version": 1, "claim_id": "CLM-20260726-1031-QUOTE-RESIDUAL-001", "strategy_pnl_computed": False, "frozen_validation_opened": False, "2024_2026_opened": False, "followers": {}, "raw_feature_summaries": raw_summaries}
    for follower in FOLLOWERS:
        follower_events = events[events.follower == follower] if len(events) else pd.DataFrame()
        fit = follower_events[follower_events.date.isin(FIT_DATES)] if len(follower_events) else follower_events
        development = follower_events[follower_events.date.isin(DEV_DATES)] if len(follower_events) else follower_events
        ranking = []
        for values in grid:
            horizon, common, balance, average_queue, minimum_queue, intensity, under, follower_queue, spread, gap = values
            counts = {}
            for date in DEV_DATES:
                subset = development[(development.date == date) & (development.horizon_ms == horizon)] if len(development) else development
                if len(subset):
                    mask = (subset.common_score >= common) & (subset.leader_balance >= balance) & (subset.average_leader_queue >= average_queue) & (subset.minimum_leader_queue >= minimum_queue) & (subset.intensity_consensus >= intensity) & (subset.underreaction_ratio <= under) & (subset.follower_queue_alignment <= follower_queue) & (subset.follower_spread_bps <= spread) & (subset.executable_gap >= gap)
                    counts[date] = thinned_count(subset.loc[mask, "decision_local_us"].to_numpy())
                else:
                    counts[date] = 0
            ranking.append((sum(counts.values()), min(counts.values()), cell_name(values), counts))
        ranking.sort(reverse=True)
        best_total, best_minimum, best_cell, best_counts = ranking[0]
        raw_gap24 = int(sum(item["raw_executable_gap24"] for item in raw_summaries if item["follower"] == follower and item["date"] in DEV_DATES))
        passed = best_total >= 40 and best_minimum >= 15 and raw_gap24 >= 30
        result["followers"][follower] = {"fit_full_filter_rows": int(len(fit)), "development_full_filter_rows": int(len(development)), "development_full_filter_rows_by_date": {date: int((development.date == date).sum()) if len(development) else 0 for date in DEV_DATES}, "development_raw_24bp_executable_gaps_before_other_filters": raw_gap24, "best_cell": best_cell, "best_cell_independent_events_by_date": best_counts, "best_cell_independent_events_total": best_total, "best_cell_minimum_date_count": best_minimum, "fatal_event_availability_gate_passed": bool(passed), "top_20_cells": [{"cell": item[2], "by_date": item[3], "total": item[0], "minimum_date_count": item[1]} for item in ranking[:20]]}
    result["any_follower_passed"] = any(item["fatal_event_availability_gate_passed"] for item in result["followers"].values())
    result["next_action"] = "Implement frozen actual-BBO state-exit PnL only for passing followers; otherwise stop without opening validation."
    return result, events


def self_test(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    date, start = "2023-01-01", day_start_us("2023-01-01")
    rows = ["exchange,symbol,timestamp,local_timestamp,ask_amount,ask_price,bid_price,bid_amount", f"bybit,BTCUSDT,{start + 10000},{start + 20000},2,101,100,3", f"bybit,BTCUSDT,{start + 120000},{start + 130000},4,102,101,5"]
    source = directory / "synthetic.csv.gz"
    with gzip.open(source, "wt") as handle:
        handle.write("\n".join(rows) + "\n")
    record = aggregate_quotes(source, directory / "synthetic.npz", "BTCUSDT", date, 200, None)
    assert record.gzip_valid and record.valid_quote_rows == 2 and record.local_timestamp_monotonic
    data = load_aggregate(directory / "synthetic.npz")
    state = carried_quote(data, 5)
    assert state["bid"][0] == 100 and state["ask"][1] == 102
    first = first_quote_after(data, np.array([0, 1]), 5)
    assert first["valid"].all() and first["bid"][0] == 100 and first["bid"][1] == 101
    assert thinned_count(np.array([0, 100000, 5000000, 5100000])) == 2
    print("quote residual self-test passed")


def run(output: Path, cache: Path, dates: tuple[str, ...], symbols: tuple[str, ...], skip_download: bool = False) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    aggregate_dir = output / "aggregates"
    aggregate_dir.mkdir(exist_ok=True)
    records = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-quote-residual/1.0"
        for date in dates:
            for symbol in symbols:
                path = cache / symbol / f"{symbol}-{date}-quotes.csv.gz"
                if skip_download:
                    status, error = ((200, None) if path.exists() else (404, "missing local source"))
                else:
                    path, status, error = download_one(session, cache, symbol, date)
                record = aggregate_quotes(path, aggregate_dir / f"{symbol}-{date}-quotes-100ms.npz", symbol, date, status, error)
                records.append(record)
                print(json.dumps(asdict(record), sort_keys=True), flush=True)
    sources_usable = all(record.http_status == 200 and record.gzip_valid and record.local_timestamp_monotonic and record.day_coverage_valid and record.valid_quote_rows > 0 and record.error is None for record in records)
    manifest = {"schema_version": 1, "claim_id": "CLM-20260726-1031-QUOTE-RESIDUAL-001", "records": [asdict(record) for record in records], "all_required_sources_usable": sources_usable}
    manifest_path = output / "SOURCE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if not sources_usable:
        result = {"schema_version": 1, "claim_id": manifest["claim_id"], "stage": "SOURCE_PROBE", "all_required_sources_usable": False, "strategy_pnl_computed": False, "frozen_validation_opened": False, "2024_2026_opened": False}
        (output / "EVENT_AVAILABILITY.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result
    frames, summaries = [], []
    for date in dates:
        for follower in FOLLOWERS:
            for horizon in HORIZON_MS:
                frame, summary = build_event_frame(aggregate_dir, date, follower, horizon)
                frames.append(frame)
                summaries.append(summary)
                print(json.dumps(summary, sort_keys=True), flush=True)
    result, events = evaluate(frames, summaries)
    result["all_required_sources_usable"] = True
    result_path, events_path = output / "EVENT_AVAILABILITY.json", output / "EXECUTABLE_QUOTE_EVENTS.csv"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    events.to_csv(events_path, index=False)
    for path in (manifest_path, result_path, events_path):
        (output / f"{path.name}.sha256").write_text(f"{sha256_file(path)}  {path.name}\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--dates", nargs="*", default=list(DEFAULT_DATES))
    parser.add_argument("--symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test(args.output)
        return 0
    result = run(args.output, args.cache, tuple(args.dates), tuple(args.symbols), args.skip_download)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
