#!/usr/bin/env python3
"""Fast information-value screen for the exact V3 system."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_ORIGINAL = importlib.util.module_from_spec


def _registered(spec):
    module = _ORIGINAL(spec)
    if spec.name:
        sys.modules[spec.name] = module
    return module


importlib.util.module_from_spec = _registered
import liquidity_delivery_ml_v3_runner as runner  # noqa: E402
v3 = runner.v3
v1 = runner.v1


def focused_grid():
    configs = []
    for tf in (1, 3, 5, 15):
        for sweep in (0.04, 0.10):
            for body in (0.40, 0.70, 1.00):
                for fvg in (0.00, 0.03):
                    overlaps = (False,) if fvg == 0 else (False, True)
                    for retrace in (0.50, 0.62, 0.705):
                        for require_pd in (False, True):
                            for overlap in overlaps:
                                configs.append(v1.SetupConfig(tf, sweep, body, fvg, retrace, require_pd, overlap))
    return configs


def focused_accounts():
    return [
        v1.AccountConfig(risk, leverage)
        for risk in (0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.16, 0.20, 0.25)
        for leverage in (5, 10, 20, 30, 50, 75, 100)
    ]


v3.setup_grid_v3 = focused_grid
v3.account_grid_v3 = focused_accounts
v3.v1.enrich = runner.enrich_v3_fixed
v3.enrich_v3 = runner.enrich_v3_fixed

if __name__ == "__main__":
    raise SystemExit(v3.main_v3())
