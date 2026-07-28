#!/usr/bin/env python3
"""Purged chronological launcher for the corrected killzone alpha."""
from __future__ import annotations

import pandas as pd

import run_killzone_smt_cisd_v2 as corrected

base=corrected.base
_original_fit=base.fit_model


def purged_fit(train: pd.DataFrame, calibration: pd.DataFrame):
    calibration_start=pd.to_datetime(calibration["event_start"],utc=True).min()
    eligible=train[pd.to_datetime(train["event_end"],utc=True)<calibration_start].copy()
    if len(eligible)<50:
        raise ValueError(f"insufficient purged rows: {len(eligible)}")
    return _original_fit(eligible,calibration)


base.fit_model=purged_fit

if __name__=="__main__":
    raise SystemExit(base.main())
