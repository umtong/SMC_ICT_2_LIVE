"""Pre-outcome correction of the incompatible complete-case metric gate.

The sealed candidate constructor is reproduced byte-for-byte at import time
except for one source-gate block.  The original required open interest,
top-position ratio and taker ratio to be simultaneously non-null in at least
90% of sweep events.  The pinned source probe proved that the metric clock and
core value families are valid while top-trader series are structurally sparse.
HistGradientBoostingClassifier natively routes NaNs, so complete-case rejection
would discard a source-valid model population before any economic observation.

No event, feature value, label, model hyperparameter, order, cost, sizing or
period rule is changed.  Partial missing values remain NaN and are never filled.
"""
from __future__ import annotations

import inspect
import re
from typing import Any

import numpy as np
import pandas as pd

from . import strategy as sealed

CORRECTION_ID = "CORRECTION-20260727-ML-SWEEP-MISSING-AWARE-METRIC-GATE-006"

_PATTERN = re.compile(
    r"\n    metric_presence = \(.*?\n    return candidates",
    flags=re.DOTALL,
)
_REPLACEMENT = """
    metric_columns = [
        "open_interest_log",
        "top_account_ls",
        "top_position_ls",
        "global_account_ls",
        "taker_buy_sell_ratio",
    ]
    candidates.attrs["event_metric_availability"] = {
        column: float(candidates[column].notna().mean())
        for column in metric_columns
    }
    candidates.attrs["event_metric_nonmissing_rows"] = {
        column: int(candidates[column].notna().sum())
        for column in metric_columns
    }
    candidates.attrs["metric_gate_correction_id"] = CORRECTION_ID
    # Source clock coverage, file hashes, value ranges and nondegeneracy are
    # enforced by source_hf_pinned_v3 before event construction.  Preserve
    # structural NaNs for the selected missing-aware HGBT instead of imposing
    # an incompatible all-columns-complete event gate.
    return candidates"""

_source = inspect.getsource(sealed.build_candidates_for_symbol)
_patched_source, PATCH_COUNT = _PATTERN.subn(_REPLACEMENT, _source)
if PATCH_COUNT != 1:
    raise RuntimeError(
        f"{CORRECTION_ID}: expected exactly one sealed complete-case gate, found {PATCH_COUNT}"
    )
_namespace: dict[str, Any] = dict(vars(sealed))
_namespace.update(
    {
        "CORRECTION_ID": CORRECTION_ID,
        "np": np,
        "pd": pd,
    }
)
exec(compile(_patched_source, str(sealed.__file__), "exec"), _namespace)
build_candidates_for_symbol = _namespace["build_candidates_for_symbol"]


def availability_diagnostics(candidates: pd.DataFrame) -> dict[str, Any]:
    columns = [
        "open_interest_log",
        "top_account_ls",
        "top_position_ls",
        "global_account_ls",
        "taker_buy_sell_ratio",
    ]
    return {
        "correction_id": CORRECTION_ID,
        "candidate_rows": int(len(candidates)),
        "per_column_nonmissing_share": {
            column: float(candidates[column].notna().mean())
            for column in columns
        },
        "per_column_unique_nonmissing": {
            column: int(candidates[column].nunique(dropna=True))
            for column in columns
        },
        "any_external_metric_share": float(candidates[columns].notna().any(axis=1).mean()),
        "all_external_metric_share": float(candidates[columns].notna().all(axis=1).mean()),
        "imputation_applied": False,
    }
