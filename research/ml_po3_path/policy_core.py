"""Causal core for RES-20260729-ML-PO3-PATH-001.

The module intentionally contains only the final active-day accepted-distribution
information unit.  Exploratory rejection, partial-runner and volatility-threshold
routes are documented as rejected results rather than retained as strategy options.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

MINUTE_MS = 60_000


@dataclass(frozen=True)
class ExecutionContract:
    maker_fee: float = 0.0002
    taker_fee: float = 0.00055
    stop_slippage: float = 0.0002
    passive_penetration: float = 0.0001
    risk_fraction: float = 0.005
    notional_cap: float = 3.0
    activation_delay_ms: int = 500

    @property
    def target_cost(self) -> float:
        return 2.0 * self.maker_fee

    @property
    def stop_cost(self) -> float:
        return self.maker_fee + self.taker_fee + self.stop_slippage


FEATURE_COLUMNS = (
    "symbol_eth", "direction", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "month_sin", "month_cos", "acc_efficiency", "acc_rotations",
    "manip_depth", "outside_n", "trigger_body_dir", "trigger_close_dir",
    "trigger_range_rel", "oi_change", "bias_start", "bias_trigger",
    "bias_change", "post_path_eff", "period_phase", "break_to_trigger_bars",
    "acc_width_pct", "acc_close_loc", "width_rel_prev20", "width_rel_prev60",
    "prev_period_ret", "prev3_period_ret", "acc_volume_z", "stop_distance",
    "target_distance", "geometry_rr",
)


def _median_range(frame: pd.DataFrame) -> float:
    value = (frame["high"] - frame["low"]).median()
    return float(value) if pd.notna(value) else np.nan


def detect_accepted_distribution_events(
    bars_5m: pd.DataFrame,
    *,
    symbol: str,
    accumulation_minutes: int = 240,
) -> pd.DataFrame:
    """Return at most one accepted-distribution event per active UTC day.

    Only completed rows are usable.  The first ``accumulation_minutes`` form a
    frozen range.  Acceptance requires two *consecutive* completed closes outside
    the same side of that range.  A later break of the opposite side invalidates
    the period instead of being relabelled after the fact.
    """
    required = {
        "start_time_ms", "available_at_ms", "open", "high", "low", "close",
        "volume", "is_complete",
    }
    missing = required.difference(bars_5m.columns)
    if missing:
        raise ValueError(f"missing 5m columns: {sorted(missing)}")
    if accumulation_minutes % 5:
        raise ValueError("accumulation_minutes must be divisible by five")

    bars = bars_5m.sort_values("start_time_ms", kind="stable").reset_index(drop=True)
    day_ms = 86_400_000
    acc_n = accumulation_minutes // 5
    day_key = (bars.start_time_ms.to_numpy(np.int64) // day_ms) * day_ms
    rows: list[dict] = []

    # Context is computed from completed prior days only.
    daily = bars.assign(day_start_ms=day_key).groupby("day_start_ms", sort=True)
    day_ranges = daily.apply(lambda g: float(g.high.max() - g.low.min()), include_groups=False)
    day_returns = daily.apply(lambda g: float(g.close.iloc[-1] / g.open.iloc[0] - 1.0), include_groups=False)
    day_keys = day_ranges.index.to_numpy(np.int64)
    range_series = pd.Series(day_ranges.to_numpy(float), index=day_keys)
    ret_series = pd.Series(day_returns.to_numpy(float), index=day_keys)

    for day_start, g in bars.assign(day_start_ms=day_key).groupby("day_start_ms", sort=True):
        g = g.reset_index(drop=True)
        if len(g) < acc_n + 2:
            continue
        acc = g.iloc[:acc_n]
        if not bool(acc.is_complete.all()) or acc[["open", "high", "low", "close"]].isna().any().any():
            continue
        ah, al = float(acc.high.max()), float(acc.low.min())
        aopen, aclose = float(acc.open.iloc[0]), float(acc.close.iloc[-1])
        width = ah - al
        if not np.isfinite(width) or width <= 0 or aopen <= 0:
            continue

        close_path = np.r_[aopen, acc.close.to_numpy(float)]
        path = float(np.abs(np.diff(close_path)).sum())
        delta = np.diff(acc.close.to_numpy(float))
        signs = np.sign(delta)
        signs = signs[signs != 0]
        rotations = int(np.sum(signs[1:] != signs[:-1])) if len(signs) > 1 else 0
        acc_eff = abs(aclose - aopen) / max(path, 1e-12)
        acc_close_loc = (aclose - al) / width

        prior = range_series.loc[range_series.index < day_start]
        prev20 = float(prior.tail(20).median()) if len(prior) >= 10 else np.nan
        prev60 = float(prior.tail(60).median()) if len(prior) >= 30 else np.nan
        prior_ret = ret_series.loc[ret_series.index < day_start]
        prev_ret = float(prior_ret.iloc[-1]) if len(prior_ret) else np.nan
        prev3_ret = float(np.prod(1.0 + prior_ret.tail(3).to_numpy()) - 1.0) if len(prior_ret) >= 3 else np.nan

        acc_volumes = []
        earlier_days = [k for k in day_keys if k < day_start][-60:]
        for k in earlier_days:
            h = bars[day_key == k].iloc[:acc_n]
            if len(h) == acc_n and bool(h.is_complete.all()):
                acc_volumes.append(float(h.volume.sum()))
        if len(acc_volumes) >= 30:
            lv = np.log1p(np.asarray(acc_volumes))
            acc_volume_z = float((np.log1p(float(acc.volume.sum())) - lv.mean()) / max(lv.std(ddof=1), 1e-12))
        else:
            acc_volume_z = np.nan

        side = 0
        first_break = -1
        extreme = np.nan
        consecutive = 0
        post_path = 0.0
        post_start = aclose
        previous_close = post_start
        for j in range(acc_n, len(g)):
            r = g.iloc[j]
            if not bool(r.is_complete) or pd.isna(r.high) or pd.isna(r.low) or pd.isna(r.close):
                continue
            post_path += abs(float(r.close) - previous_close)
            previous_close = float(r.close)
            upper, lower = float(r.high) > ah, float(r.low) < al
            if side == 0:
                if upper and lower:
                    break
                if not upper and not lower:
                    continue
                side = 1 if upper else -1
                first_break = j
                extreme = float(r.high if side > 0 else r.low)
            else:
                if side > 0:
                    extreme = max(extreme, float(r.high))
                    if lower:
                        break
                else:
                    extreme = min(extreme, float(r.low))
                    if upper:
                        break

            outside = float(r.close) > ah if side > 0 else float(r.close) < al
            consecutive = consecutive + 1 if outside else 0
            if consecutive < 2:
                continue

            candle_range = float(r.high - r.low)
            body = float(r.close - r.open)
            trigger_direction = side
            close_dir = ((float(r.close) - float(r.low)) / max(candle_range, 1e-12)
                         if side > 0 else
                         (float(r.high) - float(r.close)) / max(candle_range, 1e-12))
            prior12 = g.iloc[max(0, j - 12):j]
            median_range = _median_range(prior12)
            depth = ((extreme - ah) / width if side > 0 else (al - extreme) / width)
            rows.append({
                "symbol": symbol,
                "period_start_ms": int(day_start),
                "decision_time_ms": int(r.available_at_ms),
                "break_start_ms": int(g.start_time_ms.iloc[first_break]),
                "trigger_start_ms": int(r.start_time_ms),
                "direction": int(side),
                "acc_high": ah, "acc_low": al, "acc_open": aopen,
                "acc_close": aclose, "acc_width": width,
                "acc_width_pct": width / aopen,
                "acc_efficiency": acc_eff,
                "acc_rotations": rotations,
                "acc_close_loc": acc_close_loc,
                "manip_depth": depth,
                "outside_n": consecutive,
                "trigger_open": float(r.open),
                "trigger_close": float(r.close),
                "trigger_body_dir": trigger_direction * body / max(candle_range, 1e-12),
                "trigger_close_dir": close_dir,
                "trigger_range_rel": candle_range / max(median_range, 1e-12),
                "post_path_eff": abs(float(r.close) - post_start) / max(post_path, 1e-12),
                "period_phase": (j + 1) / len(g),
                "break_to_trigger_bars": j - first_break,
                "width_rel_prev20": width / prev20 if np.isfinite(prev20) and prev20 > 0 else np.nan,
                "width_rel_prev60": width / prev60 if np.isfinite(prev60) and prev60 > 0 else np.nan,
                "prev_period_ret": prev_ret,
                "prev3_period_ret": prev3_ret,
                "acc_volume_z": acc_volume_z,
            })
            break
    return pd.DataFrame(rows)


def attach_positioning(events: pd.DataFrame, oi_5m: pd.DataFrame, ratio_5m: pd.DataFrame) -> pd.DataFrame:
    """Attach only observations available by the event decision timestamp."""
    e = events.sort_values("decision_time_ms").copy()
    oi = oi_5m.sort_values("available_at_ms")[["available_at_ms", "open_interest"]]
    ratio = ratio_5m.sort_values("available_at_ms")[["available_at_ms", "buy_ratio", "sell_ratio"]]
    e = pd.merge_asof(e, oi, left_on="decision_time_ms", right_on="available_at_ms", direction="backward")
    e = pd.merge_asof(e, ratio, left_on="decision_time_ms", right_on="available_at_ms", direction="backward", suffixes=("_oi", "_ratio"))
    e["bias_trigger"] = e.buy_ratio - e.sell_ratio
    # Start values must be looked up separately at the frozen period start.
    starts = events[["period_start_ms"]].sort_values("period_start_ms")
    start_oi = pd.merge_asof(starts, oi, left_on="period_start_ms", right_on="available_at_ms", direction="backward")
    start_ratio = pd.merge_asof(starts, ratio, left_on="period_start_ms", right_on="available_at_ms", direction="backward")
    e["oi_start"] = start_oi.open_interest.to_numpy()
    e["oi_change"] = np.log(e.open_interest / e.oi_start)
    e["bias_start"] = (start_ratio.buy_ratio - start_ratio.sell_ratio).to_numpy()
    return e.drop(columns=[c for c in e.columns if c.startswith("available_at_ms")], errors="ignore")


def define_order_geometry(events: pd.DataFrame) -> pd.DataFrame:
    e = events.copy()
    boundary = np.where(e.direction > 0, e.acc_high, e.acc_low)
    e["limit_price"] = 0.5 * (boundary + e.trigger_close)
    e["stop"] = np.where(e.direction > 0, e.acc_low, e.acc_high)
    e["target"] = np.where(e.direction > 0, e.acc_high + e.acc_width, e.acc_low - e.acc_width)
    e["stop_distance"] = np.abs(e.stop / e.limit_price - 1.0)
    e["target_distance"] = np.abs(e.target / e.limit_price - 1.0)
    return e


def simulate_limit_lifecycle(
    event: pd.Series,
    minute: pd.DataFrame,
    funding: pd.DataFrame,
    contract: ExecutionContract = ExecutionContract(),
) -> dict:
    """Simulate one resting entry; pending expiry never forces a filled exit."""
    activation = int(event.decision_time_ms) + contract.activation_delay_ms
    m = minute[(minute.start_time_ms >= activation) & minute.observed].sort_values("start_time_ms")
    pending_end = int(event.period_start_ms) + 86_400_000 - 1
    d, lp, st, tg = int(event.direction), float(event.limit_price), float(event.stop), float(event.target)
    fill_time = None
    for r in m.itertuples(index=False):
        if fill_time is None and int(r.start_time_ms) > pending_end:
            return {"status": "pending_expired", "account_return": 0.0, "lifecycle_end_ms": pending_end}
        if fill_time is None:
            touched = float(r.low) <= lp * (1.0 - contract.passive_penetration) if d > 0 else float(r.high) >= lp * (1.0 + contract.passive_penetration)
            invalid = float(r.low) <= st if d > 0 else float(r.high) >= st
            delivered = float(r.high) >= tg if d > 0 else float(r.low) <= tg
            if touched and (invalid or delivered):
                return {"status": "ambiguous_before_fill", "account_return": 0.0, "lifecycle_end_ms": int(r.start_time_ms)}
            if invalid or delivered:
                return {"status": "invalid_or_delivered_before_fill", "account_return": 0.0, "lifecycle_end_ms": int(r.start_time_ms)}
            if touched:
                fill_time = int(r.start_time_ms)
                continue
        else:
            hit_stop = float(r.low) <= st if d > 0 else float(r.high) >= st
            hit_target = float(r.high) >= tg if d > 0 else float(r.low) <= tg
            if not hit_stop and not hit_target:
                continue
            # Adverse-first when minute data cannot order both boundaries.
            won = not hit_stop and hit_target
            exit_price = tg if won else st
            exit_time = int(r.start_time_ms)
            f = funding[(funding.timestamp_ms > fill_time) & (funding.timestamp_ms <= exit_time)]
            funding_sum = float(f.funding_rate.sum())
            gross = d * (exit_price / lp - 1.0) - d * funding_sum
            cost = contract.target_cost if won else contract.stop_cost
            unit_return = gross - cost
            notional = min(contract.notional_cap, contract.risk_fraction / (abs(st / lp - 1.0) + contract.stop_cost))
            return {
                "status": "target" if won else "stop",
                "fill_time_ms": fill_time,
                "exit_time_ms": exit_time,
                "lifecycle_end_ms": exit_time,
                "funding_sum": funding_sum,
                "unit_return": unit_return,
                "notional_mult": notional,
                "account_return": notional * unit_return,
            }
    return {"status": "unresolved", "account_return": np.nan, "lifecycle_end_ms": int(m.start_time_ms.iloc[-1]) if len(m) else activation}


def add_ml_features(events: pd.DataFrame, contract: ExecutionContract = ExecutionContract()) -> pd.DataFrame:
    x = events.copy()
    dt = pd.to_datetime(x.decision_time_ms, unit="ms", utc=True)
    x["symbol_eth"] = (x.symbol == "ETHUSDT").astype(int)
    x["hour_sin"], x["hour_cos"] = np.sin(2*np.pi*dt.dt.hour/24), np.cos(2*np.pi*dt.dt.hour/24)
    x["dow_sin"], x["dow_cos"] = np.sin(2*np.pi*dt.dt.dayofweek/7), np.cos(2*np.pi*dt.dt.dayofweek/7)
    x["month_sin"], x["month_cos"] = np.sin(2*np.pi*(dt.dt.month-1)/12), np.cos(2*np.pi*(dt.dt.month-1)/12)
    x["bias_change"] = x.bias_trigger - x.bias_start
    x["geometry_rr"] = x.target_distance / (x.stop_distance + contract.stop_cost)
    return x


def global_route(candidates: pd.DataFrame, score_column: str, threshold: float) -> pd.DataFrame:
    """Replay a single pending/open slot without future-aware simultaneous choice."""
    e = candidates[candidates[score_column] > threshold].sort_values(
        ["activation_time_ms", score_column, "symbol"], ascending=[True, False, True]
    )
    selected = []
    busy_until = -1
    for activation, group in e.groupby("activation_time_ms", sort=True):
        if int(activation) < busy_until:
            continue
        row = group.iloc[0]
        selected.append(row)
        busy_until = int(row.lifecycle_end_ms) + 1
    return pd.DataFrame(selected).reset_index(drop=True) if selected else pd.DataFrame(columns=e.columns)
