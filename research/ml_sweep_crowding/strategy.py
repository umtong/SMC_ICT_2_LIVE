"""Causal SMC/ICT sweep events, labels, and fixed pooled ML model."""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from .common import (
    EPS,
    FEATURE_COLUMNS,
    EconomicGateError,
    MarketData,
    SourceGateError,
    StageSpec,
)


def next_observable_minute(decision_ts: pd.Timestamp, latency_ms: int) -> pd.Timestamp:
    active = decision_ts + pd.Timedelta(milliseconds=latency_ms)
    return active.ceil("1min")


def locate_position(index: pd.DatetimeIndex, timestamp: pd.Timestamp) -> int | None:
    value = index.get_indexer([timestamp])[0]
    return None if value < 0 else int(value)


def funding_between(
    market: MarketData, entry: pd.Timestamp, exit_: pd.Timestamp, direction: int
) -> float:
    cum = market.funding_long_cum
    if exit_ < cum.index[0] or entry > cum.index[-1]:
        return 0.0
    exit_loc = cum.index.searchsorted(exit_, side="right") - 1
    entry_loc = cum.index.searchsorted(entry, side="right") - 1
    exit_value = float(cum.iloc[exit_loc]) if exit_loc >= 0 else 0.0
    entry_value = float(cum.iloc[entry_loc]) if entry_loc >= 0 else 0.0
    return float(direction) * (exit_value - entry_value)


def resolve_candidate(
    market: MarketData,
    entry_ts: pd.Timestamp,
    stop_raw: float,
    target_raw: float,
    direction: int,
) -> dict[str, Any]:
    one = market.one_minute
    start_pos = locate_position(one.index, entry_ts)
    if start_pos is None:
        return {"resolution": "invalid", "path_invalid": True}
    consecutive_missing = 0
    opens = market.minute_open
    highs = market.minute_high
    lows = market.minute_low
    closes = market.minute_close
    for pos in range(start_pos, len(one)):
        ts = one.index[pos]
        open_, high, low, close_ = opens[pos], highs[pos], lows[pos], closes[pos]
        if not (
            np.isfinite(open_)
            and np.isfinite(high)
            and np.isfinite(low)
            and np.isfinite(close_)
        ):
            consecutive_missing += 1
            if consecutive_missing > 2:
                return {"resolution": "invalid", "path_invalid": True}
            continue
        consecutive_missing = 0
        open_, high, low = float(open_), float(high), float(low)
        if direction == 1:
            stop_gap = open_ <= stop_raw
            target_gap = open_ >= target_raw
            stop_touch = low <= stop_raw
            target_touch = high >= target_raw
        else:
            stop_gap = open_ >= stop_raw
            target_gap = open_ <= target_raw
            stop_touch = high >= stop_raw
            target_touch = low <= target_raw
        if stop_gap:
            return {
                "resolution": "stop",
                "exit_ts": ts,
                "exit_raw": open_,
                "path_invalid": False,
            }
        if target_gap:
            return {
                "resolution": "target",
                "exit_ts": ts,
                "exit_raw": target_raw,
                "path_invalid": False,
            }
        if stop_touch:
            return {
                "resolution": "stop",
                "exit_ts": ts,
                "exit_raw": stop_raw,
                "path_invalid": False,
            }
        if target_touch:
            return {
                "resolution": "target",
                "exit_ts": ts,
                "exit_raw": target_raw,
                "path_invalid": False,
            }
    return {
        "resolution": "unresolved",
        "exit_ts": pd.NaT,
        "exit_raw": np.nan,
        "path_invalid": False,
    }


