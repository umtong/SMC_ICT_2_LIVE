#!/usr/bin/env python3
"""Causal pre-2024 action-value evaluation for dense prior-day edge microflow.

The script deliberately keeps the event source, action geometry, execution,
model, threshold, sizing and chronology fixed.  It reports raw CONTINUE and
REJECT economics, then a single HGBT direct-account-value policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

COSTS_BP = (12.0, 18.0, 24.0)
RISK = 0.005
CAP = 3.0
FIT_END = pd.Timestamp("2023-05-01T00:00:00Z")
REFIT_END = pd.Timestamp("2023-09-01T00:00:00Z")
END = pd.Timestamp("2024-01-01T00:00:00Z")


def clean_json(x):
    if isinstance(x, dict):
        return {str(k): clean_json(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean_json(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(float(x)) else float(x)
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ts_from_any(s: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, utc=True)
    n = pd.to_numeric(s, errors="coerce")
    finite = n[np.isfinite(n)]
    if len(finite):
        med = float(np.nanmedian(np.abs(finite)))
        unit = "ns" if med >= 1e17 else "us" if med >= 1e14 else "ms" if med >= 1e11 else "s"
        return pd.to_datetime(n, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(s, utc=True, errors="coerce")


def find_col(cols: Iterable[str], exact: Iterable[str], contains: Iterable[str] = ()) -> str | None:
    lookup = {str(c).strip().lower(): str(c) for c in cols}
    for x in exact:
        if x in lookup:
            return lookup[x]
    for low, original in lookup.items():
        if any(x in low for x in contains):
            return original
    return None


def classify_parquet(path: Path) -> str | None:
    n = path.as_posix().lower()
    if "fund" in n:
        return "funding"
    if "open_interest" in n or "/oi" in n or "_oi_" in n or n.endswith("oi.parquet"):
        return "oi"
    if "account" in n and "ratio" in n:
        return "account"
    if ("trade" in n or "kline" in n) and ("1m" in n or "minute" in n) and not any(x in n for x in ["mark", "index", "premium"]):
        return "price"
    return None


def read_kind(root: Path, kind: str) -> pd.DataFrame:
    candidates = [p for p in root.rglob("*.parquet") if classify_parquet(p) == kind]
    if not candidates:
        # Fallback schema inspection for nonstandard internal names.
        for p in root.rglob("*.parquet"):
            try:
                cols = [str(c).lower() for c in pd.read_parquet(p).columns]
            except Exception:
                continue
            if kind == "price" and {"open", "high", "low", "close"}.issubset(cols) and len(cols) >= 5:
                if not any(x in p.name.lower() for x in ["mark", "index", "premium"]):
                    candidates.append(p)
            elif kind == "oi" and any("open_interest" in c for c in cols):
                candidates.append(p)
            elif kind == "account" and any("buy_ratio" in c for c in cols) and any("sell_ratio" in c for c in cols):
                candidates.append(p)
            elif kind == "funding" and any("funding" in c and "rate" in c for c in cols):
                candidates.append(p)
    if not candidates:
        return pd.DataFrame()
    frames = [pd.read_parquet(p) for p in sorted(set(candidates))]
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def normalize_price(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        raise RuntimeError("canonical trade 1m table not found")
    tscol = find_col(df.columns, ["start_ms", "start", "open_time", "timestamp", "ts", "time"], ["start", "open_time", "timestamp"])
    if tscol is None:
        raise RuntimeError(f"price timestamp missing: {list(df.columns)}")
    ren = {}
    for k, opts in {
        "open": ["open", "open_price"],
        "high": ["high", "high_price"],
        "low": ["low", "low_price"],
        "close": ["close", "close_price"],
        "turnover": ["turnover", "quote_volume", "volume_quote"],
        "volume": ["volume", "base_volume"],
    }.items():
        c = find_col(df.columns, opts, opts)
        if c is not None:
            ren[c] = k
    out = df.rename(columns=ren).copy()
    out["ts"] = ts_from_any(out[tscol])
    required = ["open", "high", "low", "close"]
    if not set(required).issubset(out.columns):
        raise RuntimeError(f"price OHLC missing: {list(out.columns)}")
    for c in required + [c for c in ["turnover", "volume"] if c in out.columns]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    if "turnover" not in out:
        out["turnover"] = out.get("volume", 0.0) * out["close"]
    out = out.dropna(subset=["ts", *required]).sort_values("ts").drop_duplicates("ts", keep="last")
    out = out[(out["open"] > 0) & (out["high"] > 0) & (out["low"] > 0) & (out["close"] > 0)]
    return out[["ts", "open", "high", "low", "close", "turnover"]].reset_index(drop=True)


def normalize_oi(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["available_ts", "oi"])
    t = find_col(df.columns, ["available_at_ms", "available_ts", "timestamp", "start_ms", "start", "ts"], ["available", "timestamp", "start"])
    v = find_col(df.columns, ["open_interest", "oi", "sum_open_interest", "value"], ["open_interest"])
    if t is None or v is None:
        return pd.DataFrame(columns=["available_ts", "oi"])
    out = pd.DataFrame({"available_ts": ts_from_any(df[t]), "oi": pd.to_numeric(df[v], errors="coerce")})
    if "available" not in t.lower() and ("start" in t.lower()):
        out["available_ts"] += pd.Timedelta(minutes=5)
    return out.dropna().sort_values("available_ts").drop_duplicates("available_ts", keep="last")


def normalize_account(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["available_ts", "account_imbalance"])
    t = find_col(df.columns, ["available_at_ms", "available_ts", "timestamp", "start_ms", "start", "ts"], ["available", "timestamp", "start"])
    b = find_col(df.columns, ["buy_ratio", "long_account", "buyratio"], ["buy_ratio", "long_account"])
    s = find_col(df.columns, ["sell_ratio", "short_account", "sellratio"], ["sell_ratio", "short_account"])
    if t is None or b is None or s is None:
        return pd.DataFrame(columns=["available_ts", "account_imbalance"])
    out = pd.DataFrame(
        {
            "available_ts": ts_from_any(df[t]),
            "account_imbalance": pd.to_numeric(df[b], errors="coerce") - pd.to_numeric(df[s], errors="coerce"),
        }
    )
    if "available" not in t.lower() and ("start" in t.lower()):
        out["available_ts"] += pd.Timedelta(minutes=5)
    return out.dropna().sort_values("available_ts").drop_duplicates("available_ts", keep="last")


def normalize_funding(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["ts", "funding_rate"])
    t = find_col(df.columns, ["funding_time", "timestamp", "time", "ts", "calc_time"], ["funding_time", "timestamp", "calc_time"])
    r = find_col(df.columns, ["funding_rate", "rate"], ["funding_rate"])
    if t is None or r is None:
        return pd.DataFrame(columns=["ts", "funding_rate"])
    out = pd.DataFrame({"ts": ts_from_any(df[t]), "funding_rate": pd.to_numeric(df[r], errors="coerce")})
    return out.dropna().sort_values("ts").drop_duplicates("ts", keep="last")


@dataclass
class SymbolData:
    symbol: str
    price: pd.DataFrame
    oi: pd.DataFrame
    account: pd.DataFrame
    funding: pd.DataFrame
    minute_ns: np.ndarray
    open_: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    turnover: np.ndarray
    five_ts: pd.DatetimeIndex
    five_close: np.ndarray
    four_pools: pd.DataFrame


class RangeTree:
    def __init__(self, values: np.ndarray, mode: str):
        self.n = 1
        while self.n < len(values):
            self.n *= 2
        neutral = -np.inf if mode == "max" else np.inf
        self.mode = mode
        self.tree = np.full(2 * self.n, neutral, dtype=float)
        self.tree[self.n : self.n + len(values)] = values
        for i in range(self.n - 1, 0, -1):
            self.tree[i] = max(self.tree[2 * i], self.tree[2 * i + 1]) if mode == "max" else min(self.tree[2 * i], self.tree[2 * i + 1])

    def first(self, left: int, threshold: float, relation: str) -> int:
        def ok(v: float) -> bool:
            return v >= threshold if relation == "ge" else v <= threshold

        neutral_fail = (lambda v: v < threshold) if relation == "ge" else (lambda v: v > threshold)

        def rec(node: int, lo: int, hi: int) -> int:
            if hi <= left or neutral_fail(self.tree[node]):
                return -1
            if hi - lo == 1:
                return lo
            mid = (lo + hi) // 2
            x = rec(node * 2, lo, mid)
            return x if x >= 0 else rec(node * 2 + 1, mid, hi)

        return rec(1, 0, self.n)


def build_pools(price: pd.DataFrame) -> pd.DataFrame:
    q = price.set_index("ts")[["open", "high", "low", "close"]]
    bars = q.resample("4h", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    rows = []
    h = bars["high"].to_numpy()
    l = bars["low"].to_numpy()
    idx = bars.index
    for i in range(2, len(bars) - 2):
        available = idx[i + 2] + pd.Timedelta(hours=4)
        if h[i] > max(h[i - 2], h[i - 1], h[i + 1], h[i + 2]):
            rows.append({"kind": 1, "price": float(h[i]), "pivot_ts": idx[i], "available_ts": available})
        if l[i] < min(l[i - 2], l[i - 1], l[i + 1], l[i + 2]):
            rows.append({"kind": -1, "price": float(l[i]), "pivot_ts": idx[i], "available_ts": available})
    return pd.DataFrame(rows).sort_values("available_ts").reset_index(drop=True)


def load_symbol(root: Path, symbol: str) -> SymbolData:
    r = root / symbol
    price = normalize_price(read_kind(r, "price"))
    oi = normalize_oi(read_kind(r, "oi"))
    account = normalize_account(read_kind(r, "account"))
    funding = normalize_funding(read_kind(r, "funding"))
    p5 = price.set_index("ts")["close"].resample("5min", label="right", closed="left").last().dropna()
    return SymbolData(
        symbol=symbol,
        price=price,
        oi=oi,
        account=account,
        funding=funding,
        minute_ns=price["ts"].astype("int64").to_numpy(),
        open_=price["open"].to_numpy(float),
        high=price["high"].to_numpy(float),
        low=price["low"].to_numpy(float),
        close=price["close"].to_numpy(float),
        turnover=price["turnover"].to_numpy(float),
        five_ts=p5.index,
        five_close=p5.to_numpy(float),
        four_pools=build_pools(price),
    )


def asof_value(df: pd.DataFrame, ts: pd.Timestamp, col: str) -> float:
    if df.empty:
        return math.nan
    arr = df["available_ts"].astype("int64").to_numpy()
    i = int(np.searchsorted(arr, ts.value, side="right") - 1)
    return float(df.iloc[i][col]) if i >= 0 else math.nan


def price_before(sd: SymbolData, ts: pd.Timestamp, minutes: int = 0) -> float:
    x = ts - pd.Timedelta(minutes=minutes)
    i = int(np.searchsorted(sd.minute_ns, x.value, side="left") - 1)
    return float(sd.close[i]) if i >= 0 else math.nan


def canonical_features(sd: SymbolData, peer: SymbolData, ts: pd.Timestamp) -> dict[str, float]:
    now = price_before(sd, ts)
    def ret(m):
        p = price_before(sd, ts, m)
        return math.log(now / p) if np.isfinite(now) and np.isfinite(p) and p > 0 else math.nan
    peer_now = price_before(peer, ts)
    peer_60 = price_before(peer, ts, 60)
    oi0 = asof_value(sd.oi, ts, "oi")
    oi1 = asof_value(sd.oi, ts - pd.Timedelta(hours=1), "oi")
    ac0 = asof_value(sd.account, ts, "account_imbalance")
    ac1 = asof_value(sd.account, ts - pd.Timedelta(hours=1), "account_imbalance")
    poi0 = asof_value(peer.oi, ts, "oi")
    poi1 = asof_value(peer.oi, ts - pd.Timedelta(hours=1), "oi")
    pac0 = asof_value(peer.account, ts, "account_imbalance")
    pac1 = asof_value(peer.account, ts - pd.Timedelta(hours=1), "account_imbalance")
    i = int(np.searchsorted(sd.minute_ns, ts.value, side="left"))
    lo = max(0, i - 168 * 60)
    hist = np.log1p(np.maximum(sd.turnover[lo:i], 0.0))
    cur = math.log1p(max(float(np.nansum(sd.turnover[max(0, i - 60):i])), 0.0))
    hz = (cur - float(np.nanmean(hist))) / max(float(np.nanstd(hist)), 1e-9) if len(hist) >= 60 else math.nan
    path = np.diff(np.log(sd.close[max(0, i - 60):i])) if i - max(0, i - 60) > 1 else np.array([])
    eff = abs(ret(60)) / max(float(np.nansum(np.abs(path))), 1e-9) if len(path) else math.nan
    return {
        "ret_1h": ret(60), "ret_6h": ret(360), "ret_24h": ret(1440), "path_eff_1h": eff,
        "turnover_state_z": hz,
        "oi_change_1h": oi0 / oi1 - 1 if np.isfinite(oi0) and np.isfinite(oi1) and oi1 > 0 else math.nan,
        "account_imbalance": ac0,
        "account_change_1h": ac0 - ac1 if np.isfinite(ac0) and np.isfinite(ac1) else math.nan,
        "peer_ret_1h": math.log(peer_now / peer_60) if np.isfinite(peer_now) and np.isfinite(peer_60) and peer_60 > 0 else math.nan,
        "peer_oi_change_1h": poi0 / poi1 - 1 if np.isfinite(poi0) and np.isfinite(poi1) and poi1 > 0 else math.nan,
        "peer_account_imbalance": pac0,
        "peer_account_change_1h": pac0 - pac1 if np.isfinite(pac0) and np.isfinite(pac1) else math.nan,
        "hour_sin": math.sin(2 * math.pi * ts.hour / 24), "hour_cos": math.cos(2 * math.pi * ts.hour / 24),
    }


def pool_consumed(sd: SymbolData) -> pd.DataFrame:
    pools = sd.four_pools.copy()
    if pools.empty:
        pools["consumed_ts"] = pd.NaT
        return pools
    max_tree = RangeTree(sd.high, "max")
    min_tree = RangeTree(sd.low, "min")
    out = []
    for r in pools.itertuples(index=False):
        start = int(np.searchsorted(sd.minute_ns, pd.Timestamp(r.available_ts).value, side="left"))
        j = max_tree.first(start, float(r.price), "ge") if int(r.kind) > 0 else min_tree.first(start, float(r.price), "le")
        out.append(pd.Timestamp(sd.price.iloc[j]["ts"]) if 0 <= j < len(sd.price) else pd.NaT)
    pools["consumed_ts"] = out
    return pools


def choose_target(pools: pd.DataFrame, side: int, level: float, decision: pd.Timestamp, entry: pd.Timestamp) -> float:
    if pools.empty:
        return math.nan
    p = pools[(pools["kind"] == side) & (pools["available_ts"] <= decision)]
    p = p[(p["consumed_ts"].isna()) | (p["consumed_ts"] > entry)]
    p = p[p["price"] > level] if side > 0 else p[p["price"] < level]
    if p.empty:
        return math.nan
    return float(p["price"].min() if side > 0 else p["price"].max())


def first_state_index(sd: SymbolData, start_ts: pd.Timestamp, threshold: float, relation: str) -> int:
    arr_ts = sd.five_ts.astype("int64").to_numpy()
    start = int(np.searchsorted(arr_ts, start_ts.value, side="right"))
    vals = sd.five_close[start:]
    mask = vals < threshold if relation == "lt" else vals > threshold
    hit = np.flatnonzero(mask)
    if not len(hit):
        return -1
    decision = pd.Timestamp(sd.five_ts[start + int(hit[0])])
    execution = decision + pd.Timedelta(milliseconds=500)
    return int(np.searchsorted(sd.minute_ns, execution.value, side="right"))


def funding_sum(sd: SymbolData, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if sd.funding.empty:
        return 0.0
    x = sd.funding[(sd.funding["ts"] > start) & (sd.funding["ts"] <= end)]
    return float(x["funding_rate"].sum())


def resolve_action(event: pd.Series, action: str, sd: SymbolData, pools: pd.DataFrame) -> dict | None:
    entry_ts = pd.Timestamp(event["entry_ts"])
    decision = pd.Timestamp(event["decision_ts"])
    entry = float(event["entry_price"])
    level_side = int(event["level_side"])
    level = float(event["level"])
    atr = float(event["atr15m20"])
    if not np.isfinite(entry) or not np.isfinite(atr) or atr <= 0:
        return None
    if action == "CONTINUE":
        direction = level_side
        target = choose_target(pools, direction, level, decision, entry_ts)
        stop = level - direction * 0.25 * atr
        state_level = level
        relation = "lt" if direction > 0 else "gt"
    else:
        direction = -level_side
        target = float(event["prior_day_mid"])
        extreme = float(event["sensor_high"] if level_side > 0 else event["sensor_low"])
        stop = extreme + level_side * 0.25 * atr
        state_level = extreme
        relation = "gt" if level_side > 0 else "lt"
    if not np.isfinite(target) or direction * (target - entry) <= 0 or direction * (entry - stop) <= 0:
        return None
    # Exact post-entry portion of the containing minute.
    ph = float(event["post_entry_minute_high"]); pl = float(event["post_entry_minute_low"])
    stop_touch = pl <= stop if direction > 0 else ph >= stop
    target_touch = ph >= target if direction > 0 else pl <= target
    exit_ts = pd.NaT; exit_px = math.nan; reason = "UNRESOLVED"
    if stop_touch:
        exit_ts, exit_px, reason = pd.Timestamp(event["post_entry_minute_last_ts"]), stop, "STOP"
    elif target_touch:
        exit_ts, exit_px, reason = pd.Timestamp(event["post_entry_minute_last_ts"]), target, "TARGET"
    else:
        start_min = entry_ts.floor("min") + pd.Timedelta(minutes=1)
        start = int(np.searchsorted(sd.minute_ns, start_min.value, side="left"))
        if start < len(sd.price):
            hi_tree = RangeTree(sd.high, "max"); lo_tree = RangeTree(sd.low, "min")
            stop_i = lo_tree.first(start, stop, "le") if direction > 0 else hi_tree.first(start, stop, "ge")
            target_i = hi_tree.first(start, target, "ge") if direction > 0 else lo_tree.first(start, target, "le")
            state_i = first_state_index(sd, entry_ts, state_level, relation)
            choices = [(i, r) for i, r in [(stop_i, "STOP"), (target_i, "TARGET"), (state_i, "STATE")] if i >= 0 and i < len(sd.price)]
            if choices:
                i0 = min(i for i, _ in choices)
                same = {r for i, r in choices if i == i0}
                if "STOP" in same:
                    reason = "STOP"
                    o = float(sd.open_[i0]); exit_px = o if (o <= stop if direction > 0 else o >= stop) else stop
                elif "TARGET" in same:
                    reason, exit_px = "TARGET", target
                else:
                    reason, exit_px = "STATE", float(sd.open_[i0])
                    if direction > 0 and exit_px <= stop:
                        reason = "STOP_GAP"
                    elif direction < 0 and exit_px >= stop:
                        reason = "STOP_GAP"
                exit_ts = pd.Timestamp(sd.price.iloc[i0]["ts"])
    result = {
        "event_id": event["event_id"], "symbol": event["symbol"], "action": action,
        "direction": direction, "decision_ts": decision, "entry_ts": entry_ts, "entry": entry,
        "stop": stop, "target": target, "exit_ts": exit_ts, "exit": exit_px, "exit_reason": reason,
    }
    if pd.notna(exit_ts):
        fsum = funding_sum(sd, entry_ts, exit_ts)
        gross = direction * (exit_px / entry - 1.0)
        result["funding_sum"] = fsum
        for bp in COSTS_BP:
            c = bp / 10000.0
            lev = min(CAP, RISK / max(abs(entry - stop) / entry + c, 1e-12))
            result[f"leverage_{int(bp)}"] = lev
            result[f"notional_ret_{int(bp)}"] = gross - c - direction * fsum
            result[f"account_ret_{int(bp)}"] = lev * result[f"notional_ret_{int(bp)}"]
    else:
        result["funding_sum"] = math.nan
        for bp in COSTS_BP:
            result[f"leverage_{int(bp)}"] = min(CAP, RISK / max(abs(entry - stop) / entry + bp / 10000.0, 1e-12))
            result[f"notional_ret_{int(bp)}"] = math.nan
            result[f"account_ret_{int(bp)}"] = math.nan
    return result


def mark_return(row: pd.Series, sd: SymbolData, boundary: pd.Timestamp, bp: float) -> float:
    if pd.notna(row["exit_ts"]) and pd.Timestamp(row["exit_ts"]) <= boundary:
        return float(row[f"account_ret_{int(bp)}"])
    px = price_before(sd, boundary)
    if not np.isfinite(px):
        return 0.0
    direction = int(row["direction"]); entry = float(row["entry"])
    fsum = funding_sum(sd, pd.Timestamp(row["entry_ts"]), boundary)
    net = direction * (px / entry - 1.0) - bp / 10000.0 - direction * fsum
    return float(row[f"leverage_{int(bp)}"] * net)


def fit_model(actions: pd.DataFrame, feature_cols: list[str], boundary: pd.Timestamp) -> HistGradientBoostingRegressor:
    train = actions[pd.notna(actions["exit_ts"]) & (actions["exit_ts"] < boundary)].copy()
    if len(train) < 200:
        raise RuntimeError(f"insufficient resolved training actions before {boundary}: {len(train)}")
    counts = train.groupby("event_id")["event_id"].transform("count")
    model = HistGradientBoostingRegressor(
        loss="squared_error", learning_rate=0.035, max_iter=250, max_leaf_nodes=15,
        max_depth=4, min_samples_leaf=40, l2_regularization=5.0, random_state=20260730,
    )
    model.fit(train[feature_cols], train["account_ret_24"], sample_weight=1.0 / counts)
    return model


def score_stage(actions: pd.DataFrame, model, feature_cols: list[str], start: pd.Timestamp, end: pd.Timestamp, tag: str) -> pd.DataFrame:
    x = actions[(actions["decision_ts"] >= start) & (actions["decision_ts"] < end)].copy()
    if x.empty:
        return x
    x["prediction"] = model.predict(x[feature_cols])
    x["model_tag"] = tag
    x = x.sort_values(["event_id", "prediction", "action"], ascending=[True, False, True])
    x = x.groupby("event_id", as_index=False).head(1)
    return x[x["prediction"] > 0].sort_values(["entry_ts", "prediction"], ascending=[True, False])


def route(selected: pd.DataFrame, symbol_data: dict[str, SymbolData], bp: float, remove: set[str] | None = None) -> tuple[pd.DataFrame, dict[pd.Timestamp, float]]:
    remove = remove or set()
    nav = 1.0; slot_end = pd.Timestamp.min.tz_localize("UTC")
    rows = []; marks: dict[pd.Timestamp, float] = {}
    boundaries = [pd.Timestamp(x) for x in ["2023-05-01T00:00Z", "2023-07-01T00:00Z", "2023-09-01T00:00Z", "2023-11-01T00:00Z", "2024-01-01T00:00Z"]]
    pending_boundaries = list(boundaries)
    for r in selected.sort_values(["entry_ts", "prediction"], ascending=[True, False]).itertuples(index=False):
        if r.event_id in remove or pd.Timestamp(r.entry_ts) <= slot_end:
            continue
        row = selected.loc[selected["event_id"].eq(r.event_id) & selected["action"].eq(r.action)].iloc[0]
        entry_ts = pd.Timestamp(row["entry_ts"])
        while pending_boundaries and pending_boundaries[0] <= entry_ts:
            b = pending_boundaries.pop(0); marks[b] = nav
        end_ts = pd.Timestamp(row["exit_ts"]) if pd.notna(row["exit_ts"]) else END + pd.Timedelta(days=3650)
        nav_before = nav
        # Store entry NAV; completed return is applied when the route closes. Boundary marks are recomputed below.
        ret = float(row[f"account_ret_{int(bp)}"]) if pd.notna(row["exit_ts"]) else math.nan
        if np.isfinite(ret):
            nav *= max(1e-12, 1.0 + ret)
        rows.append({**row.to_dict(), "nav_before": nav_before, "nav_after": nav, "route_ret": ret})
        slot_end = end_ts
    ledger = pd.DataFrame(rows)
    # Rebuild exact liquidation-value marks from accepted positions in chronological order.
    for b in boundaries:
        n = 1.0
        for _, r in ledger.iterrows():
            if pd.Timestamp(r["entry_ts"]) >= b:
                break
            sd = symbol_data[str(r["symbol"])]
            if pd.notna(r["exit_ts"]) and pd.Timestamp(r["exit_ts"]) < b:
                rr = float(r[f"account_ret_{int(bp)}"])
            else:
                rr = mark_return(r, sd, b, bp)
                n *= max(1e-12, 1.0 + rr)
                break
            n *= max(1e-12, 1.0 + rr)
        marks[b] = n
    return ledger, marks


def metrics(ledger: pd.DataFrame, marks: dict[pd.Timestamp, float], bp: float, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    start_nav = marks.get(start, 1.0)
    end_nav = marks.get(end, start_nav)
    x = ledger[(ledger["entry_ts"] >= start) & (ledger["entry_ts"] < end)].copy()
    done = x[pd.notna(x["exit_ts"]) & (x["exit_ts"] < end)]
    rets = done[f"account_ret_{int(bp)}"].to_numpy(float) if len(done) else np.array([])
    wins = rets[rets > 0]; losses = rets[rets < 0]
    return {
        "start_nav": start_nav, "end_nav": end_nav, "multiple": end_nav / max(start_nav, 1e-12),
        "entries": int(len(x)), "completed": int(len(done)),
        "pf": float(wins.sum() / max(-losses.sum(), 1e-12)) if len(rets) else math.nan,
        "median": float(np.median(rets)) if len(rets) else math.nan,
        "mean": float(np.mean(rets)) if len(rets) else math.nan,
        "positive": int(np.sum(rets > 0)), "negative": int(np.sum(rets < 0)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path, required=True)
    ap.add_argument("--canonical", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    events = pd.read_csv(args.features)
    for c in ["event_ts", "decision_ts", "entry_ts", "post_entry_minute_last_ts"]:
        events[c] = pd.to_datetime(events[c], utc=True)
    symbol_data = {s: load_symbol(args.canonical, s) for s in ["BTCUSDT", "ETHUSDT"]}
    pools = {s: pool_consumed(symbol_data[s]) for s in symbol_data}
    enriched = []
    for _, e in events.iterrows():
        sd = symbol_data[e["symbol"]]; peer = symbol_data["ETHUSDT" if e["symbol"] == "BTCUSDT" else "BTCUSDT"]
        f = canonical_features(sd, peer, pd.Timestamp(e["decision_ts"]))
        enriched.append({**e.to_dict(), **f, "is_eth": float(e["symbol"] == "ETHUSDT")})
    events = pd.DataFrame(enriched)
    actions = []
    for _, e in events.iterrows():
        for a in ["CONTINUE", "REJECT"]:
            r = resolve_action(e, a, symbol_data[e["symbol"]], pools[e["symbol"]])
            if r is not None:
                r.update(e.to_dict()); r["is_continue"] = float(a == "CONTINUE")
                actions.append(r)
    actions = pd.DataFrame(actions)
    for c in ["decision_ts", "entry_ts", "exit_ts"]:
        actions[c] = pd.to_datetime(actions[c], utc=True)
    nonfeatures = {"event_id","symbol","event_day","event_ts","sensor_end_ts","decision_ts","activation_ts","entry_ts","post_entry_minute_last_ts","action","exit_ts","exit_reason","model_tag","prediction"}
    feature_cols = [c for c in actions.columns if c not in nonfeatures and pd.api.types.is_numeric_dtype(actions[c])]
    feature_cols = [c for c in feature_cols if not c.startswith(("account_ret_","notional_ret_","leverage_")) and c not in ["entry","exit","stop","target","funding_sum"]]
    # Raw fixed-action paths use a dummy positive priority.
    raw = {}
    for a in ["CONTINUE", "REJECT"]:
        z = actions[actions["action"] == a].copy(); z["prediction"] = 1.0
        led, mk = route(z, symbol_data, 24.0)
        raw[a] = {
            "may_aug": metrics(led, mk, 24.0, FIT_END, REFIT_END),
            "sep_dec": metrics(led, mk, 24.0, REFIT_END, END),
        }
    m1 = fit_model(actions, feature_cols, FIT_END)
    s1 = score_stage(actions, m1, feature_cols, FIT_END, REFIT_END, "FIT_JAN_APR")
    m2 = fit_model(actions, feature_cols, REFIT_END)
    s2 = score_stage(actions, m2, feature_cols, REFIT_END, END, "REFIT_THROUGH_AUG")
    selected = pd.concat([s1, s2], ignore_index=True).sort_values(["entry_ts", "prediction"], ascending=[True, False])
    result = {
        "result_id": "RES-20260730-DENSE-LIQUIDITY-EDGE-MICROFLOW-001",
        "status": "PENDING_DECISION",
        "source_events": int(len(events)), "action_rows": int(len(actions)),
        "resolved_before_may": int(np.sum(pd.notna(actions["exit_ts"]) & (actions["exit_ts"] < FIT_END))),
        "resolved_before_sep": int(np.sum(pd.notna(actions["exit_ts"]) & (actions["exit_ts"] < REFIT_END))),
        "feature_columns": feature_cols, "raw_24bp": raw, "costs": {},
    }
    ledgers = {}
    for bp in COSTS_BP:
        led, mk = route(selected, symbol_data, bp)
        ledgers[bp] = led
        positive = led[pd.notna(led["exit_ts"]) & (led[f"account_ret_{int(bp)}"] > 0)]
        k = max(1, int(math.ceil(0.10 * len(positive)))) if len(positive) else 0
        remove = set(positive.nlargest(k, f"account_ret_{int(bp)}")["event_id"]) if k else set()
        wr_led, wr_mk = route(selected, symbol_data, bp, remove)
        result["costs"][str(int(bp))] = {
            "may_jun": metrics(led, mk, bp, FIT_END, pd.Timestamp("2023-07-01T00:00Z")),
            "jul_aug": metrics(led, mk, bp, pd.Timestamp("2023-07-01T00:00Z"), REFIT_END),
            "may_aug": metrics(led, mk, bp, FIT_END, REFIT_END),
            "sep_oct": metrics(led, mk, bp, REFIT_END, pd.Timestamp("2023-11-01T00:00Z")),
            "nov_dec": metrics(led, mk, bp, pd.Timestamp("2023-11-01T00:00Z"), END),
            "sep_dec": metrics(led, mk, bp, REFIT_END, END),
            "continuous_may_dec": metrics(led, mk, bp, FIT_END, END),
            "winner_removed_may_aug": metrics(wr_led, wr_mk, bp, FIT_END, REFIT_END),
            "winner_removed_sep_dec": metrics(wr_led, wr_mk, bp, REFIT_END, END),
            "removed_event_count": len(remove),
        }
    g = result["costs"]["24"]
    def pass_part(name, h1, h2, wr):
        m = g[name]
        return m["entries"] >= 60 and m["multiple"] > 1 and m["pf"] > 1 and m["median"] >= 0 and g[h1]["multiple"] > 1 and g[h2]["multiple"] > 1 and g[wr]["multiple"] > 1
    passed = pass_part("may_aug", "may_jun", "jul_aug", "winner_removed_may_aug") and pass_part("sep_dec", "sep_oct", "nov_dec", "winner_removed_sep_dec")
    result["gate_pass"] = bool(passed)
    result["status"] = "PRE2024_GATE_PASS_OFFICIAL_AUTHORIZED" if passed else "RETIRED_PRE2024_NEGATIVE_SPARSE_UNSTABLE_OR_WINNER_DEPENDENT"
    result["official_2024_2026_opened"] = False
    actions.to_csv(args.out / "actions.csv.gz", index=False, compression="gzip")
    selected.to_csv(args.out / "selected_candidates.csv.gz", index=False, compression="gzip")
    ledgers[24.0].to_csv(args.out / "ledger_24bp.csv.gz", index=False, compression="gzip")
    (args.out / "RESULT.json").write_text(json.dumps(clean_json(result), indent=2, sort_keys=True), encoding="utf-8")
    report = [
        "# Dense official-Bybit liquidity-edge microflow", "",
        f"Status: `{result['status']}`", f"Source events: {len(events):,}", f"Action rows: {len(actions):,}",
        "", "## 24 bp forward partitions", "",
    ]
    for name in ["may_jun","jul_aug","may_aug","sep_oct","nov_dec","sep_dec","continuous_may_dec","winner_removed_may_aug","winner_removed_sep_dec"]:
        report.append(f"- {name}: `{json.dumps(clean_json(g[name]), sort_keys=True)}`")
    report += ["", "Raw actions and all 12/18/24-bp diagnostics are in RESULT.json. No risk/leverage or official-period result was opened unless the frozen gate passed."]
    (args.out / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    manifest = {p.name: sha256_file(p) for p in sorted(args.out.iterdir()) if p.is_file()}
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": result["status"], "events": len(events), "actions": len(actions)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
