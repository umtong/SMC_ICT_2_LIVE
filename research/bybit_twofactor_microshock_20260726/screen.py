from __future__ import annotations

import argparse
import csv
import gc
import gzip
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

CLAIM = "CLM-20260726-1142-TWOFACTOR-MICROSHOCK-001"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
FOLLOWERS = ("SOLUSDT", "XRPUSDT")
SCREEN_DATES = ("2023-01-15", "2023-03-19", "2023-04-16")
CONFIRM_DATES = ("2023-06-18", "2023-08-20", "2023-12-17")
HORIZONS = (1, 2, 5)
FLOORS = (0.0012, 0.0018, 0.0024)
FAMILIES = (
    "consensus_underreaction",
    "consensus_overreaction",
    "eth_idiosyncratic_underreaction",
    "eth_idiosyncratic_overreaction",
)
BINS_PER_DAY = 24 * 60 * 60 * 10
BASE_URL = "https://public.bybit.com/trading"


@dataclass(frozen=True, slots=True)
class SourceRecord:
    symbol: str
    date: str
    url: str
    bytes: int
    sha256: str
    rows: int
    first_timestamp: float
    last_timestamp: float
    timestamp_monotonic: bool
    columns: list[str]


def utc_start(date: str) -> float:
    return datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


def download(session: requests.Session, url: str, target: Path, attempts: int = 5) -> Path:
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for attempt in range(attempts):
        try:
            with session.get(url, stream=True, timeout=(30, 600)) as response:
                if response.status_code == 200:
                    partial = target.with_suffix(target.suffix + ".partial")
                    with partial.open("wb") as handle:
                        for block in response.iter_content(chunk_size=1 << 20):
                            if block:
                                handle.write(block)
                    partial.replace(target)
                    return target
                errors.append(f"HTTP {response.status_code}")
                if response.status_code in (400, 401, 403, 404):
                    break
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(2**attempt, 16))
    raise RuntimeError(f"download failed {url}: {'; '.join(errors[-5:])}")


def load_archive(path: Path, symbol: str, date: str, url: str) -> tuple[dict[str, np.ndarray], SourceRecord]:
    day0 = utc_start(date)
    total = np.zeros(BINS_PER_DAY, dtype=np.float64)
    signed = np.zeros(BINS_PER_DAY, dtype=np.float64)
    count = np.zeros(BINS_PER_DAY, dtype=np.int32)
    last = np.full(BINS_PER_DAY, np.nan, dtype=np.float64)
    digest = hashlib.sha256()
    with path.open("rb") as raw:
        for block in iter(lambda: raw.read(1 << 20), b""):
            digest.update(block)
    observed_columns: list[str] | None = None
    rows = 0
    first_ts: float | None = None
    last_ts: float | None = None
    previous: float | None = None
    monotonic = True
    usecols = ["timestamp", "side", "size", "price"]
    for chunk in pd.read_csv(path, compression="gzip", usecols=usecols, chunksize=400_000):
        if observed_columns is None:
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
                observed_columns = next(csv.reader(handle))
        ts = pd.to_numeric(chunk["timestamp"], errors="coerce").to_numpy(np.float64)
        size = pd.to_numeric(chunk["size"], errors="coerce").to_numpy(np.float64)
        price = pd.to_numeric(chunk["price"], errors="coerce").to_numpy(np.float64)
        side = chunk["side"].astype(str).str.lower().to_numpy()
        good = np.isfinite(ts) & np.isfinite(size) & np.isfinite(price) & (size > 0) & (price > 0)
        ts, size, price, side = ts[good], size[good], price[good], side[good]
        if not len(ts):
            continue
        if previous is not None and ts[0] < previous:
            monotonic = False
        if np.any(np.diff(ts) < 0):
            monotonic = False
        previous = float(ts[-1])
        first_ts = float(ts[0]) if first_ts is None else first_ts
        last_ts = float(ts[-1])
        rows += len(ts)
        bins = np.floor((ts - day0) * 10.0 + 1e-9).astype(np.int64)
        inside = (bins >= 0) & (bins < BINS_PER_DAY)
        bins, size, price, side = bins[inside], size[inside], price[inside], side[inside]
        if not len(bins):
            continue
        notional = size * price
        sign = np.where(side == "buy", 1.0, np.where(side == "sell", -1.0, 0.0))
        total += np.bincount(bins, weights=notional, minlength=BINS_PER_DAY)
        signed += np.bincount(bins, weights=notional * sign, minlength=BINS_PER_DAY)
        count += np.bincount(bins, minlength=BINS_PER_DAY).astype(np.int32)
        local = pd.DataFrame({"bin": bins, "price": price}).groupby("bin", sort=False)["price"].last()
        last[local.index.to_numpy(np.int64)] = local.to_numpy(np.float64)
    if rows == 0 or first_ts is None or last_ts is None:
        raise ValueError(f"no usable rows in {path}")
    mark = pd.Series(last).ffill(limit=20).to_numpy(np.float64)
    return {
        "mark": mark,
        "total": total,
        "signed": signed,
        "trade_count": count,
    }, SourceRecord(
        symbol=symbol,
        date=date,
        url=url,
        bytes=path.stat().st_size,
        sha256=digest.hexdigest(),
        rows=rows,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        timestamp_monotonic=monotonic,
        columns=observed_columns or usecols,
    )


