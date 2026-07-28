#!/usr/bin/env python3
"""Apply deterministic pandas compatibility fixes to the isolated ALDS runtime.

The canonical parquet schema may expose availability timestamps as pandas
nullable Int64 while trade-bar timestamps are numpy int64. pandas 2.2
requires identical dtypes for merge_asof keys. This patch normalizes only
those causal timestamp keys; no values, ordering, signals, or labels change.
"""
from __future__ import annotations

import argparse
from pathlib import Path


HTF_OLD = '''        hs = build_htf_state(h, prefix).rename(columns={"available_at_ms": f"{prefix}_known_at_ms"})
        b = pd.merge_asof(b.sort_values("start_time_ms"), hs.sort_values(f"{prefix}_known_at_ms"),
                          left_on="start_time_ms", right_on=f"{prefix}_known_at_ms",
                          direction="backward", allow_exact_matches=True).sort_values("start_time_ms").reset_index(drop=True)
'''
HTF_NEW = '''        hs = build_htf_state(h, prefix).rename(columns={"available_at_ms": f"{prefix}_known_at_ms"})
        known_col = f"{prefix}_known_at_ms"
        hs = hs[hs[known_col].notna()].copy()
        hs[known_col] = hs[known_col].astype("int64")
        b["start_time_ms"] = b["start_time_ms"].astype("int64")
        b = pd.merge_asof(b.sort_values("start_time_ms"), hs.sort_values(known_col),
                          left_on="start_time_ms", right_on=known_col,
                          direction="backward", allow_exact_matches=True).sort_values("start_time_ms").reset_index(drop=True)
'''

DAY_OLD = '''    d = d.rename(columns={"high": "d_high", "low": "d_low", "available_at_ms": "d_known_at_ms"})
    d = d[["d_high", "d_low", "d_known_at_ms"]]
    b = pd.merge_asof(b.sort_values("start_time_ms"), d.sort_values("d_known_at_ms"),
'''
DAY_NEW = '''    d = d.rename(columns={"high": "d_high", "low": "d_low", "available_at_ms": "d_known_at_ms"})
    d = d[["d_high", "d_low", "d_known_at_ms"]]
    d = d[d["d_known_at_ms"].notna()].copy()
    d["d_known_at_ms"] = d["d_known_at_ms"].astype("int64")
    b["start_time_ms"] = b["start_time_ms"].astype("int64")
    b = pd.merge_asof(b.sort_values("start_time_ms"), d.sort_values("d_known_at_ms"),
'''


def apply(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if HTF_NEW in source and DAY_NEW in source:
        return
    if source.count(HTF_OLD) != 1:
        raise RuntimeError("unexpected HTF merge_asof source shape")
    if source.count(DAY_OLD) != 1:
        raise RuntimeError("unexpected daily merge_asof source shape")
    source = source.replace(HTF_OLD, HTF_NEW).replace(DAY_OLD, DAY_NEW)
    path.write_text(source, encoding="utf-8")
    compiled = path.read_text(encoding="utf-8")
    if HTF_NEW not in compiled or DAY_NEW not in compiled:
        raise RuntimeError("runtime compatibility patch did not persist")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    apply(args.path)


if __name__ == "__main__":
    main()
