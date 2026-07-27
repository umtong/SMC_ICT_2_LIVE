#!/usr/bin/env python3
"""V7: ML-confidence-conditioned risk budget plus pending replacement."""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_ORIGINAL_MODULE_FROM_SPEC = importlib.util.module_from_spec


def _registered(spec):
    module = _ORIGINAL_MODULE_FROM_SPEC(spec)
    if spec.name:
        sys.modules[spec.name] = module
    return module


importlib.util.module_from_spec = _registered
import liquidity_delivery_ml_v6_replacement as v6  # noqa: E402
v5 = v6.v5
v3 = v6.v3
v1 = v6.v1


@dataclass(frozen=True)
class ConfidenceRiskAccountConfig:
    risk_fraction: float
    leverage: float
    taker_fee_bps: float = 5.5
    slippage_bps: float = 1.0
    impact_bps: float = 4.0
    maintenance_margin_rate: float = 0.005
    replacement_sigma: float = 0.25
    confidence_risk_max: float = 2.0

    @property
    def key(self) -> str:
        raw = json.dumps(dataclasses.asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


_SCORE_CACHE: dict[tuple[int, float, float], tuple[float, float]] = {}


def _risk_multiplier(score: float, frame, threshold: float, maximum: float) -> float:
    key = (id(frame), round(float(threshold), 12), round(float(maximum), 6))
    bounds = _SCORE_CACHE.get(key)
    if bounds is None:
        values = frame.loc[frame["ml_score"].notna() & (frame["ml_score"] >= threshold), "ml_score"].astype(float)
        if len(values):
            median = float(values.quantile(0.50))
            high = float(values.quantile(0.90))
        else:
            median = high = float(threshold)
        _SCORE_CACHE[key] = (median, high)
        bounds = (median, high)
    median, high = bounds
    denominator = max(high - float(threshold), abs(float(threshold)) * 0.05, 1e-9)
    normalized = float(np.clip((score - float(threshold)) / denominator, 0.0, 1.0))
    # Convex allocation concentrates risk in the strongest prequential scores
    # while keeping marginal qualifying trades small rather than zero.
    return 0.35 + (float(maximum) - 0.35) * normalized ** 1.5


# Keep one audited account implementation.  Generate the confidence-risk
# revision by replacing only its planned-loss line, making the semantic delta
# explicit and mechanically reviewable.
_source = inspect.getsource(v5.account_sim_exact)
_source = _source.replace("def account_sim_exact(", "def account_sim_confidence_risk(", 1)
_old = "planned_loss = nav * float(account.risk_fraction)"
_new = "planned_loss = nav * float(account.risk_fraction) * _risk_multiplier(float(row.ml_score), frame, threshold, float(account.confidence_risk_max))"
if _old not in _source:
    raise RuntimeError("audited V5 planned-loss line changed; refuse silent patch")
_source = _source.replace(_old, _new, 1)
v5.__dict__["_risk_multiplier"] = _risk_multiplier
exec(_source, v5.__dict__)
v5.account_sim_exact = v5.__dict__["account_sim_confidence_risk"]


def confidence_account_grid() -> list[ConfidenceRiskAccountConfig]:
    return [
        ConfidenceRiskAccountConfig(
            risk_fraction=risk,
            leverage=leverage,
            replacement_sigma=replacement,
            confidence_risk_max=maximum,
        )
        for risk in (0.01, 0.02, 0.03, 0.05, 0.08, 0.12)
        for leverage in (5, 10, 20, 30, 50, 75)
        for replacement in (0.0, 0.25, 0.50)
        for maximum in (1.0, 1.75, 3.0)
    ]


v1.AccountConfig = ConfidenceRiskAccountConfig
v3.account_grid_v3 = confidence_account_grid
# v1.account_sim remains V6's replacement-aware wrapper; that wrapper invokes
# v5.account_sim_exact dynamically, now the confidence-risk implementation.

if __name__ == "__main__":
    raise SystemExit(v3.main_v3())
