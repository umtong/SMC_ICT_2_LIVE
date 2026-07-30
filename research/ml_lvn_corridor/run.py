from __future__ import annotations

import bisect
import hashlib
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(os.environ.get("BYBIT_CANONICAL_PANDAS_ROOT", "/mnt/data/alds_core")).expanduser().resolve()
DAY_MS = 86_400_000


@dataclass(frozen=True)
class Topology:
    bin_bps: int
    window_days: int
    high_q: float
    low_frac: float
    min_bins: int = 2
    max_bins: int = 60


FEATURES = [
    "symbol_eth", "direction", "corridor_pct", "width_bins", "cur_density_ratio", "prev_density_ratio",
    "lower_density_ratio", "upper_density_ratio", "entry_depth", "origin_distance", "destination_distance",
    "ret_15m", "ret_1h", "ret_4h", "ret_24h", "ret_72h", "range_15m", "atr_4h", "atr_24h",
    "rv_4h", "rv_24h", "volume_z_24h", "turnover_z_24h", "body_frac", "close_location", "vwap_deviation",
    "oi_chg_15m", "oi_chg_1h", "oi_chg_4h", "oi_chg_24h", "oi_change_z_24h",
    "account_bias", "account_chg_1h", "account_chg_4h", "funding_rate",
    "other_ret_15m", "other_ret_1h", "other_ret_4h", "other_ret_24h", "relative_ret_4h", "relative_ret_24h",
    "cross_direction_agree_1h", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_export() -> dict:
    manifest = json.loads((ROOT / "EXPORT_MANIFEST.json").read_text())
    checks = []
    for item in manifest["tables"]:
        path = ROOT / item["symbol"] / f"{item['table']}.pkl.gz"
        actual = sha256_file(path)
        checks.append({"path": str(path), "expected": item["sha256"], "actual": actual, "ok": actual == item["sha256"]})
    if not all(item["ok"] for item in checks):
        raise RuntimeError("export hash mismatch")
    return {"manifest_sha256": sha256_file(ROOT / "EXPORT_MANIFEST.json"), "files": checks}


class DataCache:
    def __init__(self):
        self.frames = {}
        self.passage_trees = {}

    def get(self, symbol: str, name: str):
        key = (symbol, name)
        if key not in self.frames:
            self.frames[key] = pd.read_pickle(ROOT / symbol / f"{name}.pkl.gz", compression="gzip")
        return self.frames[key]


def _smooth(profile: dict[int, float], key: int) -> float:
    return (
        .15 * profile.get(key - 2, 0.0)
        + .20 * profile.get(key - 1, 0.0)
        + .30 * profile.get(key, 0.0)
        + .20 * profile.get(key + 1, 0.0)
        + .15 * profile.get(key + 2, 0.0)
    )


def prepare_feature_frames(cache: DataCache) -> dict[str, pd.DataFrame]:
    output = {}
    base = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        bars = cache.get(symbol, "bars_15m").copy()
        bars = bars[bars["is_complete"] & bars["close"].notna()].sort_values("start_time_ms").reset_index(drop=True)
        close = bars["close"].astype(float)
        log_close = np.log(close)
        returns = log_close.diff()
        bars["ret_15m"] = close.pct_change(1)
        bars["ret_1h"] = close.pct_change(4)
        bars["ret_4h"] = close.pct_change(16)
        bars["ret_24h"] = close.pct_change(96)
        bars["ret_72h"] = close.pct_change(288)
        bars["range_15m"] = bars["high"] / bars["low"] - 1
        bars["atr_4h"] = bars["range_15m"].rolling(16, min_periods=8).mean()
        bars["atr_24h"] = bars["range_15m"].rolling(96, min_periods=48).mean()
        bars["rv_4h"] = returns.rolling(16, min_periods=8).std()
        bars["rv_24h"] = returns.rolling(96, min_periods=48).std()
        log_volume = np.log1p(bars["volume"])
        log_turnover = np.log1p(bars["turnover"])
        bars["volume_z_24h"] = (log_volume - log_volume.rolling(96, min_periods=48).mean()) / log_volume.rolling(96, min_periods=48).std()
        bars["turnover_z_24h"] = (log_turnover - log_turnover.rolling(96, min_periods=48).mean()) / log_turnover.rolling(96, min_periods=48).std()
        candle_range = (bars["high"] - bars["low"]).replace(0, np.nan)
        bars["body_frac"] = (bars["close"] - bars["open"]) / candle_range
        bars["close_location"] = (bars["close"] - bars["low"]) / candle_range
        vwap = (bars["turnover"] / bars["volume"]).where(bars["volume"] > 0)
        bars["vwap_deviation"] = bars["close"] / vwap - 1
        available = pd.to_datetime(bars["available_at_ms"].astype("int64"), unit="ms", utc=True)
        bars["hour_sin"] = np.sin(2 * np.pi * available.dt.hour / 24)
        bars["hour_cos"] = np.cos(2 * np.pi * available.dt.hour / 24)
        bars["dow_sin"] = np.sin(2 * np.pi * available.dt.dayofweek / 7)
        bars["dow_cos"] = np.cos(2 * np.pi * available.dt.dayofweek / 7)
        bars["available_at_ms"] = bars["available_at_ms"].astype("int64")

        oi = cache.get(symbol, "open_interest_5m").copy().sort_values("available_at_ms")
        oi = oi[oi["observed"] & oi["open_interest"].gt(0)].copy()
        log_oi = np.log(oi["open_interest"])
        oi["oi_chg_15m"] = log_oi.diff(3)
        oi["oi_chg_1h"] = log_oi.diff(12)
        oi["oi_chg_4h"] = log_oi.diff(48)
        oi["oi_chg_24h"] = log_oi.diff(288)
        oi_change = log_oi.diff(3)
        oi["oi_change_z_24h"] = (oi_change - oi_change.rolling(288, min_periods=144).mean()) / oi_change.rolling(288, min_periods=144).std()
        oi = oi[["available_at_ms", "oi_chg_15m", "oi_chg_1h", "oi_chg_4h", "oi_chg_24h", "oi_change_z_24h"]]
        bars = pd.merge_asof(bars.sort_values("available_at_ms"), oi, on="available_at_ms", direction="backward")

        ratio = cache.get(symbol, "account_ratio_5m").copy().sort_values("available_at_ms")
        ratio = ratio[ratio["observed"]].copy()
        ratio["account_bias"] = ratio["buy_ratio"] - ratio["sell_ratio"]
        ratio["account_chg_1h"] = ratio["account_bias"].diff(12)
        ratio["account_chg_4h"] = ratio["account_bias"].diff(48)
        ratio = ratio[["available_at_ms", "account_bias", "account_chg_1h", "account_chg_4h"]]
        bars = pd.merge_asof(bars.sort_values("available_at_ms"), ratio, on="available_at_ms", direction="backward")

        funding = cache.get(symbol, "funding_events").copy().sort_values("available_at_ms")
        bars = pd.merge_asof(bars.sort_values("available_at_ms"), funding[["available_at_ms", "funding_rate"]], on="available_at_ms", direction="backward")
        base[symbol] = bars.sort_values("start_time_ms")

    for symbol, other in (("BTCUSDT", "ETHUSDT"), ("ETHUSDT", "BTCUSDT")):
        frame = base[symbol].copy()
        other_frame = base[other][["start_time_ms", "ret_15m", "ret_1h", "ret_4h", "ret_24h"]].copy()
        other_frame = other_frame.rename(columns={name: f"other_{name}" for name in ("ret_15m", "ret_1h", "ret_4h", "ret_24h")})
        frame = frame.merge(other_frame, on="start_time_ms", how="left")
        frame["relative_ret_4h"] = frame["ret_4h"] - frame["other_ret_4h"]
        frame["relative_ret_24h"] = frame["ret_24h"] - frame["other_ret_24h"]
        frame["cross_direction_agree_1h"] = np.sign(frame["ret_1h"]) * np.sign(frame["other_ret_1h"])
        output[symbol] = frame
    return output


def topology_id(topology: Topology) -> str:
    raw = json.dumps(asdict(topology), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def generate_events(cache: DataCache, feature_frames: dict[str, pd.DataFrame], symbol: str, topology: Topology) -> pd.DataFrame:
    bars_5m = cache.get(symbol, "bars_5m")
    bars_5m = bars_5m[bars_5m["is_complete"] & bars_5m["close"].notna()].copy()
    bars_15m = feature_frames[symbol].copy().sort_values("start_time_ms")
    step = math.log1p(topology.bin_bps / 10_000)
    vwap = (bars_5m["turnover"] / bars_5m["volume"]).where((bars_5m["volume"] > 0) & np.isfinite(bars_5m["turnover"] / bars_5m["volume"]), bars_5m["close"])
    bars_5m = bars_5m.assign(profile_bin=np.floor(np.log(vwap) / step).astype("int64"), profile_day=(bars_5m["start_time_ms"] // DAY_MS).astype("int64"))
    grouped = bars_5m.groupby(["profile_day", "profile_bin"], sort=True)["turnover"].sum()
    day_contribution: dict[int, dict[int, float]] = {}
    for (day, key), value in grouped.items():
        day_contribution.setdefault(int(day), {})[int(key)] = float(value)
    bars_15m = bars_15m.assign(profile_day=(bars_15m["start_time_ms"] // DAY_MS).astype("int64"), close_profile_bin=np.floor(np.log(bars_15m["close"]) / step).astype("int64"))
    profile = defaultdict(float)
    events = []
    last_day = None
    previous = None
    high_threshold = low_threshold = None
    high_keys: list[int] = []
    for row in bars_15m.itertuples(index=False):
        day = int(row.profile_day)
        if last_day is None:
            for prior_day in range(day - topology.window_days, day):
                for key, value in day_contribution.get(prior_day, {}).items():
                    profile[key] += value
            last_day = day
        elif day != last_day:
            for completed_day in range(last_day, day):
                for key, value in day_contribution.get(completed_day, {}).items():
                    profile[key] += value
                expired_day = completed_day - topology.window_days
                for key, value in day_contribution.get(expired_day, {}).items():
                    profile[key] -= value
                    if profile[key] <= 1e-6:
                        profile.pop(key, None)
            last_day = day
        if previous is None or int(row.start_time_ms) % DAY_MS == 0:
            if len(profile) >= 20:
                keys = sorted(profile)
                densities = np.fromiter((_smooth(profile, key) for key in keys), float, count=len(keys))
                positive = densities[densities > 0]
                if len(positive) >= 20:
                    high_threshold = float(np.quantile(positive, topology.high_q))
                    low_threshold = high_threshold * topology.low_frac
                    high_keys = [key for key, density in zip(keys, densities) if density >= high_threshold]
                else:
                    high_threshold = low_threshold = None
                    high_keys = []
            else:
                high_threshold = low_threshold = None
                high_keys = []
        if previous is None:
            previous = row
            continue
        if int(row.start_time_ms) - int(previous.start_time_ms) != 900_000 or high_threshold is None or len(high_keys) < 2:
            previous = row
            continue
        current_bin = int(row.close_profile_bin)
        previous_bin = int(previous.close_profile_bin)
        current_density = _smooth(profile, current_bin)
        previous_density = _smooth(profile, previous_bin)
        if not (current_density <= low_threshold and previous_density > low_threshold):
            previous = row
            continue
        location = bisect.bisect_left(high_keys, current_bin)
        if location == 0 or location == len(high_keys):
            previous = row
            continue
        lower_key = int(high_keys[location - 1])
        upper_key = int(high_keys[location])
        width = upper_key - lower_key
        if width < topology.min_bins or width > topology.max_bins:
            previous = row
            continue
        move = 1 if current_bin > previous_bin else (-1 if current_bin < previous_bin else 0)
        if move == 0:
            previous = row
            continue
        tolerance = max(3, width // 3)
        if move > 0 and not (previous_bin <= current_bin and abs(previous_bin - lower_key) <= tolerance):
            previous = row
            continue
        if move < 0 and not (previous_bin >= current_bin and abs(previous_bin - upper_key) <= tolerance):
            previous = row
            continue
        lower = math.exp((lower_key + 1) * step)
        upper = math.exp(upper_key * step)
        if not lower < float(row.close) < upper:
            previous = row
            continue
        depth = (math.log(float(row.close)) - math.log(lower)) / (math.log(upper) - math.log(lower))
        origin = lower if move > 0 else upper
        destination = upper if move > 0 else lower
        record = {key: getattr(row, key) for key in FEATURES if hasattr(row, key)}
        record.update({
            "symbol": symbol,
            "symbol_eth": 1.0 if symbol == "ETHUSDT" else 0.0,
            "decision_ms": int(row.available_at_ms),
            "bar_start_ms": int(row.start_time_ms),
            "direction": float(move),
            "lower": lower,
            "upper": upper,
            "decision_close": float(row.close),
            "width_bins": float(width),
            "corridor_pct": upper / lower - 1,
            "cur_density_ratio": current_density / high_threshold,
            "prev_density_ratio": previous_density / high_threshold,
            "lower_density_ratio": _smooth(profile, lower_key) / high_threshold,
            "upper_density_ratio": _smooth(profile, upper_key) / high_threshold,
            "entry_depth": depth,
            "origin_distance": abs(float(row.close) / origin - 1),
            "destination_distance": abs(destination / float(row.close) - 1),
            "topology_id": topology_id(topology),
        })
        events.append(record)
        previous = row
    return pd.DataFrame(events)


@njit(cache=True)
def _range_max(tree: np.ndarray, size: int, left: int, right: int) -> float:
    result = -np.inf
    left += size
    right += size
    while left < right:
        if left & 1:
            result = max(result, tree[left])
            left += 1
        if right & 1:
            right -= 1
            result = max(result, tree[right])
        left //= 2
        right //= 2
    return result


@njit(cache=True)
def _range_min(tree: np.ndarray, size: int, left: int, right: int) -> float:
    result = np.inf
    left += size
    right += size
    while left < right:
        if left & 1:
            result = min(result, tree[left])
            left += 1
        if right & 1:
            right -= 1
            result = min(result, tree[right])
        left //= 2
        right //= 2
    return result


@njit(cache=True)
def _first_ge(tree: np.ndarray, size: int, count: int, start: int, value: float) -> int:
    if start >= count or _range_max(tree, size, start, count) < value:
        return -1
    low, high = start, count - 1
    while low < high:
        middle = (low + high) // 2
        if _range_max(tree, size, start, middle + 1) >= value:
            high = middle
        else:
            low = middle + 1
    return low


@njit(cache=True)
def _first_le(tree: np.ndarray, size: int, count: int, start: int, value: float) -> int:
    if start >= count or _range_min(tree, size, start, count) > value:
        return -1
    low, high = start, count - 1
    while low < high:
        middle = (low + high) // 2
        if _range_min(tree, size, start, middle + 1) <= value:
            high = middle
        else:
            low = middle + 1
    return low


@njit(cache=True)
def first_passage_tree(max_tree: np.ndarray, min_tree: np.ndarray, size: int, count: int, starts: np.ndarray, uppers: np.ndarray, lowers: np.ndarray):
    up_index = np.full(len(starts), -1, np.int64)
    down_index = np.full(len(starts), -1, np.int64)
    ambiguous = np.zeros(len(starts), np.int8)
    for index in range(len(starts)):
        start = starts[index]
        if start < 0 or start >= count:
            continue
        upper = _first_ge(max_tree, size, count, start, uppers[index])
        lower = _first_le(min_tree, size, count, start, lowers[index])
        up_index[index] = upper
        down_index[index] = lower
        if upper >= 0 and lower >= 0 and upper == lower:
            ambiguous[index] = 1
    return up_index, down_index, ambiguous


def get_passage_tree(cache: DataCache, symbol: str, bars: pd.DataFrame):
    if symbol in cache.passage_trees:
        return cache.passage_trees[symbol]
    high = np.nan_to_num(bars["high"].to_numpy(float), nan=-np.inf)
    low = np.nan_to_num(bars["low"].to_numpy(float), nan=np.inf)
    count = len(high)
    size = 1
    while size < count:
        size *= 2
    max_tree = np.full(2 * size, -np.inf, dtype=np.float64)
    min_tree = np.full(2 * size, np.inf, dtype=np.float64)
    max_tree[size:size + count] = high
    min_tree[size:size + count] = low
    for index in range(size - 1, 0, -1):
        max_tree[index] = max(max_tree[index * 2], max_tree[index * 2 + 1])
        min_tree[index] = min(min_tree[index * 2], min_tree[index * 2 + 1])
    cache.passage_trees[symbol] = (max_tree, min_tree, size, count)
    return cache.passage_trees[symbol]


def label_events(cache: DataCache, symbol: str, events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events
    bars = cache.get(symbol, "bars_1m").copy().sort_values("start_time_ms").reset_index(drop=True)
    times = bars["start_time_ms"].to_numpy(np.int64)
    opens = bars["open"].to_numpy(float)
    activation = events["decision_ms"].to_numpy(np.int64) + 500
    starts = np.searchsorted(times, activation, side="left").astype(np.int64)
    valid = starts < len(times)
    entry = np.full(len(events), np.nan)
    entry[valid] = opens[starts[valid]]
    valid &= np.isfinite(entry) & (entry > events["lower"].to_numpy(float)) & (entry < events["upper"].to_numpy(float))
    safe_starts = starts.copy()
    safe_starts[~valid] = len(times) - 1
    max_tree, min_tree, tree_size, count = get_passage_tree(cache, symbol, bars)
    upper_hit, lower_hit, ambiguous = first_passage_tree(max_tree, min_tree, tree_size, count, safe_starts, events["upper"].to_numpy(float), events["lower"].to_numpy(float))
    upper_hit[~valid] = -1
    lower_hit[~valid] = -1
    ambiguous[~valid] = 0
    resolved = (upper_hit >= 0) | (lower_hit >= 0)
    exit_index = np.where((upper_hit >= 0) & ((lower_hit < 0) | (upper_hit < lower_hit)), upper_hit, lower_hit)
    exit_index = np.where(resolved, exit_index, -1)
    upper_first = (upper_hit >= 0) & ((lower_hit < 0) | (upper_hit < lower_hit))
    exit_ms = np.where(resolved, times[np.maximum(exit_index, 0)], -1)
    output = events.copy()
    output["activation_ms"] = activation
    output["entry_index"] = starts
    output["entry_ms"] = np.where(valid, times[np.minimum(starts, len(times) - 1)], -1)
    output["entry_price"] = entry
    output["upper_hit_index"] = upper_hit
    output["lower_hit_index"] = lower_hit
    output["ambiguous"] = ambiguous.astype(bool)
    output["resolved"] = resolved & valid
    output["upper_first"] = upper_first.astype(float)
    output.loc[~output["resolved"], "upper_first"] = np.nan
    output["exit_index"] = exit_index
    output["exit_ms"] = exit_ms
    output["duration_hours"] = np.where(output["resolved"], (output["exit_ms"] - output["entry_ms"]) / 3_600_000, np.nan)
    funding = cache.get(symbol, "funding_events").sort_values("timestamp_ms")
    funding_times = funding["timestamp_ms"].to_numpy(np.int64)
    funding_rates = funding["funding_rate"].to_numpy(float)
    cumulative = np.r_[0.0, np.cumsum(funding_rates)]
    left = np.searchsorted(funding_times, output["entry_ms"].to_numpy(np.int64), side="right")
    right_values = np.where(output["resolved"].to_numpy(bool), output["exit_ms"].to_numpy(np.int64), -1).astype(np.int64)
    right = np.searchsorted(funding_times, right_values, side="right")
    output["funding_sum"] = np.where(output["resolved"], cumulative[right] - cumulative[left], np.nan)
    return output


def action_returns(frame: pd.DataFrame, cost: float = .0024) -> pd.DataFrame:
    output = frame.copy()
    upper_first = output["upper_first"].eq(1)
    continuation_side = output["direction"].astype(int)
    reversal_side = -continuation_side
    nonambiguous_exit = np.where(upper_first, output["upper"], output["lower"])
    continuation_stop = np.where(continuation_side > 0, output["lower"], output["upper"])
    reversal_stop = np.where(reversal_side > 0, output["lower"], output["upper"])
    continuation_exit = np.where(output["ambiguous"], continuation_stop, nonambiguous_exit)
    reversal_exit = np.where(output["ambiguous"], reversal_stop, nonambiguous_exit)
    output["continuation_side"] = continuation_side
    output["reversal_side"] = reversal_side
    output["continuation_exit"] = continuation_exit
    output["reversal_exit"] = reversal_exit
    output["continuation_return"] = continuation_side * (continuation_exit / output["entry_price"] - 1) - cost - continuation_side * output["funding_sum"].fillna(0)
    output["reversal_return"] = reversal_side * (reversal_exit / output["entry_price"] - 1) - cost - reversal_side * output["funding_sum"].fillna(0)
    output["continuation_stop"] = continuation_stop
    output["reversal_stop"] = reversal_stop
    return output


def model_pipeline(kind: str, parameter: float):
    if kind == "logit":
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", LogisticRegression(C=parameter, max_iter=2000, random_state=7))])
    if kind == "hgb":
        return Pipeline([("impute", SimpleImputer(strategy="median")), ("model", HistGradientBoostingClassifier(max_iter=250, learning_rate=.05, max_leaf_nodes=int(parameter), min_samples_leaf=30, l2_regularization=2.0, random_state=7))])
    raise ValueError(kind)


def expected_actions(frame: pd.DataFrame, upper_probability: np.ndarray, cost: float = .0024) -> pd.DataFrame:
    output = frame.copy()
    entry = output["entry_price"].to_numpy(float)
    upper = output["upper"].to_numpy(float)
    lower = output["lower"].to_numpy(float)
    long_ev = upper_probability * (upper / entry - 1) + (1 - upper_probability) * (lower / entry - 1) - cost
    short_ev = -upper_probability * (upper / entry - 1) - (1 - upper_probability) * (lower / entry - 1) - cost
    continuation_side = output["direction"].to_numpy(int)
    continuation_ev = np.where(continuation_side > 0, long_ev, short_ev)
    reversal_ev = np.where(continuation_side > 0, short_ev, long_ev)
    output["p_upper"] = upper_probability
    output["continuation_ev"] = continuation_ev
    output["reversal_ev"] = reversal_ev
    output["best_action"] = np.where(continuation_ev >= reversal_ev, "continuation", "reversal")
    output["best_ev"] = np.maximum(continuation_ev, reversal_ev)
    return output


def simulate_closed(events: pd.DataFrame, threshold: float, risk: float = .005, leverage: float = 3.0, cost: float = .0024, start_nav: float = 10_000.0):
    candidates = events[events["resolved"]].sort_values(["entry_ms", "best_ev", "symbol"], ascending=[True, False, True]).copy()
    if candidates.empty:
        return {"end_nav": start_nav, "return": 0.0, "trades": 0, "pf": 0.0, "mdd_closed": 0.0, "median_trade_bps": np.nan, "ledger": pd.DataFrame()}
    entry_ms = candidates["entry_ms"].to_numpy(np.int64)
    exit_ms = candidates["exit_ms"].to_numpy(np.int64)
    best_ev = candidates["best_ev"].to_numpy(float)
    actions = candidates["best_action"].to_numpy(object)
    symbols = candidates["symbol"].to_numpy(object)
    entry_price = candidates["entry_price"].to_numpy(float)
    continuation_side = candidates["continuation_side"].to_numpy(int)
    reversal_side = candidates["reversal_side"].to_numpy(int)
    continuation_stop = candidates["continuation_stop"].to_numpy(float)
    reversal_stop = candidates["reversal_stop"].to_numpy(float)
    continuation_return = candidates["continuation_return"].to_numpy(float)
    reversal_return = candidates["reversal_return"].to_numpy(float)
    continuation_exit = candidates["continuation_exit"].to_numpy(float)
    reversal_exit = candidates["reversal_exit"].to_numpy(float)
    duration = candidates["duration_hours"].to_numpy(float)
    ambiguous = candidates["ambiguous"].to_numpy(bool)
    nav = start_nav
    free_at = -1
    trades = []
    index = 0
    while index < len(candidates):
        timestamp = int(entry_ms[index])
        next_index = index + 1
        while next_index < len(candidates) and entry_ms[next_index] == timestamp:
            next_index += 1
        if timestamp >= free_at and best_ev[index] >= threshold:
            selected = index
            is_continuation = actions[selected] == "continuation"
            side = int(continuation_side[selected] if is_continuation else reversal_side[selected])
            stop = float(continuation_stop[selected] if is_continuation else reversal_stop[selected])
            realised_return = float(continuation_return[selected] if is_continuation else reversal_return[selected])
            exit_price = float(continuation_exit[selected] if is_continuation else reversal_exit[selected])
            stop_loss = abs(stop / entry_price[selected] - 1) + cost
            if stop_loss > 0 and np.isfinite(stop_loss):
                notional = min(nav * risk / stop_loss, nav * leverage)
                pnl = notional * realised_return
                new_nav = nav + pnl
                trades.append((timestamp, int(exit_ms[selected]), symbols[selected], actions[selected], side, entry_price[selected], exit_price, realised_return, notional, pnl, nav, new_nav, best_ev[selected], duration[selected], ambiguous[selected]))
                nav = new_nav
                free_at = int(exit_ms[selected])
                if nav <= 0:
                    break
        index = next_index
    columns = ["entry_ms", "exit_ms", "symbol", "action", "side", "entry_price", "exit_price", "return_on_notional", "notional", "pnl", "nav_before", "nav_after", "best_ev", "duration_hours", "ambiguous"]
    ledger = pd.DataFrame(trades, columns=columns)
    if ledger.empty:
        return {"end_nav": nav, "return": nav / start_nav - 1, "trades": 0, "pf": 0.0, "mdd_closed": 0.0, "median_trade_bps": np.nan, "ledger": ledger}
    curve = np.r_[start_nav, ledger["nav_after"].to_numpy(float)]
    peak = np.maximum.accumulate(curve)
    drawdown = float(np.max(1 - curve / peak))
    gross_profit = ledger.loc[ledger.pnl > 0, "pnl"].sum()
    gross_loss = -ledger.loc[ledger.pnl < 0, "pnl"].sum()
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else math.inf
    return {"end_nav": nav, "return": nav / start_nav - 1, "trades": len(ledger), "pf": profit_factor, "mdd_closed": drawdown, "median_trade_bps": float(np.median(ledger["return_on_notional"]) * 1e4), "ledger": ledger}


def development_run(output: Path) -> dict:
    """Reproduce the frozen pre-2024 screen and stop before calendar 2023."""
    output.mkdir(parents=True, exist_ok=True)
    verification = verify_export()
    (output / "source_verification.json").write_text(json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    cache = DataCache()
    frames = prepare_feature_frames(cache)
    configs = [
        Topology(10, 7, .55, .35), Topology(10, 7, .55, .50),
        Topology(10, 7, .65, .35), Topology(10, 7, .65, .50),
        Topology(10, 14, .55, .35), Topology(10, 14, .55, .50),
        Topology(20, 7, .55, .35), Topology(20, 7, .55, .50),
    ]
    rows = []
    for topology in configs:
        parts = []
        for symbol in ("BTCUSDT", "ETHUSDT"):
            events = generate_events(cache, frames, symbol, topology)
            parts.append(action_returns(label_events(cache, symbol, events), .0024))
        data = pd.concat(parts, ignore_index=True).sort_values(["decision_ms", "symbol"])
        identifier = topology_id(topology)
        decision_time = pd.to_datetime(data["decision_ms"], unit="ms", utc=True)
        train = data[(decision_time < "2022-01-01") & data["resolved"] & ~data["ambiguous"]].copy()
        validation = data[(decision_time >= "2022-01-01") & (decision_time < "2023-01-01") & data["resolved"]].copy()
        if len(train) < 100 or len(validation) < 40 or train["upper_first"].nunique() < 2:
            continue
        for c_value in (.1, 1.0, 10.0):
            model = model_pipeline("logit", c_value)
            model.fit(train[FEATURES], train["upper_first"].astype(int))
            probability = model.predict_proba(validation[FEATURES])[:, 1]
            scored = expected_actions(validation, probability, .0024)
            entry = scored["entry_price"].to_numpy(float)
            scored["continuation_ev_r"] = scored["continuation_ev"] / (np.abs(scored["continuation_stop"] / entry - 1) + .0024)
            scored["reversal_ev_r"] = scored["reversal_ev"] / (np.abs(scored["reversal_stop"] / entry - 1) + .0024)
            scored["best_action"] = np.where(scored["continuation_ev_r"] >= scored["reversal_ev_r"], "continuation", "reversal")
            scored["best_ev"] = np.maximum(scored["continuation_ev_r"], scored["reversal_ev_r"])
            unambiguous = ~validation["ambiguous"]
            auc = roc_auc_score(validation.loc[unambiguous, "upper_first"].astype(int), probability[unambiguous])
            brier = brier_score_loss(validation.loc[unambiguous, "upper_first"].astype(int), probability[unambiguous])
            for threshold_r in (0, .02, .05, .10, .20, .30, .50, .75, 1.0, 1.5):
                simulation = simulate_closed(scored, threshold_r, risk=.005, leverage=3.0, cost=.0024)
                rows.append({**asdict(topology), "topology_id": identifier, "model": "logit", "param": c_value, "threshold_r": threshold_r, "train_n": len(train), "valid_n": len(validation), "auc": auc, "brier": brier, "end_nav": simulation["end_nav"], "trades": simulation["trades"], "pf": simulation["pf"], "mdd": simulation["mdd_closed"], "median_bps": simulation["median_trade_bps"]})
    grid = pd.DataFrame(rows)
    grid.to_csv(output / "development_grid.csv", index=False)
    broad = grid[(grid["trades"] >= 80) & (grid["end_nav"] > 10_000)]
    decision = {"status": "NO_BREADTH_PRESERVING_2022_SURVIVOR" if broad.empty else "SURVIVOR", "tested_rows": int(len(grid)), "official_period_opened": False}
    (output / "development_decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return decision


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(development_run(arguments.output_dir), indent=2, sort_keys=True))
