#!/usr/bin/env python3
"""Reproduce the pre-2024 account evidence for the tightened quality gate.

Only event labels whose full outcomes are available before each evaluation boundary
are included.  Passive nonfills are zero-return orders that occupy the slot only
until their known cancellation/end time; filled trades compound whole-account NAV.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from math import exp, log
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from run_frozen_period_v1 import _budget_targets
from run_quality_gate_ml_rank_period_v1 import label_quality_mask
from run_quality_gate_ml_rank_tightened_v1 import TIGHTENED_GATE


def replay(rows: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, risk: float) -> dict[str, Any]:
    eligible = rows[
        (rows["event_start"] >= start)
        & (rows["event_start"] < end)
        & (rows["event_end"] <= end)
    ].sort_values(["event_start", "symbol", "row_id"], kind="stable")
    nav = 10_000.0
    peak = nav
    maximum_drawdown = 0.0
    slot_free = start
    orders = 0
    trades = 0
    values: list[float] = []
    chosen: list[dict[str, Any]] = []
    for row in eligible.itertuples(index=False):
        event_start = pd.Timestamp(row.event_start)
        event_end = pd.Timestamp(row.event_end)
        if event_start < slot_free:
            continue
        slot_free = event_end
        orders += 1
        value = float(row.passive_budget_r)
        chosen.append(
            {
                "row_id": int(row.row_id),
                "event_start": event_start.isoformat(),
                "event_end": event_end.isoformat(),
                "symbol": str(row.symbol),
                "family": str(row.family),
                "passive_filled": int(row.passive_filled),
                "passive_budget_r": value,
            }
        )
        if int(row.passive_filled) != 1:
            continue
        account_return = risk * value
        if account_return <= -1.0:
            nav = 0.0
            values.append(value)
            trades += 1
            break
        nav *= 1.0 + account_return
        values.append(value)
        trades += 1
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, 1.0 - nav / peak)
    days = int((end - start) / pd.Timedelta(days=1))
    growth = -1.0 if nav <= 0 else exp(log(nav / 10_000.0) / days) - 1.0
    return {
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "calendar_days": days,
        "orders": orders,
        "filled_trades": trades,
        "ending_nav": nav,
        "account_multiple": nav / 10_000.0,
        "geometric_daily_growth": growth,
        "maximum_drawdown": maximum_drawdown,
        "mean_budget_r": float(np.mean(values)) if values else None,
        "median_budget_r": float(np.median(values)) if values else None,
        "chosen": chosen,
    }


def run(labels_path: Path, output: Path, risk: float) -> dict[str, Any]:
    labels = pd.read_pickle(labels_path, compression="gzip").reset_index(drop=True)
    labels["row_id"] = np.arange(len(labels), dtype=int)
    labels["event_start"] = pd.to_datetime(labels["event_start"], utc=True)
    labels["event_end"] = pd.to_datetime(labels["event_end"], utc=True)
    if labels["event_end"].max() >= pd.Timestamp("2024-01-01", tz="UTC"):
        raise RuntimeError("label outcome crosses the 2024 information cutoff")
    labels = _budget_targets(labels)
    mask = label_quality_mask(labels, TIGHTENED_GATE)
    rows = labels[
        mask
        & labels["passive_budget_r"].notna()
        & labels["passive_filled"].notna()
    ].copy()
    h1_start = pd.Timestamp("2023-01-01", tz="UTC")
    h1_end = pd.Timestamp("2023-07-01", tz="UTC")
    h2_end = pd.Timestamp("2024-01-01", tz="UTC")
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "stage": "PRE2024_TIGHTENED_QUALITY_GATE_FREEZE",
        "information_cutoff": "2023-12-31T23:59:59Z",
        "quality_gate": asdict(TIGHTENED_GATE),
        "entry_action": "PASSIVE_RETEST_FIXED",
        "risk_fraction": risk,
        "eligible_label_rows": int(len(rows)),
        "eligible_by_symbol": {str(k): int(v) for k, v in rows["symbol"].value_counts().sort_index().items()},
        "eligible_by_family": {str(k): int(v) for k, v in rows["family"].value_counts().sort_index().items()},
        "halves": {
            "2023H1": replay(rows, h1_start, h1_end, risk),
            "2023H2": replay(rows, h1_end, h2_end, risk),
        },
        "full_2023": replay(rows, h1_start, h2_end, risk),
        "selection_note": "Chosen from a neighboring pre-2024 plateau, not from 2024 performance.",
        "ranking_effect": "NONE_PRE2024_NOT_RANKABLE",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "TIGHTENED_GATE_PRE2024_FREEZE.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--risk-fraction", type=float, default=0.17)
    args = parser.parse_args()
    result = run(args.labels, args.output, args.risk_fraction)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