def acquire_day(session: requests.Session, cache: Path, date: str) -> tuple[dict[str, dict[str, np.ndarray]], list[SourceRecord]]:
    arrays: dict[str, dict[str, np.ndarray]] = {}
    records: list[SourceRecord] = []
    for symbol in SYMBOLS:
        url = f"{BASE_URL}/{symbol}/{symbol}{date}.csv.gz"
        path = download(session, url, cache / symbol / f"{symbol}{date}.csv.gz")
        arr, record = load_archive(path, symbol, date, url)
        if not record.timestamp_monotonic:
            raise ValueError(f"nonmonotonic source {url}")
        arrays[symbol] = arr
        records.append(record)
        print(json.dumps(asdict(record), sort_keys=True), flush=True)
    return arrays, records


def rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(values).rolling(window, min_periods=1).sum().to_numpy(np.float64)


def rolling_median_positive(values: np.ndarray, window: int, minimum: int) -> np.ndarray:
    series = pd.Series(np.where(values > 0, values, np.nan))
    return series.rolling(window, min_periods=minimum).median().to_numpy(np.float64)


def rolling_pair_sums(x: np.ndarray, y: np.ndarray, window: int) -> dict[str, np.ndarray]:
    valid = np.isfinite(x) & np.isfinite(y)
    m = valid.astype(np.float64)
    xv = np.where(valid, x, 0.0)
    yv = np.where(valid, y, 0.0)
    return {
        "n": rolling_sum(m, window),
        "x": rolling_sum(xv, window),
        "y": rolling_sum(yv, window),
        "xx": rolling_sum(xv * xv, window),
        "yy": rolling_sum(yv * yv, window),
        "xy": rolling_sum(xv * yv, window),
    }


def rolling_triple_moments(b: np.ndarray, e: np.ndarray, f: np.ndarray, window: int) -> dict[str, np.ndarray]:
    valid = np.isfinite(b) & np.isfinite(e) & np.isfinite(f)
    m = valid.astype(np.float64)
    bv = np.where(valid, b, 0.0)
    ev = np.where(valid, e, 0.0)
    fv = np.where(valid, f, 0.0)
    return {
        "n": rolling_sum(m, window),
        "b": rolling_sum(bv, window),
        "e": rolling_sum(ev, window),
        "f": rolling_sum(fv, window),
        "bb": rolling_sum(bv * bv, window),
        "ee": rolling_sum(ev * ev, window),
        "ff": rolling_sum(fv * fv, window),
        "be": rolling_sum(bv * ev, window),
        "bf": rolling_sum(bv * fv, window),
        "ef": rolling_sum(ev * fv, window),
    }


def centered(m: dict[str, np.ndarray], a: str, b: str) -> np.ndarray:
    n = m["n"]
    raw = m[a + b] if a + b in m else m[b + a]
    return raw - np.divide(m[a] * m[b], n, out=np.full_like(n, np.nan), where=n > 0)


def variance(m: dict[str, np.ndarray], a: str) -> np.ndarray:
    n = m["n"]
    return m[a + a] - np.divide(m[a] * m[a], n, out=np.full_like(n, np.nan), where=n > 0)


