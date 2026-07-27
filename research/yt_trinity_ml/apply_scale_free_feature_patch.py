#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORE = ROOT / "system" / "core.py"
MODEL = ROOT / "system" / "model.py"
TEST = ROOT / "tests" / "test_scale_free_model_features.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


core = CORE.read_text(encoding="utf-8")
old_core = '''    optional = {
        "mark_close": "basis_mark_atr",
        "index_close": "basis_index_atr",
        "premium_close": "premium_atr",
        "open_interest": "open_interest_change",
        "long_short_ratio": "long_short_ratio_z",
        "funding_rate": "funding_rate",
        "spread_bps": "spread_bps",
    }
    for source, destination in optional.items():
        if source not in raw.columns:
            out[destination] = np.nan
            continue
        values = pd.to_numeric(raw[source], errors="coerce")
        if source in {"mark_close", "index_close", "premium_close"}:
            out[destination] = (values - out["close"]) / out["atr"]
        elif source == "open_interest":
            out[destination] = np.log(values.replace(0, np.nan)).diff()
        elif source == "long_short_ratio":
            mean = values.rolling(100, min_periods=30).mean()
            std_value = values.rolling(100, min_periods=30).std(ddof=0)
            out[destination] = (values - mean) / std_value.replace(0, np.nan)
        else:
            out[destination] = values
'''
new_core = '''    optional = {
        "mark_close": "basis_mark_atr",
        "index_close": "basis_index_atr",
        "open_interest": "open_interest_change",
        "long_short_ratio": "long_short_ratio_z",
        "funding_rate": "funding_rate",
        "spread_bps": "spread_bps",
    }
    for source, destination in optional.items():
        if source not in raw.columns:
            out[destination] = np.nan
            continue
        values = pd.to_numeric(raw[source], errors="coerce")
        if source in {"mark_close", "index_close"}:
            out[destination] = (values - out["close"]) / out["atr"]
        elif source == "open_interest":
            out[destination] = np.log(values.replace(0, np.nan)).diff()
        elif source == "long_short_ratio":
            mean = values.rolling(100, min_periods=30).mean()
            std_value = values.rolling(100, min_periods=30).std(ddof=0)
            out[destination] = (values - mean) / std_value.replace(0, np.nan)
        else:
            out[destination] = values

    # Bybit premium-index klines contain a premium rate, not a tradable price.
    # Treating that rate as a price and subtracting the contract close creates a
    # scale-dependent value hundreds or thousands of ATRs from zero.
    if "premium_close" in raw.columns:
        premium_rate = pd.to_numeric(raw["premium_close"], errors="coerce")
        premium_mean = premium_rate.rolling(100, min_periods=30).mean()
        premium_std = premium_rate.rolling(100, min_periods=30).std(ddof=0)
        out["premium_rate"] = premium_rate
        out["premium_bps"] = premium_rate * 10_000.0
        out["premium_rate_z"] = (premium_rate - premium_mean) / premium_std.replace(0, np.nan)
    else:
        out["premium_rate"] = np.nan
        out["premium_bps"] = np.nan
        out["premium_rate_z"] = np.nan
    # Keep the legacy column non-informative so old manifests fail safely instead
    # of silently learning the invalid price-minus-rate calculation.
    out["premium_atr"] = np.nan
'''
core = replace_once(core, old_core, new_core, "premium-index semantics")
CORE.write_text(core, encoding="utf-8")

