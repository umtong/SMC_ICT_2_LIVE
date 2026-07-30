#!/usr/bin/env python3
"""Historical liquidity-void first-reentry Core fatal screen.

Implements the frozen takeover contract in GitHub issue #699.  The program
loads only canonical Bybit BTCUSDT/ETHUSDT data through 2022, constructs
causal completed-five-minute displacement runs and genuine FVG components,
waits for the first aged re-entry, maps acceptance to traversal and rejection
to continuation, and replays one global slot at fixed small risk.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
from dataclasses import dataclass, asdict
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

MIN_MS = 60_000
FIVE_MS = 300_000
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
PRE2023_END_MS = 1_672_531_200_000  # 2023-01-01T00:00:00Z
YEAR_START = {2021: 1_609_459_200_000, 2022: 1_640_995_200_000}
YEAR_END = {2021: 1_640_995_200_000, 2022: PRE2023_END_MS}
ACCOUNT_START_MS = YEAR_START[2021]
ACCOUNT_END_MS = PRE2023_END_MS
MOVE_THRESHOLDS = (1.0, 1.5)
WIDTH_THRESHOLDS = (0.10, 0.25)
EXPIRY_DAYS = (3, 7)
COSTS_BPS = (0, 12, 18, 24)
RISK_FRACTION = 0.005
NOTIONAL_CAP = 3.0
FUNDING_RESERVE = 0.0002
ATR_BUFFER = 0.10
SYMBOL_ORDER = {"BTCUSDT": 0, "ETHUSDT": 1}
CLAIM_ID = "CLM-20260730-LIQUIDITY-VOID-LIFECYCLE-TAKEOVER-001"
RESULT_ID = "RES-20260730-LIQUIDITY-VOID-LIFECYCLE-TAKEOVER-001"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv_gzip(df: pd.DataFrame, path: Path) -> None:
    """Write byte-reproducible UTF-8 CSV gzip (fixed header mtime/name)."""
    payload = df.to_csv(index=False, lineterminator="\n", float_format="%.17g").encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            gz.write(payload)


def classify_first_touch(side: int, proximal: float, distal: float, o: float, h: float, l: float, c: float) -> str:
    """Rule-owned action at the first completed one-minute re-entry."""
    full_traverse = (side == 1 and l <= distal) or (side == -1 and h >= distal)
    if full_traverse:
        return "FLAT_FULL_TRAVERSE"
    if side == 1 and distal < c < proximal:
        return "TRAVERSE"
    if side == -1 and proximal < c < distal:
        return "TRAVERSE"
    if side == 1 and c > proximal and c > o:
        return "CONTINUE"
    if side == -1 and c < proximal and c < o:
        return "CONTINUE"
    return "FLAT_AMBIGUOUS"


class ExtremeTree:
    """Segment tree supporting first future threshold crossing."""

    def __init__(self, values: np.ndarray, mode: str):
        if mode not in {"max", "min"}:
            raise ValueError(mode)
        self.mode = mode
        self.n = int(len(values))
        size = 1
        while size < self.n:
            size <<= 1
        self.size = size
        fill = -np.inf if mode == "max" else np.inf
        tree = np.full(2 * size, fill, dtype=np.float64)
        vals = np.asarray(values, dtype=np.float64)
        vals = np.where(np.isfinite(vals), vals, fill)
        tree[size : size + self.n] = vals
        op = np.maximum if mode == "max" else np.minimum
        for i in range(size - 1, 0, -1):
            tree[i] = op(tree[2 * i], tree[2 * i + 1])
        self.tree = tree

    def _qualifies(self, value: float, threshold: float, inclusive: bool) -> bool:
        if self.mode == "max":
            return value >= threshold if inclusive else value > threshold
        return value <= threshold if inclusive else value < threshold

    def first_cross(
        self,
        start: int,
        end: int,
        threshold: float,
        *,
        inclusive: bool = True,
    ) -> int | None:
        """Return first i in [start,end) crossing threshold, else None."""
        start = max(0, int(start))
        end = min(self.n, int(end))
        if start >= end:
            return None

        def search(node: int, left: int, right: int) -> int | None:
            if right <= start or end <= left:
                return None
            if not self._qualifies(float(self.tree[node]), threshold, inclusive):
                return None
            if right - left == 1:
                return left if left < self.n else None
            mid = (left + right) // 2
            hit = search(node * 2, left, mid)
            if hit is not None:
                return hit
            return search(node * 2 + 1, mid, right)

        return search(1, 0, self.size)


@dataclass(frozen=True)
class Level:
    level_id: str
    side: int
    price: float
    available_ms: int
    consumed_ms: int
    source: str
    center_ms: int


@dataclass
class SymbolData:
    symbol: str
    m1: pd.DataFrame
    b5: pd.DataFrame
    h1: pd.DataFrame
    h4: pd.DataFrame
    d1: pd.DataFrame
    funding: pd.DataFrame
    mt: np.ndarray
    mo: np.ndarray
    mh: np.ndarray
    ml: np.ndarray
    mc: np.ndarray
    mav: np.ndarray
    bt: np.ndarray
    bo: np.ndarray
    bh: np.ndarray
    bl: np.ndarray
    bc: np.ndarray
    bav: np.ndarray
    atr: np.ndarray
    ft: np.ndarray
    fr: np.ndarray
    tick: float
    high_tree: ExtremeTree
    low_tree: ExtremeTree
    close_high_tree: ExtremeTree
    close_low_tree: ExtremeTree
    levels: list[Level]
    level_prices: np.ndarray
    level_sides: np.ndarray
    level_available: np.ndarray
    level_consumed: np.ndarray
    level_sources: np.ndarray
    h4_state_times: np.ndarray
    h4_states: np.ndarray
    prev_day_map: dict[int, tuple[float, float]]


def complete_before(df: pd.DataFrame, end_ms: int, *, minute: bool = False) -> pd.DataFrame:
    if minute:
        out = df[df["observed"] & df["open"].notna() & (df["start_time_ms"] < end_ms)].copy()
    else:
        out = df[df["is_complete"] & df["close"].notna() & (df["start_time_ms"] < end_ms)].copy()
    return out.sort_values("start_time_ms").reset_index(drop=True)


def infer_tick(prices: np.ndarray) -> float:
    vals = np.unique(np.asarray(prices[np.isfinite(prices)], dtype=float)[:300_000])
    if len(vals) < 2:
        return 1e-8
    diffs = np.diff(vals)
    diffs = diffs[diffs > 0]
    return float(np.min(diffs)) if len(diffs) else 1e-8


def width_two_pivots(df: pd.DataFrame, source: str) -> list[tuple[int, float, int, str, int]]:
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    av = df["available_at_ms"].to_numpy(np.int64)
    st = df["start_time_ms"].to_numpy(np.int64)
    rows: list[tuple[int, float, int, str, int]] = []
    for i in range(2, len(df) - 2):
        if not np.isfinite(h[i]) or not np.isfinite(l[i]):
            continue
        if h[i] > h[i - 2] and h[i] > h[i - 1] and h[i] > h[i + 1] and h[i] > h[i + 2]:
            rows.append((1, float(h[i]), int(av[i + 2]), source, int(st[i])))
        if l[i] < l[i - 2] and l[i] < l[i - 1] and l[i] < l[i + 1] and l[i] < l[i + 2]:
            rows.append((-1, float(l[i]), int(av[i + 2]), source, int(st[i])))
    return rows


def compute_h4_state(h4: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    pivots = width_two_pivots(h4, "H4")
    pivots.sort(key=lambda x: (x[2], x[4], -x[0]))
    times = h4["available_at_ms"].to_numpy(np.int64)
    closes = h4["close"].to_numpy(float)
    latest_high: tuple[float, int] | None = None
    latest_low: tuple[float, int] | None = None
    p = 0
    state = 0
    states = np.zeros(len(h4), dtype=np.int8)
    for i, t in enumerate(times):
        while p < len(pivots) and pivots[p][2] <= int(t):
            side, price, _, _, center = pivots[p]
            if side == 1 and (latest_high is None or center > latest_high[1]):
                latest_high = (price, center)
            elif side == -1 and (latest_low is None or center > latest_low[1]):
                latest_low = (price, center)
            p += 1
        c = float(closes[i])
        up = latest_high is not None and c > latest_high[0]
        dn = latest_low is not None and c < latest_low[0]
        if up and not dn:
            state = 1
        elif dn and not up:
            state = -1
        states[i] = state
    return times, states


def load_symbol(root: Path, symbol: str) -> SymbolData:
    sroot = root / symbol
    m1 = complete_before(pd.read_pickle(sroot / "bars_1m.pkl.gz"), PRE2023_END_MS, minute=True)
    b5 = complete_before(pd.read_pickle(sroot / "bars_5m.pkl.gz"), PRE2023_END_MS)
    h1 = complete_before(pd.read_pickle(sroot / "bars_1h.pkl.gz"), PRE2023_END_MS)
    h4 = complete_before(pd.read_pickle(sroot / "bars_4h.pkl.gz"), PRE2023_END_MS)
    d1 = complete_before(pd.read_pickle(sroot / "bars_1d.pkl.gz"), PRE2023_END_MS)
    funding = pd.read_pickle(sroot / "funding_events.pkl.gz")
    funding = funding[funding["timestamp_ms"] < PRE2023_END_MS].sort_values("timestamp_ms").reset_index(drop=True)
    mt = m1["start_time_ms"].to_numpy(np.int64)
    mo = m1["open"].to_numpy(float)
    mh = m1["high"].to_numpy(float)
    ml = m1["low"].to_numpy(float)
    mc = m1["close"].to_numpy(float)
    mav = m1["available_at_ms"].to_numpy(np.int64)
    bt = b5["start_time_ms"].to_numpy(np.int64)
    bo = b5["open"].to_numpy(float)
    bh = b5["high"].to_numpy(float)
    bl = b5["low"].to_numpy(float)
    bc = b5["close"].to_numpy(float)
    bav = b5["available_at_ms"].to_numpy(np.int64)
    prev_close = b5["close"].shift(1)
    tr = np.maximum(b5["high"] - b5["low"], np.maximum((b5["high"] - prev_close).abs(), (b5["low"] - prev_close).abs()))
    atr = tr.rolling(288, min_periods=288).mean().shift(1).to_numpy(float)
    high_tree = ExtremeTree(mh, "max")
    low_tree = ExtremeTree(ml, "min")
    close_high_tree = ExtremeTree(bc, "max")
    close_low_tree = ExtremeTree(bc, "min")
    tick = infer_tick(mo)
    raw_levels: list[tuple[int, float, int, str, int]] = []
    for _, row in d1.iterrows():
        av = int(row["available_at_ms"])
        center = int(row["start_time_ms"])
        raw_levels.append((1, float(row["high"]), av, "D1", center))
        raw_levels.append((-1, float(row["low"]), av, "D1", center))
    raw_levels.extend(width_two_pivots(h1, "H1"))
    raw_levels.extend(width_two_pivots(h4, "H4"))
    levels: list[Level] = []
    for n, (side, price, av, source, center) in enumerate(raw_levels):
        start = int(np.searchsorted(mt, av, side="left"))
        ci = high_tree.first_cross(start, len(mt), price, inclusive=False) if side == 1 else low_tree.first_cross(start, len(mt), price, inclusive=False)
        consumed = int(mt[ci]) if ci is not None else 2**62
        levels.append(Level(f"{symbol}:{source}:{center}:{side}:{n}", side, price, av, consumed, source, center))
    levels.sort(key=lambda x: (x.available_ms, x.center_ms, x.side, x.price))
    prev_day_map: dict[int, tuple[float, float]] = {}
    for _, row in d1.iterrows():
        day = int(row["start_time_ms"])
        prev_day_map[day + DAY_MS] = (float(row["high"]), float(row["low"]))
    h4_state_times, h4_states = compute_h4_state(h4)
    return SymbolData(symbol, m1, b5, h1, h4, d1, funding, mt, mo, mh, ml, mc, mav, bt, bo, bh, bl, bc, bav, atr,
        funding["timestamp_ms"].to_numpy(np.int64), funding["funding_rate"].to_numpy(float), tick,
        high_tree, low_tree, close_high_tree, close_low_tree, levels,
        np.array([x.price for x in levels], dtype=float), np.array([x.side for x in levels], dtype=np.int8),
        np.array([x.available_ms for x in levels], dtype=np.int64), np.array([x.consumed_ms for x in levels], dtype=np.int64),
        np.array([x.source for x in levels], dtype=object), h4_state_times, h4_states, prev_day_map)


def latest_atr(d: SymbolData, available_ms: int) -> float:
    i = int(np.searchsorted(d.bav, available_ms, side="right")) - 1
    return float(d.atr[i]) if 0 <= i < len(d.atr) else math.nan


def h4_state_at(d: SymbolData, available_ms: int) -> int:
    i = int(np.searchsorted(d.h4_state_times, available_ms, side="right")) - 1
    return int(d.h4_states[i]) if i >= 0 else 0


def nearest_live_level(d: SymbolData, available_ms: int, price: float, side: int) -> tuple[str, float, str] | None:
    mask = (d.level_sides == side) & (d.level_available <= available_ms) & (d.level_consumed > available_ms)
    if side == 1:
        mask &= d.level_prices > price
        idx = np.flatnonzero(mask)
        if not len(idx): return None
        j = int(idx[np.argmin(d.level_prices[idx] - price)])
    else:
        mask &= d.level_prices < price
        idx = np.flatnonzero(mask)
        if not len(idx): return None
        j = int(idx[np.argmin(price - d.level_prices[idx])])
    return d.levels[j].level_id, float(d.level_prices[j]), str(d.level_sources[j])


def merge_intervals(intervals: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    rows = sorted((float(lo), float(hi)) for lo, hi in intervals if math.isfinite(lo) and math.isfinite(hi) and hi > lo)
    out: list[list[float]] = []
    for lo, hi in rows:
        if not out or lo > out[-1][1]: out.append([lo, hi])
        else: out[-1][1] = max(out[-1][1], hi)
    return [(x[0], x[1]) for x in out]


def funding_return(d: SymbolData, entry_ms: int, exit_ms: int, side: int) -> float:
    a = int(np.searchsorted(d.ft, entry_ms, side="right")); b = int(np.searchsorted(d.ft, exit_ms, side="right"))
    return float(-side * d.fr[a:b].sum()) if b > a else 0.0


def state_exit_index(d: SymbolData, decision_available: int, formation_side: int, proximal: float, action: str) -> int | None:
    b0 = int(np.searchsorted(d.bav, decision_available, side="right"))
    if action == "TRAVERSE":
        bi = d.close_high_tree.first_cross(b0, len(d.bc), proximal, inclusive=False) if formation_side == 1 else d.close_low_tree.first_cross(b0, len(d.bc), proximal, inclusive=False)
    else:
        bi = d.close_low_tree.first_cross(b0, len(d.bc), proximal, inclusive=False) if formation_side == 1 else d.close_high_tree.first_cross(b0, len(d.bc), proximal, inclusive=False)
    if bi is None: return None
    return int(np.searchsorted(d.mt, int(d.bav[bi]) + 500, side="left"))


def outcome_from_barriers(d: SymbolData, entry_idx: int, side: int, stop: float, target: float, state_exec_idx: int | None, boundary_ms: int) -> dict[str, Any]:
    boundary_idx = int(np.searchsorted(d.mt, boundary_ms, side="left"))
    barrier_end = min(len(d.mt), boundary_idx, state_exec_idx if state_exec_idx is not None else boundary_idx)
    if entry_idx >= max(barrier_end, 0) and not (state_exec_idx is not None and entry_idx <= state_exec_idx < boundary_idx):
        raise ValueError("entry outside outcome range")
    si = ti = None
    if entry_idx < barrier_end:
        if side == 1:
            si = d.low_tree.first_cross(entry_idx, barrier_end, stop, inclusive=True); ti = d.high_tree.first_cross(entry_idx, barrier_end, target, inclusive=True)
        else:
            si = d.high_tree.first_cross(entry_idx, barrier_end, stop, inclusive=True); ti = d.low_tree.first_cross(entry_idx, barrier_end, target, inclusive=True)
    if si is not None or ti is not None:
        if si is not None and (ti is None or si <= ti):
            op = float(d.mo[si]); px = min(op, stop) if side == 1 else max(op, stop)
            return {"exit_idx": si, "exit_ms": int(d.mt[si]), "slot_release_ms": int(d.mt[si]) + MIN_MS, "exit_price": px, "reason": "stop"}
        assert ti is not None
        return {"exit_idx": ti, "exit_ms": int(d.mt[ti]), "slot_release_ms": int(d.mt[ti]) + MIN_MS, "exit_price": target, "reason": "target"}
    if state_exec_idx is not None and state_exec_idx < boundary_idx:
        op = float(d.mo[state_exec_idx])
        if (side == 1 and op <= stop) or (side == -1 and op >= stop):
            return {"exit_idx": state_exec_idx, "exit_ms": int(d.mt[state_exec_idx]), "slot_release_ms": int(d.mt[state_exec_idx]), "exit_price": op, "reason": "stop_gap_at_state"}
        if (side == 1 and op >= target) or (side == -1 and op <= target):
            return {"exit_idx": state_exec_idx, "exit_ms": int(d.mt[state_exec_idx]), "slot_release_ms": int(d.mt[state_exec_idx]), "exit_price": target, "reason": "target_gap_at_state"}
        return {"exit_idx": state_exec_idx, "exit_ms": int(d.mt[state_exec_idx]), "slot_release_ms": int(d.mt[state_exec_idx]), "exit_price": op, "reason": "state_loss"}
    mark_idx = min(len(d.mt), boundary_idx) - 1
    if mark_idx < entry_idx: raise ValueError("no terminal mark after entry")
    return {"exit_idx": mark_idx, "exit_ms": int(boundary_ms), "slot_release_ms": int(boundary_ms), "exit_price": float(d.mc[mark_idx]), "reason": "stage_mark"}

# The remainder of the authority contains role construction, candidate generation,
# continuous one-slot NAV replay, winner-deletion rerouting, conditional Ridge/HGBT
# take-flat evaluation, focused tests, and deterministic generate/evaluate/finalize
# phases. The complete SHA-bound source is retained in the branch artifact payload.

# NOTE: Connector payload-size constraints require the rest of this file to be
# materialized from the exact source SHA recorded in VALIDATION.json. This prefix
# is not independently executable and is not the scientific authority.
