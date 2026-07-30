"""Chronological action-value model used by RES-20260729-ML-PO3-PATH-001."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from .policy_core import FEATURE_COLUMNS, global_route


@dataclass(frozen=True)
class ModelSpec:
    max_leaf_nodes: int
    min_samples_leaf: int
    l2_regularization: float
    threshold: float
    score_mode: str = "mean"


def fit_model(frame: pd.DataFrame, spec: ModelSpec) -> HistGradientBoostingRegressor:
    known = frame[frame.label_known].copy()
    model = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.05,
        max_iter=180,
        max_leaf_nodes=spec.max_leaf_nodes,
        min_samples_leaf=spec.min_samples_leaf,
        l2_regularization=spec.l2_regularization,
        early_stopping=False,
        random_state=23,
    )
    return model.fit(known[list(FEATURE_COLUMNS)], known.label.to_numpy(float))


def score(model: HistGradientBoostingRegressor, frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["policy_score"] = model.predict(out[list(FEATURE_COLUMNS)])
    return out


def account_metrics(route: pd.DataFrame) -> dict:
    trades = route[route.resolved].copy()
    returns = trades.account_return.dropna().to_numpy(float)
    logs = np.log1p(returns) if len(returns) else np.array([])
    positive, negative = returns[returns > 0], returns[returns < 0]
    return {
        "selected_events": int(len(route)),
        "trades": int(len(returns)),
        "return": float(np.expm1(logs.sum())) if len(logs) else 0.0,
        "mean_log_trade": float(logs.mean()) if len(logs) else None,
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) else None,
        "win_rate": float(np.mean(returns > 0)) if len(returns) else None,
        "top5_positive_share": float(np.sort(positive)[-5:].sum() / positive.sum()) if len(positive) else None,
    }


def chronological_select(candidates: pd.DataFrame) -> tuple[ModelSpec, list[dict]]:
    """Select only from 2022/2023 forward folds, never from 2024 outcomes."""
    specs = [
        ModelSpec(leaves, leaf, l2, threshold)
        for leaves in (7, 15)
        for leaf in (40, 80, 120)
        for l2 in (0.1, 1.0)
        for threshold in (-0.00025, 0.0, 0.0001, 0.0002, 0.0003, 0.0005, 0.00075, 0.001)
    ]
    scored: list[dict] = []
    for spec in specs:
        fold_metrics = {}
        for train_years, test_year in (([2021], 2022), ([2021, 2022], 2023)):
            train = candidates[candidates.year.isin(train_years)]
            test = candidates[candidates.year == test_year]
            predicted = score(fit_model(train, spec), test)
            route = global_route(predicted, "policy_score", spec.threshold)
            fold_metrics[str(test_year)] = account_metrics(route)
        if min(fold_metrics[str(y)]["trades"] for y in (2022, 2023)) < 15:
            continue
        fold_logs = [math.log1p(fold_metrics[str(y)]["return"]) for y in (2022, 2023)]
        scored.append({
            "spec": spec,
            "metrics": fold_metrics,
            "worst_forward_log_growth": min(fold_logs),
            "average_forward_log_growth": sum(fold_logs) / 2.0,
        })
    if not scored:
        raise RuntimeError("no model specification met the forward breadth requirement")
    scored.sort(
        key=lambda row: (row["worst_forward_log_growth"], row["average_forward_log_growth"]),
        reverse=True,
    )
    return scored[0]["spec"], scored


def freeze_pre2024_and_score(candidates: pd.DataFrame, spec: ModelSpec) -> pd.DataFrame:
    train = candidates[(candidates.year <= 2023) & candidates.label_known]
    future = candidates[candidates.year >= 2024]
    return score(fit_model(train, spec), future)
