#!/usr/bin/env python3
"""Remove absolute price/volume levels from the CISD action-value feature set."""

from pathlib import Path

TARGET = Path(__file__).with_name("run_cisd_bpr_ifvg_research.py")
text = TARGET.read_text(encoding="utf-8")
anchor = 'VARIANT_CODE = {"BPR": 1.0, "IFVG": 2.0, "CISD_FVG": 3.0}\n'
constant = '''VARIANT_CODE = {"BPR": 1.0, "IFVG": 2.0, "CISD_FVG": 3.0}\nABSOLUTE_FEATURES = {\n    "open", "high", "low", "close", "volume", "turnover", "mark_close", "body",\n    "ema_fast", "ema_slow", "ema_long", "vwap",\n    "confirmed_pivot_high", "confirmed_pivot_low", "last_swing_high", "last_swing_low",\n    "previous_day_high", "previous_day_low", "previous_week_high", "previous_week_low",\n    "bull_fvg_lower", "bull_fvg_upper", "bear_fvg_lower", "bear_fvg_upper",\n    "last_bull_fvg_lower", "last_bull_fvg_upper", "last_bear_fvg_lower", "last_bear_fvg_upper",\n    "decision_position",\n}\n'''
old_features = '''        self.feature_names = [\n            name for name in ordered.columns\n            if name not in excluded and pd.api.types.is_numeric_dtype(ordered[name])\n        ]'''
new_features = '''        self.feature_names = [\n            name for name in ordered.columns\n            if name not in excluded\n            and name not in ABSOLUTE_FEATURES\n            and pd.api.types.is_numeric_dtype(ordered[name])\n        ]'''
changed = False
if "ABSOLUTE_FEATURES = {" not in text:
    if anchor not in text:
        raise SystemExit("variant anchor missing")
    text = text.replace(anchor, constant, 1)
    changed = True
if new_features not in text:
    if old_features not in text:
        raise SystemExit("feature selection anchor missing")
    text = text.replace(old_features, new_features, 1)
    changed = True
if changed:
    TARGET.write_text(text, encoding="utf-8")
    print("stationarity guard applied")
else:
    print("stationarity guard already present")
