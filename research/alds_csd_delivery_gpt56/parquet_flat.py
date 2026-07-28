#!/usr/bin/env python3
"""Minimal local compatibility layer for the ALDS research modules.

The canonical repository stores flat pandas-compatible parquet files.  The
research modules deliberately depend on this tiny wrapper rather than on a
second data-processing stack.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


def read_parquet_flat(path: str | Path, columns: Iterable[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(Path(path), columns=list(columns) if columns is not None else None)
