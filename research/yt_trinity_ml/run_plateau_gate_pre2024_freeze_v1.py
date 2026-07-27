#!/usr/bin/env python3
"""Reproduce pre-2024 evidence for the frozen high-minimum-growth gate."""
from __future__ import annotations

import run_tightened_gate_pre2024_freeze_v1 as base
from run_quality_gate_ml_rank_plateau_v1 import PLATEAU_GATE


def main() -> int:
    base.TIGHTENED_GATE = PLATEAU_GATE
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
