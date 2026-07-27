from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

BAR_MS = 5 * 60_000
FEATURE_COLUMNS = [
    "symbol_code",
    "direction",
    "session_code",
    "hour_sin",
    "hour_cos",
    "atr_pct",
    "volatility_ratio",
    "volume_z",
    "sweep_depth_atr",
    "sweep_age_bars",
    "displacement_body_atr",
    "displacement_range_atr",
    "fvg_size_atr",
    "ob_overlap_atr",
    "bpr_overlap_atr",
    "cisd_confirmed",
    "smt_divergence",
    "smt_return_gap",
    "dealing_position_3d",
    "momentum_1h",
    "momentum_4h",
    "momentum_1d",
    "distance_target_atr",
    "distance_stop_atr",
    "reward_risk",
    "entry_discount",
    "liquidity_type_code",
    "target_type_code",
    "prev_day_range_atr",
    "asia_range_atr",
    "day_of_week_sin",
    "day_of_week_cos",
    "entry_variant_code",
    "stop_buffer_atr",
]


@dataclass(frozen=True)
class CandidatePlan:
    candidate_id: str
    symbol: str
    symbol_code: int
    direction: int
    signal_idx: int
    signal_timestamp_ms: int
    active_idx: int
    sweep_idx: int
    sweep_timestamp_ms: int
    sweep_level: float
    sweep_extreme: float
    entry: float
    stop: float
    target: float
    reward_risk: float
    entry_variant: str
    stop_buffer_atr: float
    liquidity_type: str
    target_type: str
    fill_idx: int | None
    fill_timestamp_ms: int | None
    order_end_idx: int
    order_end_timestamp_ms: int
    exit_idx: int | None
    exit_timestamp_ms: int | None
    exit_price_raw: float | None
    exit_reason: str
    gross_r: float | None
    resolved_timestamp_ms: int
    features: dict[str, float]


@dataclass
class MarketData:
    symbol: str
    frame: pd.DataFrame
    funding: pd.DataFrame
    instrument: dict[str, Any]


