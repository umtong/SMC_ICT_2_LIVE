from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import itertools
import json
import math
import tarfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numba import njit

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
BAR_MS = 300_000
HOUR_MS = 3_600_000
WARMUP_START = pd.Timestamp("2021-12-01T00:00:00Z")
DEV_START = pd.Timestamp("2022-04-04T00:00:00Z")
DEV_END = pd.Timestamp("2023-01-01T00:00:00Z")
INITIAL_EQUITY = 10_000.0
RISK_FRACTION = 0.005
MAX_NOTIONAL_LEVERAGE = 3.0
MAX_QV_PARTICIPATION = 0.001
STOP_EXTRA_BPS = 4.0
COSTS_BPS = (12.0, 18.0, 24.0)
FIVE_MIN_Z_WINDOW = 8_640
FIVE_MIN_Z_MIN = 2_016
HOURLY_Z_WINDOW = 1_440
HOURLY_Z_MIN = 336
RV_HOURS = 720

FAMILIES = (
    "HIGH_VRP_RESIDUAL_FADE",
    "LOW_VRP_RESIDUAL_CONTINUATION",
    "RELATIVE_IV_GROUP_CONTINUATION",
    "RELATIVE_IV_DISCONFIRMATION_FADE",
    "IV_SHOCK_DISPERSION_CONTINUATION",
)


@dataclass(frozen=True, slots=True)
class Market:
    times: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    quote: np.ndarray
    buy_quote: np.ndarray
    atr_prior: np.ndarray
    mark_open: np.ndarray
    funding_value: np.ndarray
    funding_fallbacks: int


@dataclass(frozen=True, slots=True)
class FeatureBlock:
    beta_window: int
    horizon: int
    residual_z: np.ndarray
    flow_z: np.ndarray
    dispersion_z: np.ndarray


@dataclass(frozen=True, slots=True)
class DvolState:
    common_vrp_z: np.ndarray
    relative_iv_z: np.ndarray
    common_dvol_shock_z: np.ndarray
    known_at_ms: np.ndarray
    hourly_rows: int


