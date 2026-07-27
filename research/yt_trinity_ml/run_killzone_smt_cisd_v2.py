#!/usr/bin/env python3
"""Corrected launcher for killzone SMT/CISD v1.

The original opening-range helper constructed a DataFrame from a DatetimeIndex and
DatetimeIndex-keyed Series without an explicit common index.  Pandas alignment could
therefore erase the range values.  This launcher installs a positional, causal
implementation before invoking the frozen scientific path.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import run_killzone_smt_cisd_v1 as base


def opening_range_levels(frame: pd.DataFrame) -> pd.DataFrame:
    out=frame.copy(); day=out.index.floor("D"); minute=np.asarray(out.index.hour*60+out.index.minute)
    for start,name in ((0,"asia"),(420,"london"),(780,"newyork")):
        active=(minute>=start)&(minute<start+60)
        table=pd.DataFrame({"day":np.asarray(day[active]),"high":out.loc[active,"high"].to_numpy(),"low":out.loc[active,"low"].to_numpy()}).groupby("day",sort=True).agg({"high":"max","low":"min"})
        completed=minute>=start+60
        mapped_high=pd.Series(np.asarray(day),index=out.index).map(table.high)
        mapped_low=pd.Series(np.asarray(day),index=out.index).map(table.low)
        out[f"{name}_or_high"]=mapped_high.where(completed)
        out[f"{name}_or_low"]=mapped_low.where(completed)
    return out


base.opening_range_levels=opening_range_levels

if __name__=="__main__":
    raise SystemExit(base.main())
