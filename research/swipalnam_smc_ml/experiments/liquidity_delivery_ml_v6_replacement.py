#!/usr/bin/env python3
"""V6: causal pending-order replacement under the one-global-slot rule."""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_ORIGINAL_MODULE_FROM_SPEC = importlib.util.module_from_spec


def _registered(spec):
    module = _ORIGINAL_MODULE_FROM_SPEC(spec)
    if spec.name:
        sys.modules[spec.name] = module
    return module


importlib.util.module_from_spec = _registered
import liquidity_delivery_ml_v5_nav as v5  # noqa: E402
v3 = v5.v3
v1 = v5.v1


@dataclass(frozen=True)
class ReplacementAccountConfig:
    risk_fraction: float
    leverage: float
    taker_fee_bps: float = 5.5
    slippage_bps: float = 1.0
    impact_bps: float = 4.0
    maintenance_margin_rate: float = 0.005
    replacement_sigma: float = 0.25

    @property
    def key(self) -> str:
        raw = json.dumps(dataclasses.asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _chosen_filled_candidates(frame: pd.DataFrame, threshold: float, replacement_sigma: float) -> pd.DataFrame:
    eligible = (
        frame[frame["ml_score"].notna() & (frame["ml_score"] >= threshold)]
        .sort_values(["decision_time_ms", "ml_score"], ascending=[True, False])
        .drop_duplicates("decision_time_ms")
        .reset_index(drop=True)
    )
    if eligible.empty:
        return eligible
    score_scale = float(eligible["ml_score"].std(ddof=0))
    if not np.isfinite(score_scale) or score_scale <= 0:
        score_scale = max(abs(float(eligible["ml_score"].median())), 1e-6)
    margin = replacement_sigma * score_scale
    active: pd.Series | None = None
    chosen: list[dict[str, Any]] = []

    for _, row in eligible.iterrows():
        decision = int(row["decision_time_ms"])
        if active is None:
            active = row
            continue
        active_filled = bool(active["filled"])
        if active_filled:
            entry = int(active["entry_time_ms"])
            exit_time = int(active["exit_time_ms"])
            if decision >= exit_time:
                chosen.append(active.to_dict())
                active = row
                continue
            if decision >= entry:
                # A live position is never replaced merely because a later
                # signal scores higher.
                continue
        else:
            pending_end = int(active["order_end_time_ms"])
            if decision >= pending_end:
                active = row
                continue

        # Only a still-unfilled order reaches this branch.
        if float(row["ml_score"]) > float(active["ml_score"]) + margin:
            active = row

    if active is not None and bool(active["filled"]):
        chosen.append(active.to_dict())
    if not chosen:
        return eligible.iloc[0:0].copy()
    return pd.DataFrame(chosen).sort_values("decision_time_ms", kind="stable").reset_index(drop=True)


def account_sim_replacement(
    frame: pd.DataFrame,
    minute_by_symbol: Mapping[str, pd.DataFrame],
    account: Any,
    start_ms: int,
    end_ms: int,
    threshold: float,
    initial_nav: float = 10_000.0,
) -> dict[str, Any]:
    chosen = _chosen_filled_candidates(frame, threshold, float(account.replacement_sigma))
    if chosen.empty:
        empty = v5.account_sim_exact(chosen, minute_by_symbol, account, start_ms, end_ms, threshold, initial_nav)
        empty["pending_order_replacements"] = 0
        empty["replacement_sigma"] = float(account.replacement_sigma)
        return empty
    original_count = int((frame["ml_score"].notna() & (frame["ml_score"] >= threshold)).sum())
    metrics = v5.account_sim_exact(chosen, minute_by_symbol, account, start_ms, end_ms, threshold, initial_nav)
    metrics["pending_order_replacements_or_competition_drops"] = max(0, original_count - len(chosen))
    metrics["replacement_sigma"] = float(account.replacement_sigma)
    return metrics


def replacement_account_grid() -> list[ReplacementAccountConfig]:
    return [
        ReplacementAccountConfig(risk, leverage, replacement_sigma=margin)
        for risk in (0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.16, 0.20, 0.25)
        for leverage in (5, 10, 20, 30, 50, 75, 100)
        for margin in (0.0, 0.25, 0.50, 0.75)
    ]


v1.AccountConfig = ReplacementAccountConfig
v1.account_sim = account_sim_replacement
v3.account_grid_v3 = replacement_account_grid

if __name__ == "__main__":
    raise SystemExit(v3.main_v3())
