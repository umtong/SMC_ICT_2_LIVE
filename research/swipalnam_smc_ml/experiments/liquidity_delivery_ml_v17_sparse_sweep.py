#!/usr/bin/env python3
"""V17: event-sparse candidate construction with V16 causal accounting.

This is an execution-equivalent acceleration, not a new trading thesis.  The
legacy base detector inspected every completed bar with pandas Series objects.
V17 first locates bars that actually reclaimed at least one confirmed liquidity
level using vectorized arrays, then invokes the unchanged detector on an exact
66-bar window around each event.  Displacement, FVG, order block, target, stop,
latency and account semantics remain delegated to the audited implementation.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import liquidity_delivery_ml_v16_causal_boundary as v16  # noqa: E402

v15 = v16.v15
v1 = v16.v1
v3 = v16.v3

_ORIGINAL_BASE_RAW = v15.v4._ORIGINAL_RAW

_LONG_LEVELS = (
    "last_swing_low",
    "equal_low_level",
    "opening_range_low",
    "prev_4h_low",
    "prev_session_low",
    "prev_day_low",
    "prev_week_low",
)
_SHORT_LEVELS = (
    "last_swing_high",
    "equal_high_level",
    "opening_range_high",
    "prev_4h_high",
    "prev_session_high",
    "prev_day_high",
    "prev_week_high",
)


def _level_matrix(frame: pd.DataFrame, names: tuple[str, ...]) -> np.ndarray:
    columns = [
        pd.to_numeric(frame[name], errors="coerce").to_numpy(float)
        if name in frame
        else np.full(len(frame), np.nan)
        for name in names
    ]
    return np.column_stack(columns)


def potential_sweep_indices(frame: pd.DataFrame) -> np.ndarray:
    """Exact prefilter for the V3 confirmed-level sweep-and-close-back test."""
    n = len(frame)
    if n < 66:
        return np.empty(0, dtype=np.int64)
    atr = pd.to_numeric(frame["atr"], errors="coerce").to_numpy(float)
    low = pd.to_numeric(frame["low"], errors="coerce").to_numpy(float)
    high = pd.to_numeric(frame["high"], errors="coerce").to_numpy(float)
    close = pd.to_numeric(frame["close"], errors="coerce").to_numpy(float)
    long_levels = _level_matrix(frame, _LONG_LEVELS)
    short_levels = _level_matrix(frame, _SHORT_LEVELS)
    long_event = np.any(
        np.isfinite(long_levels)
        & (low[:, None] < long_levels)
        & (long_levels < close[:, None]),
        axis=1,
    )
    short_event = np.any(
        np.isfinite(short_levels)
        & (high[:, None] > short_levels)
        & (short_levels > close[:, None]),
        axis=1,
    )
    valid = np.isfinite(atr) & (np.arange(n) >= 60) & (np.arange(n) < n - 5)
    return np.flatnonzero(valid & (long_event | short_event)).astype(np.int64)


def sparse_base_candidates(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for global_index in potential_sweep_indices(frame):
        # 60 preceding rows preserve every state field already computed by the
        # causal feature pipeline.  Six rows from the event make the unchanged
        # detector inspect exactly one sweep and its five-bar MSS horizon.
        window = (
            frame.iloc[int(global_index) - 60 : int(global_index) + 6]
            .copy()
            .reset_index(drop=True)
        )
        candidates = _ORIGINAL_BASE_RAW(symbol, window)
        if candidates.empty:
            continue
        candidates = candidates.copy()
        candidates["candidate_id"] = (
            candidates["candidate_id"].astype(str)
            + f"-global{int(global_index)}"
        )
        parts.append(candidates)
    if not parts:
        return pd.DataFrame()
    return (
        pd.concat(parts, ignore_index=True, sort=False)
        .sort_values("decision_time_ms", kind="stable")
        .reset_index(drop=True)
    )


# V4's cross-timeframe wrapper looks up this global at call time, so all later
# target-ladder, gap-entry, regime, dual-auction and V16 account layers remain.
v15.v4._ORIGINAL_RAW = sparse_base_candidates


def _synthetic_frame() -> pd.DataFrame:
    n = 100
    start = v1.utc_ms("2023-01-01T00:00:00Z")
    frame = pd.DataFrame(
        {
            "start_time_ms": start + np.arange(n) * v1.MINUTE_MS,
            "available_at_ms": start + (np.arange(n) + 1) * v1.MINUTE_MS,
            "open": 102.0,
            "high": 103.0,
            "low": 101.0,
            "close": 102.0,
            "volume": 10.0,
            "turnover": 1_020.0,
            "atr": 2.0,
            "atr_pct": 0.02,
            "range": 2.0,
            "body_signed": 0.0,
            "body_atr": 0.0,
            "range_atr": 1.0,
            "lower_wick": 1.0,
            "upper_wick": 1.0,
            "close_location": 0.5,
            "volume_z": 0.0,
            "turnover_z": 0.0,
            "internal_high": 103.0,
            "internal_low": 101.0,
            "last_swing_high": 110.0,
            "last_swing_low": np.nan,
            "equal_high_level": np.nan,
            "equal_low_level": np.nan,
            "opening_range_high": np.nan,
            "opening_range_low": np.nan,
            "prev_4h_high": np.nan,
            "prev_4h_low": np.nan,
            "prev_session_high": np.nan,
            "prev_session_low": np.nan,
            "prev_day_high": np.nan,
            "prev_day_low": np.nan,
            "prev_week_high": np.nan,
            "prev_week_low": np.nan,
            "trend_1h": 0.0,
            "trend_4h": 0.0,
            "pd_1h": 0.4,
            "pd_4h": 0.4,
            "oi_change_z": 0.0,
            "account_ratio_z": 0.0,
            "basis_bps": 0.0,
            "funding": 0.0,
            "smt_bull": 0.0,
            "smt_bear": 0.0,
            "session_bucket": 1.0,
            "hour_sin": 0.0,
            "hour_cos": 1.0,
            "dow_sin": 0.0,
            "dow_cos": 1.0,
            "timeframe_min": 1,
        }
    )
    frame.loc[69, ["open", "high", "low", "close"]] = [101.0, 101.5, 99.5, 100.0]
    frame.loc[69, "body_signed"] = -1.0
    frame.loc[70, ["open", "high", "low", "close"]] = [100.0, 102.0, 99.0, 101.0]
    frame.loc[70, "last_swing_low"] = 100.0
    frame.loc[70, "body_signed"] = 1.0
    frame.loc[70, "body_atr"] = 0.5
    frame.loc[70, "range_atr"] = 1.5
    frame.loc[70, "close_location"] = 2.0 / 3.0
    frame.loc[71, ["open", "high", "low", "close"]] = [101.0, 105.0, 102.0, 104.0]
    frame.loc[71, "body_signed"] = 3.0
    frame.loc[71, "body_atr"] = 1.5
    frame.loc[71, "range_atr"] = 1.5
    frame.loc[71, "close_location"] = 2.0 / 3.0
    frame.loc[71, "internal_high"] = 103.0
    frame.loc[71, "last_swing_high"] = 110.0
    return frame


def self_test_v17() -> None:
    v16.self_test_v16()
    frame = _synthetic_frame()
    expected_indices = [
        index
        for index in range(60, len(frame) - 5)
        if any(
            v3.swept_level_v3(frame.iloc[index], direction) is not None
            for direction in (1, -1)
        )
    ]
    actual_indices = potential_sweep_indices(frame).tolist()
    assert actual_indices == expected_indices

    original = _ORIGINAL_BASE_RAW("BTCUSDT", frame)
    sparse = sparse_base_candidates("BTCUSDT", frame)
    assert len(original) == len(sparse) == 1
    compare_columns = [
        "symbol",
        "direction",
        "timeframe_min",
        "decision_time_ms",
        "swept_level_name",
        "swept_level",
        "sweep_depth_atr",
        "displacement_body_atr",
        "fvg_low",
        "fvg_high",
        "ob_low",
        "ob_high",
        "zone_low",
        "zone_high",
        "stop_anchor",
        "target_price",
        "structural_rr",
    ]
    for name in compare_columns:
        left: Any = original.iloc[0][name]
        right: Any = sparse.iloc[0][name]
        if isinstance(left, (float, np.floating)):
            assert np.isclose(float(left), float(right), equal_nan=True), name
        else:
            assert left == right, name
    print("V17_SPARSE_SWEEP_EQUIVALENCE_PASS")


def main() -> int:
    if "--self-test" in sys.argv:
        self_test_v17()
        return 0
    return v3.main_v3()


if __name__ == "__main__":
    raise SystemExit(main())
