#!/usr/bin/env python3
"""Quality-gated causal exit-geometry research.

The frequency gate was selected only from 2023 H1/H2 stability before this exit
study.  Exit variants are selected on 2023H1 and frozen on 2023H2.  This wrapper
keeps the exact marketable-entry/cost simulator from ``run_exit_geometry_v1`` but
removes the 2,981 candidates outside the preselected structural gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import run_exit_geometry_v1 as base


GATE = {
    "reversal_target_distance_atr_min": 5.5,
    "reversal_sweep_depth_atr_min": 1.0,
    "reversal_external_rr_min": 1.0,
    "continuation_stop_distance_atr_min": 3.5,
    "continuation_path_excursion_atr_min": 5.0,
    "continuation_external_rr_min": 2.0,
}


def gate_mask(rows: pd.DataFrame) -> pd.Series:
    family = rows["family"].astype(str)
    reward_risk = pd.to_numeric(rows["raw_reward_risk"], errors="coerce")
    reversal = (
        family.eq("LIQUIDITY_SWEEP_REVERSAL")
        & pd.to_numeric(rows["target_distance_atr"], errors="coerce").ge(
            GATE["reversal_target_distance_atr_min"]
        )
        & pd.to_numeric(rows["sweep_depth_atr"], errors="coerce").ge(
            GATE["reversal_sweep_depth_atr_min"]
        )
        & reward_risk.ge(GATE["reversal_external_rr_min"])
    )
    continuation = (
        family.eq("DISPLACEMENT_BREAK_RETEST_CONTINUATION")
        & pd.to_numeric(rows["stop_distance_atr"], errors="coerce").ge(
            GATE["continuation_stop_distance_atr_min"]
        )
        & pd.to_numeric(rows["path_excursion_atr"], errors="coerce").ge(
            GATE["continuation_path_excursion_atr_min"]
        )
        & reward_risk.ge(GATE["continuation_external_rr_min"])
    )
    return reversal | continuation


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    labels = pd.read_pickle(args.labels, compression="gzip")
    selected = labels.loc[gate_mask(labels)].copy().reset_index(drop=True)
    if selected.empty:
        raise RuntimeError("frequency gate selected zero labels")
    filtered_path = args.output / "QUALITY_GATE_LABELS.pkl.gz"
    selected.to_pickle(filtered_path, compression="gzip")

    code = base.run(
        SimpleNamespace(
            labels=filtered_path,
            btc_bars=args.btc_bars,
            eth_bars=args.eth_bars,
            output=args.output,
        )
    )
    result_path = args.output / "EXIT_GEOMETRY_RESULT.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["stage"] = "PRE2024_QUALITY_GATED_EXIT_GEOMETRY_H1_DISCOVERY_H2_VALIDATION_NOT_RANKABLE"
    payload["quality_gate"] = GATE
    payload["source_label_rows"] = int(len(labels))
    payload["quality_gate_rows"] = int(len(selected))
    payload["quality_gate_labels_sha256"] = hashlib.sha256(filtered_path.read_bytes()).hexdigest()
    payload["entry_contract"] = "MARKETABLE_500MS_DIAGNOSTIC"
    payload["selection_contract"] = "EXIT_VARIANT_H1_ONLY_GATE_PRESELECTED_FROM_2023_STABILITY"
    payload["ranking_effect"] = "NONE_PRE2024_NOT_RANKABLE"
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--btc-bars", type=Path, required=True)
    parser.add_argument("--eth-bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