def window_sum(values: np.ndarray, bins: int) -> np.ndarray:
    prefix = np.concatenate(([0.0], np.cumsum(values, dtype=np.float64)))
    out = np.full(len(values), np.nan, dtype=np.float64)
    idx = np.arange(bins - 1, len(values))
    out[idx] = prefix[idx + 1] - prefix[idx + 1 - bins]
    return out


def window_return(mark: np.ndarray, bins: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(mark)
    end = np.arange(n, dtype=np.int64)
    start = end - bins + 1
    baseline = start - 1
    out = np.full(n, np.nan, dtype=np.float64)
    valid = baseline >= 0
    valid &= np.isfinite(mark)
    valid &= np.isfinite(mark[np.maximum(baseline, 0)])
    valid &= mark > 0
    valid &= mark[np.maximum(baseline, 0)] > 0
    out[valid] = np.log(mark[valid] / mark[baseline[valid]])
    return out, start


def one_second_state(arrays: dict[str, dict[str, np.ndarray]]) -> dict[str, dict[str, np.ndarray]]:
    result: dict[str, dict[str, np.ndarray]] = {}
    for symbol, arr in arrays.items():
        endpoint = arr["mark"][9::10]
        ret = pd.Series(np.log(endpoint)).diff().to_numpy(np.float64)
        result[symbol] = {
            "return": ret,
            "total": arr["total"].reshape(-1, 10).sum(axis=1),
            "trade_count": arr["trade_count"].reshape(-1, 10).sum(axis=1).astype(np.float64),
        }
    return result


def map_prior(values: np.ndarray, start: np.ndarray) -> np.ndarray:
    prior = start // 10 - 1
    out = np.full(len(start), np.nan, dtype=np.float64)
    valid = (prior >= 0) & (prior < len(values))
    out[valid] = values[prior[valid]]
    return out


def coefficients_and_scales(one: dict[str, dict[str, np.ndarray]], follower: str) -> dict[str, np.ndarray]:
    b = one["BTCUSDT"]["return"]
    e = one["ETHUSDT"]["return"]
    f = one[follower]["return"]
    long = rolling_triple_moments(b, e, f, 1800)
    short = rolling_triple_moments(b, e, f, 900)

    def solve(m: dict[str, np.ndarray], minimum: int) -> dict[str, np.ndarray]:
        vb = variance(m, "b")
        ve = variance(m, "e")
        vf = variance(m, "f")
        cbe = centered(m, "b", "e")
        cbf = centered(m, "b", "f")
        cef = centered(m, "e", "f")
        good = (m["n"] >= minimum) & (vb > 1e-16)
        beta_e_b = np.full_like(vb, np.nan)
        beta_f_b = np.full_like(vb, np.nan)
        beta_e_b[good] = np.clip(cbe[good] / vb[good], 0.2, 2.0)
        beta_f_b[good] = np.clip(cbf[good] / vb[good], 0.0, 3.0)
        var_e_res = ve - np.divide(cbe * cbe, vb, out=np.full_like(vb, np.nan), where=vb > 1e-16)
        cov_f_e_res = cef - np.divide(cbf * cbe, vb, out=np.full_like(vb, np.nan), where=vb > 1e-16)
        gamma = np.full_like(vb, np.nan)
        ok_gamma = good & (var_e_res > 1e-16)
        gamma[ok_gamma] = np.clip(cov_f_e_res[ok_gamma] / var_e_res[ok_gamma], -2.0, 3.0)
        denom = np.maximum(m["n"] - 1.0, 1.0)
        return {
            "beta_e_b": beta_e_b,
            "beta_f_b": beta_f_b,
            "gamma": gamma,
            "var_b": np.divide(vb, denom, out=np.full_like(vb, np.nan), where=m["n"] > 1),
            "var_e": np.divide(ve, denom, out=np.full_like(vb, np.nan), where=m["n"] > 1),
            "var_f": np.divide(vf, denom, out=np.full_like(vb, np.nan), where=m["n"] > 1),
            "var_e_res": np.divide(var_e_res, denom, out=np.full_like(vb, np.nan), where=m["n"] > 1),
            "count": m["n"],
        }

    result = solve(long, 1200)
    scale = solve(short, 600)
    result.update({"scale_" + key: value for key, value in scale.items()})
    return result


def activity_and_attention(one: dict[str, dict[str, np.ndarray]], follower: str) -> dict[str, np.ndarray]:
    med_b = rolling_median_positive(one["BTCUSDT"]["total"], 900, 300)
    med_e = rolling_median_positive(one["ETHUSDT"]["total"], 900, 300)
    count_b = rolling_sum(one["BTCUSDT"]["trade_count"], 1800)
    count_e = rolling_sum(one["ETHUSDT"]["trade_count"], 1800)
    count_f = rolling_sum(one[follower]["trade_count"], 1800)
    geometric = np.sqrt(np.maximum(count_b, 0.0) * np.maximum(count_e, 0.0))
    trade_ratio = np.divide(count_f, geometric, out=np.full_like(count_f, np.nan), where=geometric > 0)
    pair_bf = rolling_pair_sums(one["BTCUSDT"]["return"], one[follower]["return"], 900)
    pair_ef = rolling_pair_sums(one["ETHUSDT"]["return"], one[follower]["return"], 900)
    pair_be = rolling_pair_sums(one["BTCUSDT"]["return"], one["ETHUSDT"]["return"], 900)
    var_b = variance(pair_be, "x") / np.maximum(pair_be["n"] - 1, 1)
    var_e = variance(pair_be, "y") / np.maximum(pair_be["n"] - 1, 1)
    var_f_b = variance(pair_bf, "y") / np.maximum(pair_bf["n"] - 1, 1)
    var_f_e = variance(pair_ef, "y") / np.maximum(pair_ef["n"] - 1, 1)
    var_f = np.nanmean(np.vstack([var_f_b, var_f_e]), axis=0)
    leader_sd = np.maximum(np.sqrt(np.maximum(var_b, 0)), np.sqrt(np.maximum(var_e, 0)))
    vol_ratio = np.divide(np.sqrt(np.maximum(var_f, 0)), leader_sd, out=np.full_like(leader_sd, np.nan), where=leader_sd > 0)
    return {"med_b": med_b, "med_e": med_e, "trade_ratio": trade_ratio, "vol_ratio": vol_ratio}


def select_unique(
    mask: np.ndarray,
    gap: np.ndarray,
    start: np.ndarray,
    direction: np.ndarray,
    expected: np.ndarray,
    beta_e_b: np.ndarray,
    beta_f_b: np.ndarray,
    gamma: np.ndarray,
    btc_mark: np.ndarray,
    eth_mark: np.ndarray,
    metadata: dict[str, np.ndarray],
) -> list[dict]:
    candidates = np.flatnonzero(mask & (gap >= FLOORS[0]))
    events: list[dict] = []
    allowed = 0
    for raw in candidates:
        i = int(raw)
        if i < allowed:
            continue
        s = int(start[i])
        base_idx = s - 1
        d = int(direction[i])
        expected0 = abs(float(expected[i]))
        if base_idx < 0 or d == 0 or not math.isfinite(expected0) or expected0 <= 0:
            continue
        if not (np.isfinite(btc_mark[base_idx]) and np.isfinite(eth_mark[base_idx])):
            continue
        run = 0
        release = len(btc_mark)
        be = float(beta_e_b[i])
        bf = float(beta_f_b[i])
        g = float(gamma[i])
        for j in range(i + 1, len(btc_mark)):
            if not (np.isfinite(btc_mark[j]) and np.isfinite(eth_mark[j])):
                run = 0
                continue
            br = math.log(btc_mark[j] / btc_mark[base_idx])
            er = math.log(eth_mark[j] / eth_mark[base_idx])
            exp_j = bf * br + g * (er - be * br)
            run = run + 1 if d * exp_j <= 0.25 * expected0 else 0
            if run >= 10:
                release = j + 1
                break
        allowed = max(i + 1, release)
        row = {
            "decision_bin": i,
            "start_bin": s,
            "release_bin": int(release),
            "direction": d,
            "gap": float(gap[i]),
            "expected": float(expected[i]),
            "beta_eth_btc": be,
            "beta_follower_btc": bf,
            "gamma_follower_eth_idio": g,
        }
        for key, values in metadata.items():
            row[key] = float(values[i]) if np.issubdtype(values.dtype, np.number) else values[i]
        events.append(row)
    return events


def evaluate_day(arrays: dict[str, dict[str, np.ndarray]], date: str) -> tuple[dict[str, int], list[dict]]:
    one = one_second_state(arrays)
    counts: dict[str, int] = {}
    rows: list[dict] = []
    for follower in FOLLOWERS:
        coeff = coefficients_and_scales(one, follower)
        attn = activity_and_attention(one, follower)
        for horizon in HORIZONS:
            bins = horizon * 10
            btc_ret, start = window_return(arrays["BTCUSDT"]["mark"], bins)
            eth_ret, _ = window_return(arrays["ETHUSDT"]["mark"], bins)
            fol_ret, _ = window_return(arrays[follower]["mark"], bins)
            btc_total = window_sum(arrays["BTCUSDT"]["total"], bins)
            eth_total = window_sum(arrays["ETHUSDT"]["total"], bins)
            fol_total = window_sum(arrays[follower]["total"], bins)
            btc_signed = window_sum(arrays["BTCUSDT"]["signed"], bins)
            eth_signed = window_sum(arrays["ETHUSDT"]["signed"], bins)
            fol_signed = window_sum(arrays[follower]["signed"], bins)
            btc_flow = np.divide(btc_signed, btc_total, out=np.full_like(btc_signed, np.nan), where=btc_total > 0)
            eth_flow = np.divide(eth_signed, eth_total, out=np.full_like(eth_signed, np.nan), where=eth_total > 0)
            fol_flow = np.divide(fol_signed, fol_total, out=np.full_like(fol_signed, np.nan), where=fol_total > 0)

            beta_e_b = map_prior(coeff["beta_e_b"], start)
            beta_f_b = map_prior(coeff["beta_f_b"], start)
            gamma = map_prior(coeff["gamma"], start)
            var_b = map_prior(coeff["scale_var_b"], start)
            var_e = map_prior(coeff["scale_var_e"], start)
            var_e_res = map_prior(coeff["scale_var_e_res"], start)
            eth_idio = eth_ret - beta_e_b * btc_ret
            expected = beta_f_b * btc_ret + gamma * eth_idio
            direction = np.sign(expected).astype(np.int8)
            abs_expected = np.abs(expected)
            actual_ratio = np.divide(direction * fol_ret, abs_expected, out=np.full_like(expected, np.nan), where=abs_expected > 1e-12)
            under_gap = direction * (expected - fol_ret)
            over_gap = direction * (fol_ret - expected)
            btc_z = np.divide(np.abs(btc_ret), np.sqrt(np.maximum(var_b, 0) * horizon), out=np.full_like(btc_ret, np.nan), where=var_b > 0)
            eth_z = np.divide(np.abs(eth_ret), np.sqrt(np.maximum(var_e, 0) * horizon), out=np.full_like(eth_ret, np.nan), where=var_e > 0)
            idio_z = np.divide(np.abs(eth_idio), np.sqrt(np.maximum(var_e_res, 0) * horizon), out=np.full_like(eth_idio, np.nan), where=var_e_res > 0)
            med_b = map_prior(attn["med_b"], start)
            med_e = map_prior(attn["med_e"], start)
            combined_activity = np.divide(
                btc_total + eth_total,
                horizon * (med_b + med_e),
                out=np.full_like(btc_total, np.nan),
                where=(med_b + med_e) > 0,
            )
            eth_activity = np.divide(eth_total, horizon * med_e, out=np.full_like(eth_total, np.nan), where=med_e > 0)
            trade_ratio = map_prior(attn["trade_ratio"], start)
            vol_ratio = map_prior(attn["vol_ratio"], start)
            attention = (trade_ratio >= 0.75) & (vol_ratio >= 0.8)
            same_direction = (np.sign(btc_ret) == np.sign(eth_ret)) & (np.sign(btc_ret) != 0)
            consensus_direction = np.sign(btc_ret).astype(np.int8)
            consensus = (
                same_direction
                & (direction == consensus_direction)
                & (btc_z >= 2.5)
                & (eth_z >= 2.5)
                & (consensus_direction * btc_flow >= 0.3)
                & (consensus_direction * eth_flow >= 0.3)
                & (combined_activity >= 1.5)
                & attention
            )
            idio_direction = np.sign(eth_idio).astype(np.int8)
            eth_idiosyncratic = (
                (idio_direction != 0)
                & (direction == idio_direction)
                & (idio_z >= 3.0)
                & (btc_z <= 1.5)
                & (idio_direction * eth_flow >= 0.5)
                & (np.abs(eth_idio) > np.abs(beta_e_b * btc_ret))
                & (eth_activity >= 1.5)
                & attention
            )
            finite = (
                np.isfinite(expected)
                & np.isfinite(fol_ret)
                & np.isfinite(actual_ratio)
                & np.isfinite(fol_flow)
                & np.isfinite(beta_e_b)
                & np.isfinite(beta_f_b)
                & np.isfinite(gamma)
            )
            metadata = {
                "btc_return": btc_ret,
                "eth_return": eth_ret,
                "eth_idiosyncratic_return": eth_idio,
                "follower_return": fol_ret,
                "actual_to_expected_ratio": actual_ratio,
                "btc_z": btc_z,
                "eth_z": eth_z,
                "eth_idiosyncratic_z": idio_z,
                "btc_flow": btc_flow,
                "eth_flow": eth_flow,
                "follower_flow": fol_flow,
                "combined_activity": combined_activity,
                "eth_activity": eth_activity,
                "follower_trade_ratio": trade_ratio,
                "follower_vol_ratio": vol_ratio,
            }
            specifications = (
                ("consensus_underreaction", consensus & finite & (actual_ratio <= 0.75) & (direction * fol_flow <= 0.5), under_gap),
                ("consensus_overreaction", consensus & finite & (actual_ratio >= 1.25) & (direction * fol_flow >= 0.5), over_gap),
                ("eth_idiosyncratic_underreaction", eth_idiosyncratic & finite & (actual_ratio <= 0.75) & (direction * fol_flow <= 0.5), under_gap),
                ("eth_idiosyncratic_overreaction", eth_idiosyncratic & finite & (actual_ratio >= 1.25) & (direction * fol_flow >= 0.5), over_gap),
            )
            for family, mask, gap in specifications:
                events = select_unique(
                    mask,
                    gap,
                    start,
                    direction,
                    expected,
                    beta_e_b,
                    beta_f_b,
                    gamma,
                    arrays["BTCUSDT"]["mark"],
                    arrays["ETHUSDT"]["mark"],
                    metadata,
                )
                for floor in FLOORS:
                    key = f"{family}|{follower}|{date}|h{horizon}|gap{int(round(floor * 10000))}bp"
                    counts[key] = sum(event["gap"] >= floor for event in events)
                for event in events:
                    rows.append({
                        "family": family,
                        "symbol": follower,
                        "date": date,
                        "horizon": horizon,
                        **event,
                    })
            del btc_ret, eth_ret, fol_ret, btc_total, eth_total, fol_total
            del btc_signed, eth_signed, fol_signed, beta_e_b, beta_f_b, gamma
            del var_b, var_e, var_e_res, eth_idio, expected, direction, abs_expected
            gc.collect()
        del coeff, attn
        gc.collect()
    return counts, rows


def summarize_family(counts: dict[str, int], dates: tuple[str, ...], family: str, max_share: float) -> tuple[dict, dict, bool]:
    date12 = {date: 0 for date in dates}
    cells = {f"{symbol}|{date}": 0 for symbol in FOLLOWERS for date in dates}
    total12 = 0
    total24 = 0
    for key, value in counts.items():
        fam, symbol, date, _, floor = key.split("|")
        if fam != family:
            continue
        if floor == "gap12bp":
            total12 += value
            date12[date] += value
            cells[f"{symbol}|{date}"] += value
        elif floor == "gap24bp":
            total24 += value
    share = max(date12.values()) / total12 if total12 else 1.0
    dates_three = sum(value >= 3 for value in date12.values())
    cells_three = sum(value >= 3 for value in cells.values())
    aggregate = {
        "total_12bp": total12,
        "total_24bp": total24,
        "date_12bp": date12,
        "follower_date_12bp": cells,
        "dates_with_at_least_3_12bp": dates_three,
        "follower_date_cells_with_at_least_3_12bp": cells_three,
        "maximum_single_date_share_12bp": share,
    }
    checks = {
        "total_12bp_at_least_15": total12 >= 15,
        "total_24bp_at_least_4": total24 >= 4,
        "at_least_two_dates_with_3_12bp": dates_three >= 2,
        "at_least_two_follower_date_cells_with_3_12bp": cells_three >= 2,
        "maximum_single_date_share": share <= max_share,
    }
    return aggregate, checks, all(checks.values())


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def source_manifest(records: list[SourceRecord]) -> str:
    payload = json.dumps([asdict(record) for record in records], sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def run_stage(session: requests.Session, cache: Path, dates: tuple[str, ...]) -> tuple[dict[str, int], list[dict], list[SourceRecord]]:
    counts: dict[str, int] = {}
    rows: list[dict] = []
    records: list[SourceRecord] = []
    for date in dates:
        arrays, day_records = acquire_day(session, cache, date)
        day_counts, day_rows = evaluate_day(arrays, date)
        counts.update(day_counts)
        rows.extend(day_rows)
        records.extend(day_records)
        del arrays
        gc.collect()
    return counts, rows, records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-twofactor-microshock/1.0"
        screen_counts, screen_rows, screen_sources = run_stage(session, args.cache, SCREEN_DATES)
        family_results: dict[str, dict] = {}
        passing: list[str] = []
        for family in FAMILIES:
            aggregate, checks, passed = summarize_family(screen_counts, SCREEN_DATES, family, 0.7)
            family_results[family] = {"aggregate": aggregate, "gate_checks": checks, "gate_passed": passed}
            if passed:
                passing.append(family)
        selected: str | None = None
        if passing:
            selected = sorted(
                passing,
                key=lambda family: (
                    -family_results[family]["aggregate"]["total_24bp"],
                    -family_results[family]["aggregate"]["dates_with_at_least_3_12bp"],
                    -family_results[family]["aggregate"]["total_12bp"],
                    family,
                ),
            )[0]
        screen = {
            "schema_version": 1,
            "claim_id": CLAIM,
            "stage": "TWO_FACTOR_FAMILY_OPPORTUNITY_SCREEN",
            "status": "FAMILY_SELECTED" if selected else "NO_FAMILY_PASSED",
            "selected_family": selected,
            "family_results": family_results,
            "unique_event_counts": screen_counts,
            "sources": [asdict(record) for record in screen_sources],
            "source_manifest_sha256": source_manifest(screen_sources),
            "pnl_computed": False,
            "funding_opened": False,
            "entry_exit_strategy_frozen": False,
            "2024_2026_opened": False,
            "orders_submitted": False,
        }
        first = args.output / "stage1_screen"
        first.mkdir(parents=True, exist_ok=True)
        (first / "result.json").write_text(json.dumps(screen, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_rows(first / "events.csv", screen_rows)
        confirmation: dict | None = None
        if selected:
            confirm_counts, confirm_rows, confirm_sources = run_stage(session, args.cache, CONFIRM_DATES)
            aggregate, checks, passed = summarize_family(confirm_counts, CONFIRM_DATES, selected, 0.6)
            confirmation = {
                "schema_version": 1,
                "claim_id": CLAIM,
                "stage": "SELECTED_TWO_FACTOR_FAMILY_CONFIRMATION",
                "selected_family": selected,
                "status": "CONFIRMATION_PASS" if passed else "CONFIRMATION_FAIL",
                "gate_passed": passed,
                "aggregate": aggregate,
                "gate_checks": checks,
                "unique_event_counts": {key: value for key, value in confirm_counts.items() if key.startswith(selected + "|")},
                "sources": [asdict(record) for record in confirm_sources],
                "source_manifest_sha256": source_manifest(confirm_sources),
                "pnl_computed": False,
                "funding_opened": False,
                "entry_exit_strategy_frozen": False,
                "2024_2026_opened": False,
                "orders_submitted": False,
                "next_action": "Freeze a one-global-slot 100/300ms state-exit PnL contract before any additional data." if passed else "Retire the exact two-factor dependency without adjacent-threshold tuning.",
            }
            second = args.output / "stage2_confirmation"
            second.mkdir(parents=True, exist_ok=True)
            (second / "result.json").write_text(json.dumps(confirmation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            write_rows(second / "events.csv", [row for row in confirm_rows if row["family"] == selected])
    decision = {
        "schema_version": 1,
        "claim_id": CLAIM,
        "selected_family": selected,
        "confirmation_opened": selected is not None,
        "confirmation_passed": bool(confirmation and confirmation["gate_passed"]),
        "status": "CONFIRMED_OPPORTUNITY" if confirmation and confirmation["gate_passed"] else "TESTED_BELOW_GATE",
        "pnl_computed": False,
        "2024_2026_opened": False,
        "orders_submitted": False,
    }
    path = args.output / "decision.json"
    path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "decision.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "  decision.json\n", encoding="utf-8")
    print(json.dumps(decision, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