def build_candidates_for_symbol(
    market: MarketData, contract: Mapping[str, Any]
) -> pd.DataFrame:
    frame = market.five_minute.copy()
    high_sweep = (frame["high"] > frame["prior_high"]) & ~(
        frame["low"] < frame["prior_low"]
    )
    low_sweep = (frame["low"] < frame["prior_low"]) & ~(
        frame["high"] > frame["prior_high"]
    )
    events = frame.loc[(high_sweep | low_sweep) & frame["atr"].gt(0)].copy()
    if events.empty:
        raise EconomicGateError(f"{market.symbol} has no eligible sweeps")
    rows: list[dict[str, Any]] = []
    latency_ms = int(contract["execution"]["latency_ms"])
    buffer_atr = float(contract["signal"]["stop_buffer_atr"])
    target_r = float(contract["signal"]["target_r"])
    for signal_ts, event in events.iterrows():
        decision_ts = signal_ts + pd.Timedelta(
            minutes=int(contract["signal"]["bar_minutes"])
        )
        entry_ts = next_observable_minute(decision_ts, latency_ms)
        if entry_ts not in market.one_minute.index:
            continue
        entry_raw = market.one_minute.at[entry_ts, "open"]
        if not np.isfinite(entry_raw):
            continue
        atr = float(event.atr)
        is_high = bool(event.high > event.prior_high)
        sweep_side = 1 if is_high else -1
        sweep_depth = (
            (float(event.high) - float(event.prior_high)) / atr
            if is_high
            else (float(event.prior_low) - float(event.low)) / atr
        )
        close_location = (float(event.close) - float(event.low)) / max(
            float(event.high - event.low), EPS
        )
        reclaim = (
            (float(event.prior_high) - float(event.close)) / atr
            if is_high
            else (float(event.close) - float(event.prior_low)) / atr
        )
        body = abs(float(event.close - event.open)) / atr
        upper_wick = (
            float(event.high) - max(float(event.open), float(event.close))
        ) / atr
        lower_wick = (
            min(float(event.open), float(event.close)) - float(event.low)
        ) / atr
        range_atr = float(event.high - event.low) / atr
        distance_opposite = (
            (float(event.close) - float(event.prior_low)) / atr
            if is_high
            else (float(event.prior_high) - float(event.close)) / atr
        )
        event_id = f"{market.symbol}|{signal_ts.isoformat()}"
        for is_continuation in (1, 0):
            direction = sweep_side if is_continuation else -sweep_side
            if is_high and direction == 1:
                stop_raw = (
                    min(float(event.low), float(event.prior_high))
                    - buffer_atr * atr
                )
            elif is_high and direction == -1:
                stop_raw = float(event.high) + buffer_atr * atr
            elif (not is_high) and direction == -1:
                stop_raw = (
                    max(float(event.high), float(event.prior_low))
                    + buffer_atr * atr
                )
            else:
                stop_raw = float(event.low) - buffer_atr * atr
            stop_distance = direction * (float(entry_raw) - stop_raw)
            if not np.isfinite(stop_distance) or stop_distance <= 0:
                continue
            target_raw = float(entry_raw) + direction * target_r * stop_distance
            resolved = resolve_candidate(
                market, entry_ts, stop_raw, target_raw, direction
            )
            row: dict[str, Any] = {
                "event_id": event_id,
                "symbol": market.symbol,
                "signal_ts": signal_ts,
                "decision_ts": decision_ts,
                "entry_ts": entry_ts,
                "entry_raw": float(entry_raw),
                "stop_raw": float(stop_raw),
                "target_raw": float(target_raw),
                "sweep_side": float(sweep_side),
                "candidate_direction": float(direction),
                "is_continuation": float(is_continuation),
                "sweep_depth_atr": float(sweep_depth),
                "close_location": float(close_location),
                "reclaim_atr": float(reclaim),
                "body_atr": float(body),
                "upper_wick_atr": float(upper_wick),
                "lower_wick_atr": float(lower_wick),
                "range_atr": float(range_atr),
                "volume_z_24h": event.get("volume_z_24h", np.nan),
                "return_5m_atr": event.get("return_5m_atr", np.nan),
                "return_1h_atr": event.get("return_1h_atr", np.nan),
                "realized_vol_1h": event.get("realized_vol_1h", np.nan),
                "distance_opposing_liquidity_atr": float(distance_opposite),
                "open_interest_log": event.get("open_interest_log", np.nan),
                "open_interest_change_15m": event.get(
                    "open_interest_change_15m", np.nan
                ),
                "open_interest_change_1h": event.get(
                    "open_interest_change_1h", np.nan
                ),
                "open_interest_change_6h": event.get(
                    "open_interest_change_6h", np.nan
                ),
                "open_interest_z_24h": event.get("open_interest_z_24h", np.nan),
                "top_account_ls": event.get("top_account_ls", np.nan),
                "top_position_ls": event.get("top_position_ls", np.nan),
                "global_account_ls": event.get("global_account_ls", np.nan),
                "taker_buy_sell_ratio": event.get("taker_buy_sell_ratio", np.nan),
                "top_account_change_1h": event.get(
                    "top_account_change_1h", np.nan
                ),
                "top_position_change_1h": event.get(
                    "top_position_change_1h", np.nan
                ),
                "global_account_change_1h": event.get(
                    "global_account_change_1h", np.nan
                ),
                "taker_ratio_change_1h": event.get(
                    "taker_ratio_change_1h", np.nan
                ),
                "top_account_z_24h": event.get("top_account_z_24h", np.nan),
                "top_position_z_24h": event.get("top_position_z_24h", np.nan),
                "global_account_z_24h": event.get("global_account_z_24h", np.nan),
                "taker_ratio_z_24h": event.get("taker_ratio_z_24h", np.nan),
                "asset_flag": event.get("asset_flag", np.nan),
                "resolution": resolved.get("resolution"),
                "exit_ts_full": resolved.get("exit_ts", pd.NaT),
                "exit_raw_full": resolved.get("exit_raw", np.nan),
                "path_invalid": bool(resolved.get("path_invalid", False)),
            }
            row["oi_x_sweep"] = (
                row["open_interest_change_1h"] * row["sweep_depth_atr"]
            )
            row["oi_x_reclaim"] = (
                row["open_interest_change_1h"] * row["reclaim_atr"]
            )
            crowd_log = (
                np.log(row["top_position_ls"])
                if row["top_position_ls"] > 0
                else np.nan
            )
            taker_log = (
                np.log(row["taker_buy_sell_ratio"])
                if row["taker_buy_sell_ratio"] > 0
                else np.nan
            )
            row["crowding_x_direction"] = crowd_log * direction
            row["taker_x_direction"] = taker_log * direction
            row["crowding_flow_disagreement"] = (
                crowd_log - taker_log
            ) * direction
            rows.append(row)
    candidates = pd.DataFrame(rows)
    if candidates.empty:
        raise EconomicGateError(
            f"{market.symbol} candidates empty after stop validation"
        )
    metric_presence = (
        candidates[
            ["open_interest_log", "top_position_ls", "taker_buy_sell_ratio"]
        ]
        .notna()
        .all(axis=1)
        .mean()
    )
    if metric_presence < 0.90:
        raise SourceGateError(
            f"{market.symbol} event-level delayed metric availability "
            f"{metric_presence:.2%} below 90%"
        )
    return candidates