def load_market_data(data_root: Path, symbols: Iterable[str] = ("BTCUSDT", "ETHUSDT")) -> dict[str, MarketData]:
    markets: dict[str, MarketData] = {}
    for symbol in symbols:
        bars_path = data_root / f"{symbol}_5m.parquet"
        funding_path = data_root / f"{symbol}_funding.parquet"
        instrument_path = data_root / f"{symbol}_instrument.json"
        frame = pd.read_parquet(bars_path)
        required = {"timestamp_ms", "open", "high", "low", "close", "volume", "turnover"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{symbol} bars missing columns: {sorted(missing)}")
        frame = frame.sort_values("timestamp_ms").drop_duplicates("timestamp_ms", keep="last").reset_index(drop=True)
        for column in ["timestamp_ms"]:
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
        for column in ["open", "high", "low", "close", "volume", "turnover"]:
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")
        if funding_path.exists():
            funding = pd.read_parquet(funding_path).sort_values("timestamp_ms").reset_index(drop=True)
        else:
            funding = pd.DataFrame(columns=["timestamp_ms", "funding_rate"])
        instrument = json.loads(instrument_path.read_text(encoding="utf-8")) if instrument_path.exists() else {}
        markets[symbol] = MarketData(symbol=symbol, frame=frame, funding=funding, instrument=instrument)
    return markets


def confirmed_swing(series: pd.Series, *, radius: int, kind: str) -> pd.Series:
    window = radius * 2 + 1
    if kind == "high":
        centered = series.rolling(window, center=True, min_periods=window).max()
        raw = series.eq(centered)
    elif kind == "low":
        centered = series.rolling(window, center=True, min_periods=window).min()
        raw = series.eq(centered)
    else:
        raise ValueError(kind)
    # A pivot at i is only exposed at i+radius, when all right-hand bars exist.
    return series.where(raw).shift(radius).ffill()


def _group_prior_levels(index: pd.DatetimeIndex, frame: pd.DataFrame) -> pd.DataFrame:
    day = index.floor("D")
    daily = frame.assign(day=day).groupby("day", sort=True).agg(
        day_high=("high", "max"),
        day_low=("low", "min"),
        day_open=("open", "first"),
        day_close=("close", "last"),
    )
    prior = daily.shift(1).rename(
        columns={
            "day_high": "prev_day_high",
            "day_low": "prev_day_low",
            "day_open": "prev_day_open",
            "day_close": "prev_day_close",
        }
    )
    mapped = prior.reindex(day).set_axis(frame.index)

    iso = index.isocalendar()
    week_key = pd.MultiIndex.from_arrays([iso.year.to_numpy(), iso.week.to_numpy()])
    weekly = frame.assign(week=list(week_key)).groupby("week", sort=True).agg(
        week_high=("high", "max"), week_low=("low", "min")
    )
    prior_week = weekly.shift(1).rename(columns={"week_high": "prev_week_high", "week_low": "prev_week_low"})
    mapped_week = prior_week.reindex(list(week_key)).set_axis(frame.index)
    return pd.concat([mapped, mapped_week], axis=1)


def _asia_levels(index: pd.DatetimeIndex, frame: pd.DataFrame, *, end_hour: int = 8) -> pd.DataFrame:
    day = index.floor("D")
    mask = index.hour < end_hour
    asia = frame.loc[mask].assign(day=day[mask]).groupby("day", sort=True).agg(
        asia_high=("high", "max"), asia_low=("low", "min"), asia_open=("open", "first")
    )
    mapped = asia.reindex(day).set_axis(frame.index)
    available = np.asarray(index.hour >= end_hour)
    mapped = mapped.copy()
    mapped.loc[~available, :] = np.nan
    return mapped


def prepare_symbol_frame(frame: pd.DataFrame, *, swing_radius: int = 6) -> pd.DataFrame:
    work = frame.copy()
    index = pd.DatetimeIndex(pd.to_datetime(work["timestamp_ms"], unit="ms", utc=True))
    work.index = index
    work.index.name = None
    prev_close = work["close"].shift(1)
    true_range = pd.concat(
        [
            work["high"] - work["low"],
            (work["high"] - prev_close).abs(),
            (work["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    work["atr"] = true_range.rolling(20, min_periods=20).mean()
    work["atr_slow"] = true_range.rolling(288, min_periods=96).mean()
    work["atr_pct"] = work["atr"] / work["close"]
    work["volatility_ratio"] = work["atr"] / work["atr_slow"]
    log_volume = np.log1p(work["volume"])
    volume_mean = log_volume.rolling(288, min_periods=96).mean()
    volume_std = log_volume.rolling(288, min_periods=96).std(ddof=0).replace(0.0, np.nan)
    work["volume_z"] = (log_volume - volume_mean) / volume_std

    work = pd.concat([work, _group_prior_levels(index, work), _asia_levels(index, work)], axis=1)
    work["swing_high"] = confirmed_swing(work["high"], radius=swing_radius, kind="high")
    work["swing_low"] = confirmed_swing(work["low"], radius=swing_radius, kind="low")
    work["micro_swing_high"] = confirmed_swing(work["high"], radius=2, kind="high")
    work["micro_swing_low"] = confirmed_swing(work["low"], radius=2, kind="low")

    work["rolling_high_12h"] = work["high"].rolling(144, min_periods=48).max().shift(1)
    work["rolling_low_12h"] = work["low"].rolling(144, min_periods=48).min().shift(1)
    work["rolling_high_3d"] = work["high"].rolling(864, min_periods=288).max().shift(1)
    work["rolling_low_3d"] = work["low"].rolling(864, min_periods=288).min().shift(1)
    range_3d = (work["rolling_high_3d"] - work["rolling_low_3d"]).replace(0.0, np.nan)
    work["dealing_position_3d"] = (work["close"] - work["rolling_low_3d"]) / range_3d
    work["momentum_1h"] = work["close"] / work["close"].shift(12) - 1.0
    work["momentum_4h"] = work["close"] / work["close"].shift(48) - 1.0
    work["momentum_1d"] = work["close"] / work["close"].shift(288) - 1.0

    work["body"] = work["close"] - work["open"]
    work["range"] = work["high"] - work["low"]
    work["body_atr"] = work["body"] / work["atr"]
    work["range_atr"] = work["range"] / work["atr"]
    prior_two_high = work["high"].shift(1).rolling(2, min_periods=2).max()
    prior_two_low = work["low"].shift(1).rolling(2, min_periods=2).min()
    work["bull_displacement"] = (
        (work["body_atr"] >= 0.45)
        & (work["range_atr"] >= 0.75)
        & (work["close"] > prior_two_high)
    )
    work["bear_displacement"] = (
        (work["body_atr"] <= -0.45)
        & (work["range_atr"] >= 0.75)
        & (work["close"] < prior_two_low)
    )
    work["bull_fvg_low"] = work["high"].shift(2)
    work["bull_fvg_high"] = work["low"]
    work["bull_fvg"] = work["bull_fvg_high"] > work["bull_fvg_low"]
    work["bear_fvg_low"] = work["high"]
    work["bear_fvg_high"] = work["low"].shift(2)
    work["bear_fvg"] = work["bear_fvg_high"] > work["bear_fvg_low"]

    last_bearish_open = work["open"].where(work["close"] < work["open"]).shift(1).rolling(8, min_periods=1).max()
    last_bullish_open = work["open"].where(work["close"] > work["open"]).shift(1).rolling(8, min_periods=1).min()
    work["bull_cisd"] = work["close"] > last_bearish_open
    work["bear_cisd"] = work["close"] < last_bullish_open

    work["new_low_12h"] = work["low"] < work["rolling_low_12h"]
    work["new_high_12h"] = work["high"] > work["rolling_high_12h"]
    work["return_1h"] = work["close"] / work["close"].shift(12) - 1.0
    return work


def add_cross_market_context(prepared: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    symbols = list(prepared)
    if len(symbols) < 2:
        for frame in prepared.values():
            frame["other_new_low_12h"] = False
            frame["other_new_high_12h"] = False
            frame["other_return_1h"] = 0.0
        return prepared
    for symbol in symbols:
        other = next(value for value in symbols if value != symbol)
        other_frame = prepared[other][["timestamp_ms", "new_low_12h", "new_high_12h", "return_1h"]].reset_index(drop=True).copy()
        other_frame = other_frame.rename(
            columns={
                "new_low_12h": "other_new_low_12h",
                "new_high_12h": "other_new_high_12h",
                "return_1h": "other_return_1h",
            }
        )
        merged = prepared[symbol].reset_index(drop=True).merge(other_frame, on="timestamp_ms", how="left", sort=False)
        merged.index = pd.to_datetime(merged["timestamp_ms"], unit="ms", utc=True)
        merged["other_new_low_12h"] = merged["other_new_low_12h"].fillna(False).astype(bool)
        merged["other_new_high_12h"] = merged["other_new_high_12h"].fillna(False).astype(bool)
        merged["other_return_1h"] = merged["other_return_1h"].fillna(0.0)
        prepared[symbol] = merged
    return prepared


def _choose_swept_level(row: pd.Series, *, direction: int, prior_close: float) -> tuple[float, str, float] | None:
    if not math.isfinite(float(row.get("atr", np.nan))) or row["atr"] <= 0:
        return None
    if direction == 1:
        values = [
            (row.get("prev_day_low"), "previous_day_low"),
            (row.get("asia_low"), "asia_low"),
            (row.get("prev_week_low"), "previous_week_low"),
            (row.get("swing_low"), "confirmed_swing_low"),
        ]
        valid = [
            (float(level), name, (float(level) - float(row["low"])) / float(row["atr"]))
            for level, name in values
            if pd.notna(level) and prior_close > float(level) and float(row["low"]) < float(level) and float(row["close"]) > float(level)
        ]
    else:
        values = [
            (row.get("prev_day_high"), "previous_day_high"),
            (row.get("asia_high"), "asia_high"),
            (row.get("prev_week_high"), "previous_week_high"),
            (row.get("swing_high"), "confirmed_swing_high"),
        ]
        valid = [
            (float(level), name, (float(row["high"]) - float(level)) / float(row["atr"]))
            for level, name in values
            if pd.notna(level) and prior_close < float(level) and float(row["high"]) > float(level) and float(row["close"]) < float(level)
        ]
    if not valid:
        return None
    return max(valid, key=lambda item: item[2])


def _choose_target(row: pd.Series, *, direction: int, entry: float) -> tuple[float, str] | None:
    if direction == 1:
        values = [
            (row.get("swing_high"), "confirmed_swing_high"),
            (row.get("asia_high"), "asia_high"),
            (row.get("prev_day_high"), "previous_day_high"),
            (row.get("prev_week_high"), "previous_week_high"),
            (row.get("rolling_high_12h"), "rolling_12h_high"),
            (row.get("rolling_high_3d"), "rolling_3d_high"),
        ]
        valid = [(float(level), name) for level, name in values if pd.notna(level) and float(level) > entry]
        return min(valid, key=lambda item: item[0]) if valid else None
    values = [
        (row.get("swing_low"), "confirmed_swing_low"),
        (row.get("asia_low"), "asia_low"),
        (row.get("prev_day_low"), "previous_day_low"),
        (row.get("prev_week_low"), "previous_week_low"),
        (row.get("rolling_low_12h"), "rolling_12h_low"),
        (row.get("rolling_low_3d"), "rolling_3d_low"),
    ]
    valid = [(float(level), name) for level, name in values if pd.notna(level) and float(level) < entry]
    return max(valid, key=lambda item: item[0]) if valid else None


def _last_opposite_candle(frame: pd.DataFrame, start: int, end: int, direction: int) -> tuple[float, float] | None:
    if end <= start:
        return None
    window = frame.iloc[max(0, start) : end]
    if direction == 1:
        opposite = window[window["close"] < window["open"]]
    else:
        opposite = window[window["close"] > window["open"]]
    if opposite.empty:
        return None
    row = opposite.iloc[-1]
    return float(row["low"]), float(row["high"])


def _session_code(timestamp: pd.Timestamp) -> int:
    hour = timestamp.hour
    if 0 <= hour < 8:
        return 0
    if 8 <= hour < 13:
        return 1
    if 13 <= hour < 21:
        return 2
    return 3


def _liquidity_code(name: str) -> int:
    names = {
        "previous_day_low": 0,
        "previous_day_high": 0,
        "asia_low": 1,
        "asia_high": 1,
        "previous_week_low": 2,
        "previous_week_high": 2,
        "confirmed_swing_low": 3,
        "confirmed_swing_high": 3,
        "rolling_12h_low": 4,
        "rolling_12h_high": 4,
        "rolling_3d_low": 5,
        "rolling_3d_high": 5,
    }
    return names.get(name, 6)


def _simulate_plan(
    frame: pd.DataFrame,
    *,
    direction: int,
    signal_idx: int,
    entry: float,
    stop: float,
    target: float,
    sweep_level: float,
) -> dict[str, Any]:
    arrays = frame.attrs.get("_simulation_arrays")
    if arrays is None:
        arrays = {
            "open": frame["open"].to_numpy(float),
            "high": frame["high"].to_numpy(float),
            "low": frame["low"].to_numpy(float),
            "close": frame["close"].to_numpy(float),
            "bull_displacement": frame["bull_displacement"].fillna(False).to_numpy(bool),
            "bear_displacement": frame["bear_displacement"].fillna(False).to_numpy(bool),
            "timestamp_ms": frame["timestamp_ms"].to_numpy(np.int64),
        }
        frame.attrs["_simulation_arrays"] = arrays
    opens = arrays["open"]
    highs = arrays["high"]
    lows = arrays["low"]
    closes = arrays["close"]
    bull_disp = arrays["bull_displacement"]
    bear_disp = arrays["bear_displacement"]
    timestamps = arrays["timestamp_ms"]
    active_idx = signal_idx + 1
    if active_idx >= len(frame):
        return {
            "active_idx": active_idx,
            "fill_idx": None,
            "order_end_idx": signal_idx,
            "exit_idx": None,
            "exit_price_raw": None,
            "exit_reason": "dataset_end_before_activation",
            "gross_r": None,
            "resolved_timestamp_ms": int(timestamps[signal_idx]),
        }
    filled: int | None = None
    order_end = active_idx
    exit_idx: int | None = None
    exit_price: float | None = None
    reason = "unresolved"
    for idx in range(active_idx, len(frame)):
        order_end = idx
        if filled is None:
            touched_entry = lows[idx] <= entry <= highs[idx]
            if direction == 1:
                if touched_entry:
                    filled = idx
                    if lows[idx] <= stop:
                        exit_idx, exit_price, reason = idx, stop, "stop_same_bar"
                        break
                    if highs[idx] >= target:
                        exit_idx, exit_price, reason = idx, target, "target_same_bar"
                        break
                elif highs[idx] >= target:
                    reason = "target_taken_before_fill"
                    break
                elif bear_disp[idx] and closes[idx] < sweep_level:
                    reason = "opposite_delivery_before_fill"
                    break
            else:
                if touched_entry:
                    filled = idx
                    if highs[idx] >= stop:
                        exit_idx, exit_price, reason = idx, stop, "stop_same_bar"
                        break
                    if lows[idx] <= target:
                        exit_idx, exit_price, reason = idx, target, "target_same_bar"
                        break
                elif lows[idx] <= target:
                    reason = "target_taken_before_fill"
                    break
                elif bull_disp[idx] and closes[idx] > sweep_level:
                    reason = "opposite_delivery_before_fill"
                    break
            continue

        if direction == 1:
            if lows[idx] <= stop and highs[idx] >= target:
                exit_idx, exit_price, reason = idx, stop, "ambiguous_stop_first"
                break
            if lows[idx] <= stop:
                exit_idx, exit_price, reason = idx, stop, "stop"
                break
            if highs[idx] >= target:
                exit_idx, exit_price, reason = idx, target, "target"
                break
            if bear_disp[idx] and closes[idx] < entry and idx + 1 < len(frame):
                exit_idx, exit_price, reason = idx + 1, float(opens[idx + 1]), "opposite_delivery"
                break
        else:
            if highs[idx] >= stop and lows[idx] <= target:
                exit_idx, exit_price, reason = idx, stop, "ambiguous_stop_first"
                break
            if highs[idx] >= stop:
                exit_idx, exit_price, reason = idx, stop, "stop"
                break
            if lows[idx] <= target:
                exit_idx, exit_price, reason = idx, target, "target"
                break
            if bull_disp[idx] and closes[idx] > entry and idx + 1 < len(frame):
                exit_idx, exit_price, reason = idx + 1, float(opens[idx + 1]), "opposite_delivery"
                break

    risk_distance = abs(entry - stop)
    gross_r = direction * (exit_price - entry) / risk_distance if exit_price is not None and risk_distance > 0 else None
    resolved_idx = exit_idx if exit_idx is not None else order_end
    return {
        "active_idx": active_idx,
        "fill_idx": filled,
        "order_end_idx": order_end,
        "exit_idx": exit_idx,
        "exit_price_raw": exit_price,
        "exit_reason": reason,
        "gross_r": gross_r,
        "resolved_timestamp_ms": int(timestamps[resolved_idx]),
    }


def generate_candidates(
    prepared: dict[str, pd.DataFrame],
    *,
    max_sweep_age_bars: int = 12,
    stop_buffers_atr: tuple[float, ...] = (0.05, 0.15),
) -> pd.DataFrame:
    plans: list[CandidatePlan] = []
    symbol_codes = {symbol: idx for idx, symbol in enumerate(sorted(prepared))}
    for symbol, frame in prepared.items():
        last_bear_fvg: tuple[float, float] | None = None
        last_bull_fvg: tuple[float, float] | None = None
        states: dict[int, dict[str, Any] | None] = {1: None, -1: None}
        for idx in range(2, len(frame)):
            row = frame.iloc[idx]
            prior_close = float(frame.iloc[idx - 1]["close"])
            atr = float(row.get("atr", np.nan))
            if not math.isfinite(atr) or atr <= 0:
                continue
            for direction in (1, -1):
                swept = _choose_swept_level(row, direction=direction, prior_close=prior_close)
                if swept is not None:
                    level, name, depth = swept
                    states[direction] = {
                        "idx": idx,
                        "level": level,
                        "name": name,
                        "depth": depth,
                        "extreme": float(row["low"] if direction == 1 else row["high"]),
                    }
                state = states[direction]
                if state is not None:
                    if direction == 1:
                        state["extreme"] = min(float(state["extreme"]), float(row["low"]))
                    else:
                        state["extreme"] = max(float(state["extreme"]), float(row["high"]))
                    if idx - int(state["idx"]) > max_sweep_age_bars:
                        states[direction] = None

            if bool(row.get("bear_fvg", False)):
                last_bear_fvg = (float(row["bear_fvg_low"]), float(row["bear_fvg_high"]))
            if bool(row.get("bull_fvg", False)):
                last_bull_fvg = (float(row["bull_fvg_low"]), float(row["bull_fvg_high"]))

            for direction in (1, -1):
                state = states[direction]
                if state is None:
                    continue
                displacement = bool(row["bull_displacement"] if direction == 1 else row["bear_displacement"])
                fvg = bool(row["bull_fvg"] if direction == 1 else row["bear_fvg"])
                if not (displacement and fvg):
                    continue
                fvg_low = float(row["bull_fvg_low"] if direction == 1 else row["bear_fvg_low"])
                fvg_high = float(row["bull_fvg_high"] if direction == 1 else row["bear_fvg_high"])
                if fvg_high <= fvg_low:
                    continue
                fvg_mid = (fvg_low + fvg_high) / 2.0
                opposite = _last_opposite_candle(frame, int(state["idx"]), idx, direction)
                variants: list[tuple[str, float, float]] = [("fvg_midpoint", fvg_mid, 0.0)]
                ob_overlap_atr = 0.0
                if opposite is not None:
                    ob_low, ob_high = opposite
                    overlap_low = max(fvg_low, ob_low)
                    overlap_high = min(fvg_high, ob_high)
                    if overlap_high > overlap_low:
                        overlap_mid = (overlap_low + overlap_high) / 2.0
                        ob_overlap_atr = (overlap_high - overlap_low) / atr
                        variants.append(("fvg_orderblock_overlap", overlap_mid, ob_overlap_atr))

                if direction == 1 and last_bear_fvg is not None:
                    bpr_low = max(fvg_low, last_bear_fvg[0])
                    bpr_high = min(fvg_high, last_bear_fvg[1])
                    bpr_overlap_atr = max(0.0, bpr_high - bpr_low) / atr
                elif direction == -1 and last_bull_fvg is not None:
                    bpr_low = max(fvg_low, last_bull_fvg[0])
                    bpr_high = min(fvg_high, last_bull_fvg[1])
                    bpr_overlap_atr = max(0.0, bpr_high - bpr_low) / atr
                else:
                    bpr_overlap_atr = 0.0

                for entry_variant, entry, overlap_feature in variants:
                    target_choice = _choose_target(row, direction=direction, entry=entry)
                    if target_choice is None:
                        continue
                    target, target_type = target_choice
                    for stop_buffer in stop_buffers_atr:
                        stop = float(state["extreme"]) - stop_buffer * atr if direction == 1 else float(state["extreme"]) + stop_buffer * atr
                        risk = direction * (entry - stop)
                        reward = direction * (target - entry)
                        if risk <= 0 or reward <= 0:
                            continue
                        rr = reward / risk
                        if rr < 0.75:
                            continue
                        simulation = _simulate_plan(
                            frame,
                            direction=direction,
                            signal_idx=idx,
                            entry=entry,
                            stop=stop,
                            target=target,
                            sweep_level=float(state["level"]),
                        )
                        timestamp = frame.index[idx]
                        hour_fraction = timestamp.hour + timestamp.minute / 60.0
                        dow = timestamp.dayofweek
                        sweep_idx = int(state["idx"])
                        sweep_row = frame.iloc[sweep_idx]
                        smt = (
                            bool(sweep_row.get("new_low_12h", False)) and not bool(sweep_row.get("other_new_low_12h", False))
                            if direction == 1
                            else bool(sweep_row.get("new_high_12h", False)) and not bool(sweep_row.get("other_new_high_12h", False))
                        )
                        return_gap = direction * (float(sweep_row.get("return_1h", 0.0)) - float(sweep_row.get("other_return_1h", 0.0)))
                        prev_day_range = float(row.get("prev_day_high", np.nan)) - float(row.get("prev_day_low", np.nan))
                        asia_range = float(row.get("asia_high", np.nan)) - float(row.get("asia_low", np.nan))
                        features = {
                            "symbol_code": float(symbol_codes[symbol]),
                            "direction": float(direction),
                            "session_code": float(_session_code(timestamp)),
                            "hour_sin": math.sin(2.0 * math.pi * hour_fraction / 24.0),
                            "hour_cos": math.cos(2.0 * math.pi * hour_fraction / 24.0),
                            "atr_pct": float(row.get("atr_pct", np.nan)),
                            "volatility_ratio": float(row.get("volatility_ratio", np.nan)),
                            "volume_z": float(row.get("volume_z", np.nan)),
                            "sweep_depth_atr": float(state["depth"]),
                            "sweep_age_bars": float(idx - sweep_idx),
                            "displacement_body_atr": direction * float(row.get("body_atr", np.nan)),
                            "displacement_range_atr": float(row.get("range_atr", np.nan)),
                            "fvg_size_atr": (fvg_high - fvg_low) / atr,
                            "ob_overlap_atr": overlap_feature,
                            "bpr_overlap_atr": bpr_overlap_atr,
                            "cisd_confirmed": float(bool(row.get("bull_cisd" if direction == 1 else "bear_cisd", False))),
                            "smt_divergence": float(smt),
                            "smt_return_gap": return_gap,
                            "dealing_position_3d": float(row.get("dealing_position_3d", np.nan)),
                            "momentum_1h": direction * float(row.get("momentum_1h", np.nan)),
                            "momentum_4h": direction * float(row.get("momentum_4h", np.nan)),
                            "momentum_1d": direction * float(row.get("momentum_1d", np.nan)),
                            "distance_target_atr": reward / atr,
                            "distance_stop_atr": risk / atr,
                            "reward_risk": rr,
                            "entry_discount": direction * (float(row["close"]) - entry) / atr,
                            "liquidity_type_code": float(_liquidity_code(str(state["name"]))),
                            "target_type_code": float(_liquidity_code(target_type)),
                            "prev_day_range_atr": prev_day_range / atr if math.isfinite(prev_day_range) else np.nan,
                            "asia_range_atr": asia_range / atr if math.isfinite(asia_range) else np.nan,
                            "day_of_week_sin": math.sin(2.0 * math.pi * dow / 7.0),
                            "day_of_week_cos": math.cos(2.0 * math.pi * dow / 7.0),
                            "entry_variant_code": 0.0 if entry_variant == "fvg_midpoint" else 1.0,
                            "stop_buffer_atr": stop_buffer,
                        }
                        cid = f"{symbol}-{int(row['timestamp_ms'])}-{direction}-{entry_variant}-{stop_buffer:.2f}"
                        fill_idx = simulation["fill_idx"]
                        exit_idx = simulation["exit_idx"]
                        plan = CandidatePlan(
                            candidate_id=cid,
                            symbol=symbol,
                            symbol_code=symbol_codes[symbol],
                            direction=direction,
                            signal_idx=idx,
                            signal_timestamp_ms=int(row["timestamp_ms"]),
                            active_idx=int(simulation["active_idx"]),
                            sweep_idx=sweep_idx,
                            sweep_timestamp_ms=int(frame.iloc[sweep_idx]["timestamp_ms"]),
                            sweep_level=float(state["level"]),
                            sweep_extreme=float(state["extreme"]),
                            entry=entry,
                            stop=stop,
                            target=target,
                            reward_risk=rr,
                            entry_variant=entry_variant,
                            stop_buffer_atr=stop_buffer,
                            liquidity_type=str(state["name"]),
                            target_type=target_type,
                            fill_idx=fill_idx,
                            fill_timestamp_ms=int(frame.iloc[fill_idx]["timestamp_ms"]) if fill_idx is not None and fill_idx < len(frame) else None,
                            order_end_idx=int(simulation["order_end_idx"]),
                            order_end_timestamp_ms=int(frame.iloc[int(simulation["order_end_idx"])]["timestamp_ms"]),
                            exit_idx=exit_idx,
                            exit_timestamp_ms=int(frame.iloc[exit_idx]["timestamp_ms"]) if exit_idx is not None and exit_idx < len(frame) else None,
                            exit_price_raw=simulation["exit_price_raw"],
                            exit_reason=str(simulation["exit_reason"]),
                            gross_r=simulation["gross_r"],
                            resolved_timestamp_ms=int(simulation["resolved_timestamp_ms"]),
                            features=features,
                        )
                        plans.append(plan)
                states[direction] = None
    rows: list[dict[str, Any]] = []
    for plan in plans:
        item = asdict(plan)
        features = item.pop("features")
        item.update(features)
        rows.append(item)
    candidates = pd.DataFrame(rows)
    if candidates.empty:
        return pd.DataFrame(columns=[field for field in CandidatePlan.__dataclass_fields__ if field != "features"] + FEATURE_COLUMNS)
    candidates = candidates.sort_values(["signal_timestamp_ms", "candidate_id"]).reset_index(drop=True)
    return candidates


def causal_prefix_invariance_test() -> None:
    rng = np.random.default_rng(7)
    values = pd.Series(np.cumsum(rng.normal(size=200)))
    full = confirmed_swing(values, radius=4, kind="high")
    for end in (80, 120, 160):
        prefix = confirmed_swing(values.iloc[:end], radius=4, kind="high")
        pd.testing.assert_series_equal(full.iloc[:end].reset_index(drop=True), prefix.reset_index(drop=True))


def self_test() -> None:
    causal_prefix_invariance_test()
    timestamps = np.arange(0, 100 * BAR_MS, BAR_MS, dtype=np.int64)
    close = 100 + np.sin(np.arange(100) / 5.0)
    frame = pd.DataFrame(
        {
            "timestamp_ms": timestamps,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(100),
            "turnover": close,
        }
    )
    prepared = prepare_symbol_frame(frame, swing_radius=2)
    assert "swing_high" in prepared and len(prepared) == 100
    print("smc_core self-test: ok")


if __name__ == "__main__":
    self_test()
