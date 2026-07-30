#!/usr/bin/env python3
"""Run the ML-ranked evaluator with the pre-2024 high-minimum-growth gate."""
from __future__ import annotations

import run_quality_gate_ml_rank_period_v1 as base
from run_frozen_period_v1 import FrozenQualityGate


PLATEAU_GATE = FrozenQualityGate(
    reversal_target_distance_atr_min=5.5,
    reversal_sweep_depth_atr_min=1.2,
    reversal_external_rr_min=1.2,
    continuation_stop_distance_atr_min=4.0,
    continuation_path_excursion_atr_min=7.0,
    continuation_external_rr_min=1.5,
)


def _gate_factory() -> FrozenQualityGate:
    return PLATEAU_GATE


def main() -> int:
    base.FrozenQualityGate = _gate_factory
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