def prepare_matrix(frame: pd.DataFrame) -> np.ndarray:
    return (
        frame[FEATURE_COLUMNS]
        .replace([np.inf, -np.inf], np.nan)
        .to_numpy(dtype=np.float64)
    )


def fit_model(
    frame: pd.DataFrame, contract: Mapping[str, Any]
) -> HistGradientBoostingClassifier:
    labels = (frame["resolution"] == "target").astype(int).to_numpy()
    if len(frame) < 500 or len(np.unique(labels)) < 2:
        raise EconomicGateError(
            f"insufficient resolved training population: n={len(frame)}"
        )
    spec = contract["model"]
    model = HistGradientBoostingClassifier(
        learning_rate=float(spec["learning_rate"]),
        max_iter=int(spec["max_iter"]),
        max_leaf_nodes=int(spec["max_leaf_nodes"]),
        min_samples_leaf=int(spec["min_samples_leaf"]),
        l2_regularization=float(spec["l2_regularization"]),
        early_stopping=bool(spec["early_stopping"]),
        random_state=int(spec["random_state"]),
    )
    model.fit(prepare_matrix(frame), labels)
    return model


def score_candidates(
    model: HistGradientBoostingClassifier, frame: pd.DataFrame
) -> pd.DataFrame:
    scored = frame.copy()
    scored["probability"] = model.predict_proba(prepare_matrix(scored))[:, 1]
    return scored


def select_event_actions(
    scored: pd.DataFrame, threshold: float, stage: StageSpec
) -> pd.DataFrame:
    eligible = scored.loc[
        (scored["entry_ts"] >= stage.start)
        & (scored["entry_ts"] < stage.end_exclusive)
        & (~scored["path_invalid"])
    ].copy()
    if eligible.empty:
        return eligible
    best_idx = eligible.groupby("event_id", sort=False)["probability"].idxmax()
    selected = eligible.loc[best_idx]
    selected = selected.loc[selected["probability"] >= threshold]
    selected = selected.sort_values(
        ["entry_ts", "probability", "symbol", "is_continuation"],
        ascending=[True, False, True, False],
    )
    return selected.reset_index(drop=True)


def build_global_sequence(
    selected: pd.DataFrame, stage: StageSpec
) -> pd.DataFrame:
    rows: list[pd.Series] = []
    available_after = stage.start - pd.Timedelta(nanoseconds=1)
    for _, candidate in selected.iterrows():
        if candidate.entry_ts <= available_after:
            continue
        rows.append(candidate)
        exit_ts = candidate.exit_ts_full
        if pd.isna(exit_ts) or exit_ts >= stage.end_exclusive:
            break
        available_after = exit_ts
    if not rows:
        return pd.DataFrame(columns=selected.columns)
    result = pd.DataFrame(rows).reset_index(drop=True)
    result["sequence_id"] = np.arange(len(result), dtype=int)
    return result
