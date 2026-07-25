from __future__ import annotations

import numpy as np
import pandas as pd

import cross_venue_execution_v5 as base
import cross_venue_signals_v5d as signals

_PATCHED = False


def prepare_basis_v5d(frame: pd.DataFrame) -> None:
    if frame.attrs.get("_v5d_basis_prepared"):
        return
    common = signals._common(frame)
    valid = common["valid"]
    basis = np.log(frame.bb_mid.where(valid)) - np.log(frame.bn_mid.where(valid))
    frame["_v5_basis"] = basis
    frame["_v5_basis_median"] = common["basis_median"]
    frame.attrs["_v5d_basis_prepared"] = True


def patch() -> None:
    global _PATCHED
    if _PATCHED:
        return
    base._prepare_basis = prepare_basis_v5d
    _PATCHED = True
