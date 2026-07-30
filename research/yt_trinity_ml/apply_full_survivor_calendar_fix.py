#!/usr/bin/env python3
"""Normalize half-year date-range construction for timezone-aware boundaries."""

from pathlib import Path

TARGET = Path(__file__).with_name("run_full_sequential_survivor.py")
text = TARGET.read_text(encoding="utf-8")
old = 'boundaries = list(pd.date_range(OFFICIAL_START, OFFICIAL_END, freq="6MS", tz="UTC"))'
new = 'boundaries = list(pd.date_range(OFFICIAL_START, OFFICIAL_END, freq="6MS"))'
if new in text:
    print("calendar fix already present")
elif old in text:
    TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("calendar fix applied")
else:
    raise SystemExit("calendar anchor missing")
