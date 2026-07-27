#!/usr/bin/env python3
"""Run the ML-ranked evaluator with the pre-2024 robust tightened gate."""
from __future__ import annotations

import run_quality_gate_ml_rank_period_v1 as base
from run_frozen_period_v1 import FrozenQualityGate


TIGHTENED_GATE = FrozenQualityGate(
    reversal_target_distance_atr_min=5.5,
    reversal_sweep_depth_atr_min=1.6,
    reversal_external_rr_min=1.0,
    continuation_stop_distance_atr_min=4.0,
    continuation_path_excursion_atr_min=7.0,
    continuation_external_rr_min=1.5,
)


def _gate_factory() -> FrozenQualityGate:
    return TIGHTENED_GATE


def main() -> int:
    # The base evaluator resolves FrozenQualityGate from its module globals when run.
    # Replacing only that constructor preserves the model, data, account and execution
    # contracts while freezing this pre-2024-selected plateau point.
    base.FrozenQualityGate = _gate_factory
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