@dataclass(frozen=True, slots=True)
class Candidate:
    family: str
    beta_window: int
    residual_horizon: int
    residual_z_threshold: float
    flow_threshold: float
    state_threshold: float
    maximum_hold_bars: int
    stop_atr: float

    @property
    def candidate_id(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()[:20]

    @property
    def signal_key(self) -> tuple[Any, ...]:
        return (
            self.family,
            self.beta_window,
            self.residual_horizon,
            self.residual_z_threshold,
            self.flow_threshold,
            self.state_threshold,
        )


SUMMARY_COLUMNS = (
    "n", "total_return", "gmean_daily", "profit_factor", "max_drawdown",
    "median_trade_bps", "top5_positive_share", "top10pct_removed_return",
    "h1_return", "h2_return", "positive_month_fraction", "worst_month",
    "traded_symbols", "max_single_symbol_trade_share", "max_direction_share",
    "stop_rate", "funding_pnl", "ending_equity",
)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def month_keys(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    periods = pd.period_range(start=start.tz_convert(None).to_period("M"), end=(end - pd.Timedelta(microseconds=1)).tz_convert(None).to_period("M"), freq="M")
    return [str(x) for x in periods]


def _read_nested_csv(raw_zip: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as inner:
        names = [n for n in inner.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV, got {names}")
        with inner.open(names[0]) as handle:
            return pd.read_csv(handle)


def _manifest_map(tf: tarfile.TarFile) -> dict[str, str]:
    raw = tf.extractfile("research_artifact/FILE_MANIFEST.sha256").read().decode()
    out: dict[str, str] = {}
    for line in raw.splitlines():
        if line.strip():
            digest, name = line.split("  ", 1)
            out[name] = digest
    return out


def load_market_from_tar(tar_path: Path, start: pd.Timestamp, end: pd.Timestamp) -> tuple[Market, dict[str, Any]]:
    lo_ms = int(start.value // 1_000_000); up_ms = int(end.value // 1_000_000)
    times = np.arange(lo_ms, up_ms, BAR_MS, dtype=np.int64); n = len(times)
    shape = (len(SYMBOLS), n)
    fields = {k: np.full(shape, np.nan, dtype=np.float64) for k in ("open", "high", "low", "close", "quote", "buy_quote", "mark_open")}
    funding_rate = np.zeros(shape, dtype=np.float64)
    verified: list[dict[str, Any]] = []
    months = month_keys(start, end)
    with tarfile.open(tar_path, mode="r") as tf:
        manifest = _manifest_map(tf)
        for si, symbol in enumerate(SYMBOLS):
            for ym in months:
                for kind, timeframe in (("klines", "5m"), ("markPriceKlines", "5m"), ("fundingRate", "none")):
                    basename = f"{symbol}-{'fundingRate' if kind == 'fundingRate' else timeframe}-{ym}.zip"
                    path = f"research_artifact/raw/{kind}/{symbol}/{timeframe}/{basename}"
                    raw = tf.extractfile(tf.getmember(path)).read()
                    observed = sha256_bytes(raw); expected = manifest.get(path)
                    if observed != expected:
                        raise AssertionError(f"archive hash mismatch {path}: {observed} != {expected}")
                    frame = _read_nested_csv(raw)
                    verified.append({"path": path, "bytes": len(raw), "sha256": observed, "rows": int(len(frame))})
                    if kind == "fundingRate":
                        t = pd.to_numeric(frame["calc_time"], errors="raise").to_numpy(np.int64)
                        r = pd.to_numeric(frame["last_funding_rate"], errors="raise").to_numpy(float)
                        pos = np.searchsorted(times, t); valid = (pos < n) & (times[np.minimum(pos, n - 1)] == t)
                        funding_rate[si, pos[valid]] = r[valid]; continue
                    t = pd.to_numeric(frame["open_time"], errors="raise").to_numpy(np.int64)
                    pos = np.searchsorted(times, t); valid = (pos < n) & (times[np.minimum(pos, n - 1)] == t)
                    if kind == "klines":
                        for src, dst in (("open", "open"), ("high", "high"), ("low", "low"), ("close", "close"), ("quote_volume", "quote"), ("taker_buy_quote_volume", "buy_quote")):
                            values = pd.to_numeric(frame[src], errors="raise").to_numpy(float)
                            fields[dst][si, pos[valid]] = values[valid]
                    else:
                        values = pd.to_numeric(frame["open"], errors="raise").to_numpy(float)
                        fields["mark_open"][si, pos[valid]] = values[valid]
    atr_prior = np.full(shape, np.nan, dtype=np.float64)
    for si in range(len(SYMBOLS)):
        prev = np.r_[np.nan, fields["close"][si, :-1]]
        tr = np.maximum(fields["high"][si] - fields["low"][si], np.maximum(np.abs(fields["high"][si] - prev), np.abs(fields["low"][si] - prev)))
        atr_prior[si] = pd.Series(tr).shift(1).rolling(288, min_periods=144).mean().to_numpy(float)
    fallback_mask = (funding_rate != 0) & ~np.isfinite(fields["mark_open"]) & np.isfinite(fields["open"])
    funding_mark = np.where(np.isfinite(fields["mark_open"]), fields["mark_open"], fields["open"])
    funding_value = np.where(funding_rate != 0, funding_mark * funding_rate, 0.0)
    if ((funding_rate != 0) & ~np.isfinite(funding_mark)).any():
        raise AssertionError("missing both mark and contract open for funding")
    market = Market(times, fields["open"], fields["high"], fields["low"], fields["close"], fields["quote"], fields["buy_quote"], atr_prior, fields["mark_open"], funding_value, int(fallback_mask.sum()))
    manifest_out = {
        "source_tar": str(tar_path), "source_tar_sha256": sha256_file(tar_path),
        "start": start.isoformat(), "end": end.isoformat(), "bars": n,
        "symbols": list(SYMBOLS), "verified_archives": verified,
        "verified_archive_count": len(verified),
        "funding_events": {SYMBOLS[i]: int((funding_rate[i] != 0).sum()) for i in range(4)},
        "funding_contract_open_fallbacks": int(fallback_mask.sum()),
        "missing_bars": {SYMBOLS[i]: int((~np.isfinite(fields["open"][i])).sum()) for i in range(4)},
    }
    return market, manifest_out


def rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(values).rolling(window, min_periods=window).sum().to_numpy(float)


def prior_z(values: np.ndarray, window: int, minimum: int) -> np.ndarray:
    s = pd.Series(values); hist = s.shift(1)
    mean = hist.rolling(window, min_periods=minimum).mean()
    std = hist.rolling(window, min_periods=minimum).std(ddof=0).replace(0, np.nan)
    return ((s - mean) / std).to_numpy(float)


def prior_beta(factor: np.ndarray, target: np.ndarray, window: int, minimum: int) -> np.ndarray:
    x, y = pd.Series(factor), pd.Series(target)
    mx = x.rolling(window, min_periods=minimum).mean().shift(1); my = y.rolling(window, min_periods=minimum).mean().shift(1)
    exy = (x * y).rolling(window, min_periods=minimum).mean().shift(1); ex2 = (x * x).rolling(window, min_periods=minimum).mean().shift(1)
    return ((exy - mx * my) / (ex2 - mx * mx).replace(0, np.nan)).to_numpy(float)


def build_feature_blocks(market: Market) -> dict[tuple[int, int], FeatureBlock]:
    log_close = np.log(market.close); ret = np.full_like(market.close, np.nan)
    ret[:, 1:] = log_close[:, 1:] - log_close[:, :-1]
    valid_pair = np.isfinite(market.close[:, 1:]) & np.isfinite(market.close[:, :-1])
    ret[:, 1:] = np.where(valid_pair, ret[:, 1:], np.nan)
    factor = np.full_like(ret, np.nan)
    for si in range(4):
        others = np.delete(ret, si, axis=0); factor[si] = np.nanmedian(others, axis=0); factor[si, ~np.isfinite(others).all(axis=0)] = np.nan
    signed_quote = 2.0 * market.buy_quote - market.quote; out = {}
    for beta_window in (2016, 4032):
        residual = np.full_like(ret, np.nan)
        for si in range(4): residual[si] = ret[si] - prior_beta(factor[si], ret[si], beta_window, beta_window) * factor[si]
        for horizon in (12, 48):
            rz = np.full_like(ret, np.nan); fz = np.full_like(ret, np.nan)
            for si in range(4):
                cum = rolling_sum(residual[si], horizon); q = rolling_sum(market.quote[si], horizon); sq = rolling_sum(signed_quote[si], horizon)
                imbalance = np.divide(sq, q, out=np.full_like(q, np.nan), where=(q > 0) & np.isfinite(q) & np.isfinite(sq))
                rz[si] = prior_z(cum, FIVE_MIN_Z_WINDOW, FIVE_MIN_Z_MIN); fz[si] = prior_z(imbalance, FIVE_MIN_Z_WINDOW, FIVE_MIN_Z_MIN)
            dispersion = np.nanstd(rz, axis=0); dispersion[~np.isfinite(rz).all(axis=0)] = np.nan
            out[(beta_window, horizon)] = FeatureBlock(beta_window, horizon, rz, fz, prior_z(dispersion, FIVE_MIN_Z_WINDOW, FIVE_MIN_Z_MIN))
    return out


def load_dvol_state(dvol_zip: Path, market: Market, end: pd.Timestamp) -> tuple[DvolState, dict[str, Any]]:
    with zipfile.ZipFile(dvol_zip) as zf:
        frames = {}
        for cur in ("BTC", "ETH"):
            raw = zf.read(f"{cur}_DVOL_1h.csv.gz")
            with gzip.open(io.BytesIO(raw), "rt") as handle: frame = pd.read_csv(handle)
            frame["open_time_ms"] = pd.to_numeric(frame["open_time_ms"], errors="raise").astype("int64")
            frame["close"] = pd.to_numeric(frame["close"], errors="raise")
            frame = frame[frame.open_time_ms + HOUR_MS < int(end.value // 1_000_000)].copy(); frame["known_at_ms"] = frame.open_time_ms + HOUR_MS
            frames[cur] = frame[["known_at_ms", "close"]].rename(columns={"close": f"{cur.lower()}_dvol"})
        hourly = frames["BTC"].merge(frames["ETH"], on="known_at_ms", how="inner", validate="one_to_one").sort_values("known_at_ms")
    market_time = pd.to_datetime(market.times, unit="ms", utc=True); rv_values = []
    for si in range(2):
        series = pd.Series(market.close[si], index=market_time); hourly_close = series.resample("1h", label="right", closed="right").last()
        count = series.notna().resample("1h", label="right", closed="right").sum(); hourly_close[count < 12] = np.nan
        close = hourly_close.reindex(pd.to_datetime(hourly.known_at_ms, unit="ms", utc=True)); ret = np.log(close).diff()
        rv_values.append((np.sqrt(ret.shift(1).pow(2).rolling(RV_HOURS, min_periods=RV_HOURS).mean() * 8760.0) * 100.0).to_numpy(float))
    common_rv = np.nanmean(np.vstack(rv_values), axis=0)
    common_dvol = 0.5 * (hourly.btc_dvol.to_numpy(float) + hourly.eth_dvol.to_numpy(float))
    relative_iv = np.log(hourly.eth_dvol.to_numpy(float) / hourly.btc_dvol.to_numpy(float))
    common_vrp_z_h = prior_z(common_dvol - common_rv, HOURLY_Z_WINDOW, HOURLY_Z_MIN)
    relative_iv_z_h = prior_z(relative_iv, HOURLY_Z_WINDOW, HOURLY_Z_MIN)
    shock_z_h = prior_z(np.r_[np.nan, np.diff(common_dvol)], HOURLY_Z_WINDOW, HOURLY_Z_MIN)
    decision_ms = market.times + BAR_MS; positions = np.searchsorted(hourly.known_at_ms.to_numpy(np.int64), decision_ms, side="right") - 1; valid = positions >= 0
    def mapped(values):
        out = np.full(len(decision_ms), np.nan); out[valid] = values[positions[valid]]; return out
    state = DvolState(mapped(common_vrp_z_h), mapped(relative_iv_z_h), mapped(shock_z_h), hourly.known_at_ms.to_numpy(np.int64), int(len(hourly)))
    return state, {"source_zip": str(dvol_zip), "source_zip_sha256": sha256_file(dvol_zip), "hourly_rows": int(len(hourly)), "availability": "open_time + 1h", "rv_current_hour_excluded": True}


def candidate_grid() -> list[Candidate]:
    rows = [Candidate(*x) for x in itertools.product(FAMILIES, (2016, 4032), (12, 48), (1.5, 2.0, 2.5), (0.5, 1.0), (0.5, 1.0), (12, 48), (1.5, 2.5))]
    assert len(rows) == 960 and len({r.candidate_id for r in rows}) == 960
    return rows


def rising_edge(mask: np.ndarray) -> np.ndarray:
    previous = np.zeros_like(mask, dtype=bool); previous[:, 1:] = mask[:, :-1]
    return mask & ~previous


def select_signals(block: FeatureBlock, state: DvolState, candidate: Candidate, market: Market, start_ms: int, end_ms: int):
    rz, fz = block.residual_z, block.flow_z
    residual_sign = np.where(np.isfinite(rz), np.sign(rz), 0).astype(np.int8); signed_flow = residual_sign * fz
    base = np.isfinite(rz) & np.isfinite(fz) & (np.abs(rz) >= candidate.residual_z_threshold) & (residual_sign != 0); t = candidate.state_threshold
    if candidate.family == "HIGH_VRP_RESIDUAL_FADE":
        mask = base & (state.common_vrp_z >= t)[None, :] & (signed_flow <= candidate.flow_threshold); direction = -residual_sign
        score = np.abs(rz) + np.maximum(state.common_vrp_z, 0)[None, :] + np.maximum(-signed_flow, 0)
    elif candidate.family == "LOW_VRP_RESIDUAL_CONTINUATION":
        mask = base & (state.common_vrp_z <= -t)[None, :] & (signed_flow >= candidate.flow_threshold); direction = residual_sign
        score = np.abs(rz) + np.maximum(-state.common_vrp_z, 0)[None, :] + np.maximum(signed_flow, 0)
    elif candidate.family in ("RELATIVE_IV_GROUP_CONTINUATION", "RELATIVE_IV_DISCONFIRMATION_FADE"):
        rel = state.relative_iv_z; group = np.zeros_like(rz, dtype=bool); group[0] = rel <= -t; group[1:] = rel[None, :] >= t
        if candidate.family == "RELATIVE_IV_GROUP_CONTINUATION":
            mask = base & group & (signed_flow >= candidate.flow_threshold); direction = residual_sign; score = np.abs(rz) + np.abs(rel)[None, :] + np.maximum(signed_flow, 0)
        else:
            mask = base & group & (signed_flow <= candidate.flow_threshold); direction = -residual_sign; score = np.abs(rz) + np.abs(rel)[None, :] + np.maximum(-signed_flow, 0)
    else:
        iv_mask = (state.common_dvol_shock_z >= t) & (block.dispersion_z >= t)
        mask = base & iv_mask[None, :] & (signed_flow >= candidate.flow_threshold); direction = residual_sign
        score = np.abs(rz) + np.maximum(state.common_dvol_shock_z, 0)[None, :] + np.maximum(block.dispersion_z, 0)[None, :] + np.maximum(signed_flow, 0)
    mask &= ((market.times >= start_ms) & (market.times < end_ms))[None, :]; mask &= np.isfinite(score)
    scored = np.where(rising_edge(np.nan_to_num(mask, nan=False)), score, -np.inf); selected = np.argmax(scored, axis=0).astype(np.int8); best = scored[selected, np.arange(scored.shape[1])]
    bars = np.flatnonzero(np.isfinite(best)); return bars.astype(np.int64), selected[bars], direction[selected[bars], bars].astype(np.int8), best[bars].astype(float)


@njit(cache=True)
def simulate_path(times, op, hi, lo, quote, atr, funding_cum, residual_z, flow_z, bars, symbols, sides, scores, max_hold, stop_atr, family_is_fade, cost_bps):
    max_n = len(bars); ar = np.empty(max_n); pnls = np.empty(max_n); funding_pnls = np.empty(max_n); entries = np.empty(max_n, np.int64); exits = np.empty(max_n, np.int64); out_symbols = np.empty(max_n, np.int8); out_sides = np.empty(max_n, np.int8); reasons = np.empty(max_n, np.int8); out_scores = np.empty(max_n)
    equity = INITIAL_EQUITY; free_index = -1; count = 0
    for k in range(max_n):
        signal = int(bars[k])
        if signal + 1 <= free_index: continue
        si, side, entry = int(symbols[k]), int(sides[k]), signal + 1; cap = entry + max_hold
        if cap >= len(times) or times[entry] != times[signal] + BAR_MS or times[cap] - times[entry] != max_hold * BAR_MS: continue
        ep, a = op[si, entry], atr[si, signal]
        if not (np.isfinite(ep) and ep > 0 and np.isfinite(a) and a > 0): continue
        dist = max(stop_atr * a, ep * .0015)
        if dist > ep * .10: continue
        stop = ep - side * dist; planned = dist / ep + (cost_bps + STOP_EXTRA_BPS) / 10000.; prior_quote = quote[si, signal]
        if not np.isfinite(prior_quote) or prior_quote <= 0: continue
        notional = min(equity * RISK_FRACTION / planned, equity * MAX_NOTIONAL_LEVERAGE, prior_quote * MAX_QV_PARTICIPATION)
        if not np.isfinite(notional) or notional <= 0: continue
        xi, xp, reason, valid = cap, op[si, cap], 3, np.isfinite(op[si, cap])
        if not valid: continue
        for j in range(entry, cap):
            o, h, l = op[si, j], hi[si, j], lo[si, j]
            if not (np.isfinite(o) and np.isfinite(h) and np.isfinite(l)): valid = False; break
            if side > 0:
                if o <= stop: xi, xp, reason = j, o, 1; break
                if l <= stop: xi, xp, reason = j, stop, 1; break
            else:
                if o >= stop: xi, xp, reason = j, o, 1; break
                if h >= stop: xi, xp, reason = j, stop, 1; break
            if j >= entry + 2 and j + 1 <= cap:
                rz, fz = residual_z[si, j], flow_z[si, j]
                if np.isfinite(rz) and np.isfinite(fz):
                    ended = (abs(rz) <= .5 or side * fz < 0) if family_is_fade == 1 else (side * rz <= .5 or side * fz < 0)
                    if ended and np.isfinite(op[si, j + 1]): xi, xp, reason = j + 1, op[si, j + 1], 2; break
        if not valid or not np.isfinite(xp) or xp <= 0: continue
        qty = notional / ep; price_pnl = side * qty * (xp - ep); fee_pnl = -notional * cost_bps / 10000.
        if reason == 1: fee_pnl -= notional * STOP_EXTRA_BPS / 10000.
        funding_pnl = -side * qty * (funding_cum[si, xi] - funding_cum[si, entry]); total = price_pnl + fee_pnl + funding_pnl; before = equity; equity = max(1e-12, equity + total)
        ar[count] = total / before; pnls[count] = total; funding_pnls[count] = funding_pnl; entries[count] = entry; exits[count] = xi; out_symbols[count] = si; out_sides[count] = side; reasons[count] = reason; out_scores[count] = scores[k]; count += 1; free_index = xi
    return ar[:count], pnls[:count], funding_pnls[:count], entries[:count], exits[:count], out_symbols[:count], out_sides[:count], reasons[:count], out_scores[:count]


def summarize_simulation(result, market: Market, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    ar, pnls, funding_pnls, entry_indices, exit_indices, symbols, sides, reasons, _scores = result; n = len(ar)
    if n == 0: return dict(zip(SUMMARY_COLUMNS, (0., 0., 0., 0., 0., 0., 1., -1., 0., 0., 0., 0., 0., 1., 1., 0., 0., INITIAL_EQUITY)))
    curve = INITIAL_EQUITY * np.cumprod(1 + ar); c = np.r_[INITIAL_EQUITY, curve]; peak = np.maximum.accumulate(c); ending = float(curve[-1]); total = ending / INITIAL_EQUITY - 1; days = max(1., (end - start).total_seconds() / 86400.); gd = math.exp(math.log(max(1e-300, ending / INITIAL_EQUITY)) / days) - 1
    pos, neg = pnls[pnls > 0], -pnls[pnls < 0]; pf = float(pos.sum() / neg.sum()) if neg.sum() > 0 else (999. if pos.sum() > 0 else 0.); top5 = float(np.sort(pos)[-5:].sum() / pos.sum()) if pos.sum() > 0 else 1.
    remove_n = int(math.ceil(n * .1)); pidx = np.flatnonzero(ar > 0); ranked = pidx[np.argsort(ar[pidx])[::-1]] if len(pidx) else np.empty(0, int); keep = np.ones(n, bool); keep[ranked[:min(remove_n, len(ranked))]] = False; removed = float(np.prod(1 + ar[keep]) - 1) if keep.any() else -1.
    entry_times = pd.to_datetime(market.times[entry_indices], unit="ms", utc=True); exit_times = pd.to_datetime(market.times[exit_indices], unit="ms", utc=True); midpoint = start + (end - start) / 2; h1 = entry_times < midpoint
    h1r = float(np.prod(1 + ar[h1]) - 1) if h1.any() else 0.; h2r = float(np.prod(1 + ar[~h1]) - 1) if (~h1).any() else 0.; months = month_keys(start, end); mr = {m: 1. for m in months}
    for ret, t in zip(ar, exit_times):
        key = t.strftime("%Y-%m")
        if key in mr: mr[key] *= 1 + ret
    mv = np.array([mr[m] - 1 for m in months]); counts = np.bincount(symbols.astype(np.int64), minlength=4); long_n = int((sides > 0).sum())
    return {"n": float(n), "total_return": total, "gmean_daily": gd, "profit_factor": pf, "max_drawdown": float(np.max(1 - c / peak)), "median_trade_bps": float(np.median(ar) * 10000), "top5_positive_share": top5, "top10pct_removed_return": removed, "h1_return": h1r, "h2_return": h2r, "positive_month_fraction": float((mv > 0).mean()), "worst_month": float(mv.min()), "traded_symbols": float((counts > 0).sum()), "max_single_symbol_trade_share": float(counts.max() / n), "max_direction_share": float(max(long_n, n-long_n) / n), "stop_rate": float((reasons == 1).mean()), "funding_pnl": float(funding_pnls.sum()), "ending_equity": ending}


def candidate_gate(r: pd.Series) -> bool:
    return bool(r.c12_n >= 100 and r.c12_total_return > 0 and r.c18_total_return > 0 and r.c24_total_return > 0 and r.c12_profit_factor >= 1.15 and r.c12_max_drawdown <= .15 and r.c12_median_trade_bps > 0 and r.c12_top10pct_removed_return > 0 and r.c12_top5_positive_share <= .30 and r.c12_positive_month_fraction >= .60 and r.c18_h1_return > 0 and r.c18_h2_return > 0 and r.c12_traded_symbols >= 3 and r.c12_max_single_symbol_trade_share <= .65 and r.c12_max_direction_share <= .75)


def make_ledger(candidate: Candidate, result, market: Market, cost_bps: float) -> pd.DataFrame:
    ar, pnls, funding_pnls, entries, exits, symbols, sides, reasons, scores = result; reason_map = {1: "protective_or_gap_stop", 2: "causal_state_exit", 3: "maximum_lifetime"}
    return pd.DataFrame({"candidate_id": candidate.candidate_id, "family": candidate.family, "entry_time": pd.to_datetime(market.times[entries], unit="ms", utc=True), "exit_time": pd.to_datetime(market.times[exits], unit="ms", utc=True), "symbol": [SYMBOLS[int(x)] for x in symbols], "side": sides, "reason": [reason_map[int(x)] for x in reasons], "score": scores, "account_return": ar, "pnl": pnls, "funding_pnl": funding_pnls, "cost_bps": cost_bps})


def real_prefix_invariance(market: Market, blocks: dict[tuple[int, int], FeatureBlock], cutoff: pd.Timestamp) -> dict[str, Any]:
    n = int(np.searchsorted(market.times, int(cutoff.value // 1_000_000)))
    pm = Market(market.times[:n].copy(), market.open[:, :n].copy(), market.high[:, :n].copy(), market.low[:, :n].copy(), market.close[:, :n].copy(), market.quote[:, :n].copy(), market.buy_quote[:, :n].copy(), market.atr_prior[:, :n].copy(), market.mark_open[:, :n].copy(), market.funding_value[:, :n].copy(), market.funding_fallbacks)
    pb = build_feature_blocks(pm); max_diff = 0.; mismatch = 0
    for key, full in blocks.items():
        for field in ("residual_z", "flow_z", "dispersion_z"):
            a, b = getattr(full, field), getattr(pb[key], field); a = a[:, :n] if a.ndim == 2 else a[:n]; fm = np.isfinite(a) ^ np.isfinite(b); mismatch += int(fm.sum()); both = np.isfinite(a) & np.isfinite(b); max_diff = max(max_diff, float(np.max(np.abs(a[both] - b[both]))) if both.any() else 0.)
    return {"cutoff": cutoff.isoformat(), "prefix_rows": n, "max_abs_diff": max_diff, "finite_mismatch": mismatch, "pass": bool(max_diff <= 1e-12 and mismatch == 0)}


def run_development(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.output_dir); out_dir.mkdir(parents=True, exist_ok=True)
    market, market_manifest = load_market_from_tar(Path(args.binance_tar), WARMUP_START, DEV_END); state, dvol_manifest = load_dvol_state(Path(args.dvol_zip), market, DEV_END); blocks = build_feature_blocks(market); funding_cum = np.cumsum(market.funding_value, axis=1); candidates = candidate_grid(); start_ms = int(DEV_START.value // 1_000_000); end_ms = int(DEV_END.value // 1_000_000)
    signal_cache = {}; lookup = {c.candidate_id: c for c in candidates}; rows = []
    for index, candidate in enumerate(candidates, 1):
        block = blocks[(candidate.beta_window, candidate.residual_horizon)]
        if candidate.signal_key not in signal_cache: signal_cache[candidate.signal_key] = select_signals(block, state, candidate, market, start_ms, end_ms)
        bars, symbols, sides, scores = signal_cache[candidate.signal_key]; row = {"candidate_id": candidate.candidate_id, **asdict(candidate), "signal_events": len(bars)}; fade = int(candidate.family in ("HIGH_VRP_RESIDUAL_FADE", "RELATIVE_IV_DISCONFIRMATION_FADE"))
        for cost in COSTS_BPS:
            sim = simulate_path(market.times, market.open, market.high, market.low, market.quote, market.atr_prior, funding_cum, block.residual_z, block.flow_z, bars, symbols, sides, scores, candidate.maximum_hold_bars, candidate.stop_atr, fade, cost)
            row.update({f"c{int(cost)}_{k}": v for k, v in summarize_simulation(sim, market, DEV_START, DEV_END).items()})
        rows.append(row)
        if index % 100 == 0: print(json.dumps({"evaluated": index, "total": len(candidates)}, sort_keys=True), flush=True)
    screen = pd.DataFrame(rows); screen["development_gate_pass"] = screen.apply(candidate_gate, axis=1); screen = screen.sort_values(["development_gate_pass", "c12_gmean_daily", "c12_top10pct_removed_return"], ascending=[False, False, False]).reset_index(drop=True); screen.to_csv(out_dir / "development_screen_2022.csv", index=False)
    passed = screen[screen.development_gate_pass]; reps = passed.head(12); rep = {"stage": "development_2022", "gate_pass_count": int(len(passed)), "frozen_representatives": reps.candidate_id.tolist(), "selection_opened": bool(len(reps)), "2024_opened": False, "2025_or_2026_opened": False}; (out_dir / "representative_manifest.json").write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n")
    top_ids = []
    if len(screen): top_ids.append(str(screen.iloc[0].candidate_id)); broad = screen[screen.c12_n >= 100]; top_ids += ([str(broad.sort_values("c12_gmean_daily", ascending=False).iloc[0].candidate_id)] if len(broad) else []); top_ids.append(str(screen.sort_values("c12_top10pct_removed_return", ascending=False).iloc[0].candidate_id))
    ledgers = {}
    for cid in dict.fromkeys(top_ids):
        c = lookup[cid]; block = blocks[(c.beta_window, c.residual_horizon)]; bars, symbols, sides, scores = signal_cache[c.signal_key]; fade = int(c.family in ("HIGH_VRP_RESIDUAL_FADE", "RELATIVE_IV_DISCONFIRMATION_FADE")); sim = simulate_path(market.times, market.open, market.high, market.low, market.quote, market.atr_prior, funding_cum, block.residual_z, block.flow_z, bars, symbols, sides, scores, c.maximum_hold_bars, c.stop_atr, fade, 12.); path = out_dir / f"ledger_{cid}_c12.csv"; make_ledger(c, sim, market, 12.).to_csv(path, index=False); ledgers[cid] = path.name
    audit = real_prefix_invariance(market, blocks, pd.Timestamp("2022-12-01T00:00:00Z")); (out_dir / "prefix_invariance.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n"); market_manifest["dvol"] = dvol_manifest; market_manifest["common_clock_missing_any_asset"] = int((~np.isfinite(market.open).all(axis=0)).sum()); (out_dir / "data_manifest.json").write_text(json.dumps(market_manifest, indent=2, sort_keys=True) + "\n")
    def clean(r): return {k: (v.item() if isinstance(v, np.generic) else v) for k, v in r.to_dict().items()}
    broad = screen[screen.c12_n >= 100]; summary = {"schema_version": 1, "study_id": "DVOL_XSEC_REGIME_ROUTER_V1", "claim_id": "CLM-20260726-0005-DVOL-XSEC-001", "status": "CANDIDATE" if len(passed) else "TESTED_BELOW_GATE", "hard_validity_status": "PASS" if audit["pass"] else "FAIL", "economic_status": "BASIC_COST_POSITIVE" if len(passed) else "BELOW_GATE", "candidate_count": int(len(screen)), "unique_signal_path_count": int(len(signal_cache)), "development_gate_pass_count": int(len(passed)), "selection_opened": bool(len(passed)), "2024_opened": False, "2025_or_2026_opened": False, "orders_submitted": False, "best_raw": clean(screen.iloc[0]) if len(screen) else None, "best_minimum_100_trades": clean(broad.sort_values("c12_gmean_daily", ascending=False).iloc[0]) if len(broad) else None, "best_top10pct_removed": clean(screen.sort_values("c12_top10pct_removed_return", ascending=False).iloc[0]) if len(screen) else None, "prefix_invariance": audit, "data": {"binance_tar_sha256": market_manifest["source_tar_sha256"], "dvol_zip_sha256": dvol_manifest["source_zip_sha256"], "verified_archive_count": market_manifest["verified_archive_count"], "funding_contract_open_fallbacks": market.funding_fallbacks}, "ledgers": ledgers, "decision": "Open frozen 2023 selection only for preregistered development survivors." if len(passed) else "Reject the preregistered DVOL cross-sectional router under this dependency fingerprint without opening 2023."}; (out_dir / "result_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n"); return summary


def self_test() -> None:
    x = np.arange(100.); a = prior_z(x, 20, 10); b = prior_z(np.r_[x, [10_000., -10_000.]], 20, 10)[:len(x)]; assert np.allclose(a, b, equal_nan=True)
    mask = np.array([[False, True, True, False, True]]); assert rising_edge(mask).tolist() == [[False, True, False, False, True]]
    grid = candidate_grid(); assert len(grid) == 960 and len({x.candidate_id for x in grid}) == 960
    values = np.array([[0., 2., 0., -1.]]); cum = np.cumsum(values, axis=1); assert cum[0, 3] - cum[0, 1] == -1.
    print("self-test passed")


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--binance-tar", default="/mnt/data/binance_usdm_research_data.tar"); p.add_argument("--dvol-zip", default="/mnt/data/deribit-dvol-bundle.zip"); p.add_argument("--output-dir", default="/mnt/data/dvol_xsec_regime_v1/results"); p.add_argument("--self-test", action="store_true"); args = p.parse_args()
    if args.self_test: self_test()
    else: print(json.dumps(run_development(args), indent=2, sort_keys=True, default=str))


if __name__ == "__main__": main()