model = MODEL.read_text(encoding="utf-8")
old_function = '''def candidate_model_features(candidate: EventCandidate) -> dict[str, float]:
    """Return the exact numeric feature vector used for both fitting and scoring."""
    row = {
        str(key): float(value)
        for key, value in candidate.feature_row.items()
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)
    }
    row.update(
        {
            "side": float(candidate.side),
            "stop_distance_fraction": candidate.stop_distance / max(candidate.entry_reference, 1e-12),
            "target_distance_fraction": candidate.target_distance / max(candidate.entry_reference, 1e-12),
            "raw_reward_risk": candidate.target_distance / max(candidate.stop_distance, 1e-12),
            "family_liquidity_sweep": float(candidate.family.value == "LIQUIDITY_SWEEP_REVERSAL"),
            "family_displacement_retest": float(
                candidate.family.value == "DISPLACEMENT_BREAK_RETEST_CONTINUATION"
            ),
            "symbol_btc": float(candidate.symbol == "BTCUSDT"),
            "symbol_eth": float(candidate.symbol == "ETHUSDT"),
            "symbol_sol": float(candidate.symbol == "SOLUSDT"),
            "symbol_xrp": float(candidate.symbol == "XRPUSDT"),
        }
    )
    return row
'''
new_function = '''_RAW_MODEL_FEATURES = {
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "trade_count",
    "atr",
    "body",
    "ema_fast",
    "ema_slow",
    "ema_long",
    "vwap",
    "mark_close",
    "index_close",
    "premium_close",
    "premium_atr",
    "open_interest",
    "mark_price",
    "index_price",
    "equal_high_liquidity",
    "equal_low_liquidity",
}
_RAW_LEVEL_PREFIXES = (
    "previous_",
    "current_",
    "last_",
    "micro_",
    "internal_",
    "confirmed_",
    "htf_",
    "dealing_range_",
)
_RAW_LEVEL_SUFFIXES = (
    "_price",
    "_level",
    "_lower",
    "_upper",
    "_equilibrium",
)


def _eligible_model_feature_name(name: str) -> bool:
    """Reject absolute price/time identity while preserving normalized SMC geometry."""
    key = str(name)
    if key in _RAW_MODEL_FEATURES:
        return False
    lowered = key.lower()
    if "timestamp" in lowered or lowered.endswith(("_ms", "_ns")):
        return False
    if lowered.endswith(_RAW_LEVEL_SUFFIXES):
        return False
    if lowered.startswith(_RAW_LEVEL_PREFIXES) and lowered.endswith(("_high", "_low", "_open", "_close")):
        return False
    return True


def candidate_model_features(candidate: EventCandidate) -> dict[str, float]:
    """Return one scale-free feature vector for both fitting and live scoring."""
    row = {
        str(key): float(value)
        for key, value in candidate.feature_row.items()
        if _eligible_model_feature_name(str(key))
        and isinstance(value, (int, float, np.integer, np.floating))
        and np.isfinite(value)
    }
    row.update(
        {
            "side": float(candidate.side),
            "stop_distance_fraction": candidate.stop_distance / max(candidate.entry_reference, 1e-12),
            "target_distance_fraction": candidate.target_distance / max(candidate.entry_reference, 1e-12),
            "raw_reward_risk": candidate.target_distance / max(candidate.stop_distance, 1e-12),
            "family_liquidity_sweep": float(candidate.family.value == "LIQUIDITY_SWEEP_REVERSAL"),
            "family_displacement_retest": float(
                candidate.family.value == "DISPLACEMENT_BREAK_RETEST_CONTINUATION"
            ),
            "symbol_btc": float(candidate.symbol == "BTCUSDT"),
            "symbol_eth": float(candidate.symbol == "ETHUSDT"),
            "symbol_sol": float(candidate.symbol == "SOLUSDT"),
            "symbol_xrp": float(candidate.symbol == "XRPUSDT"),
        }
    )
    return row
'''
model = replace_once(model, old_function, new_function, "candidate feature contract")
old_fit = '''        self.feature_names = [
            name
            for name in ordered.columns
            if name not in leakage_columns and pd.api.types.is_numeric_dtype(ordered[name])
        ]
'''
new_fit = '''        self.feature_names = [
            name
            for name in ordered.columns
            if name not in leakage_columns
            and _eligible_model_feature_name(name)
            and pd.api.types.is_numeric_dtype(ordered[name])
        ]
'''
model = replace_once(model, old_fit, new_fit, "fit feature allow contract")
MODEL.write_text(model, encoding="utf-8")

TEST.write_text(
    '''from __future__ import annotations

import numpy as np
import pandas as pd

from system.core import EventCandidate, EventFamily, FeatureConfig, build_causal_features
from system.model import _eligible_model_feature_name, candidate_model_features


def _bars(count: int = 240) -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=count, freq="5min", tz="UTC")
    close = 100.0 + np.linspace(0.0, 3.0, count)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": np.linspace(100.0, 200.0, count),
            "premium_close": np.linspace(-0.0002, 0.0003, count),
        },
        index=index,
    )


def test_premium_index_is_rate_not_contract_price() -> None:
    frame = _bars()
    features = build_causal_features(
        frame,
        FeatureConfig(atr_window=3, fast_ema=3, slow_ema=5, long_ema=8, volume_window=5),
    )
    np.testing.assert_allclose(
        features["premium_bps"].to_numpy(),
        frame["premium_close"].to_numpy() * 10_000.0,
    )
    assert features["premium_atr"].isna().all()
    assert features["premium_rate_z"].notna().sum() > 100


def test_candidate_feature_contract_removes_absolute_price_identity() -> None:
    event = EventCandidate(
        pd.Timestamp("2023-01-01T00:00:00Z"),
        "BTCUSDT",
        EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        1,
        100.0,
        100.0,
        98.0,
        106.0,
        99.0,
        {
            "close": 100.0,
            "atr": 2.0,
            "ema_fast": 99.0,
            "previous_day_high": 110.0,
            "equal_high_liquidity": 109.0,
            "premium_atr": -861.0,
            "sweep_depth_atr": 0.7,
            "premium_bps": 1.2,
            "premium_rate_z": 0.4,
            "liquidity_quality": 6.0,
            "x1": 3.0,
        },
    )
    values = candidate_model_features(event)
    for forbidden in (
        "close",
        "atr",
        "ema_fast",
        "previous_day_high",
        "equal_high_liquidity",
        "premium_atr",
    ):
        assert forbidden not in values
    for required in (
        "sweep_depth_atr",
        "premium_bps",
        "premium_rate_z",
        "liquidity_quality",
        "x1",
        "raw_reward_risk",
        "symbol_btc",
    ):
        assert required in values


def test_feature_name_filter_keeps_normalized_geometry() -> None:
    assert not _eligible_model_feature_name("htf_4h_last_swing_high")
    assert not _eligible_model_feature_name("bull_fvg_lower")
    assert not _eligible_model_feature_name("available_at_ms")
    assert _eligible_model_feature_name("distance_previous_day_high_atr")
    assert _eligible_model_feature_name("htf_bias_score")
    assert _eligible_model_feature_name("near_equal_high")
    assert _eligible_model_feature_name("raw_structural_reward_risk")
''',
    encoding="utf-8",
)

print("applied scale-free premium and model-feature contract")
