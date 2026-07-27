#!/usr/bin/env python3
"""Exclude absolute HTF levels from the OTE model feature vector."""

from pathlib import Path

TARGET = Path(__file__).with_name("run_htf_ote_continuation.py")
text = TARGET.read_text(encoding="utf-8")
old_numeric = '''def numeric_row(row: pd.Series) -> dict[str, float]:\n    return {\n        str(key): float(value)\n        for key, value in row.items()\n        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)\n    }'''
new_numeric = '''HTF_ABSOLUTE_FEATURES = {\n    "htf_atr", "htf_ema_fast", "htf_ema_slow", "htf_ema_long",\n    "htf_last_swing_high", "htf_last_swing_low",\n    "htf_previous_day_high", "htf_previous_day_low",\n    "htf_previous_week_high", "htf_previous_week_low",\n}\n\n\ndef numeric_row(row: pd.Series) -> dict[str, float]:\n    return {\n        str(key): float(value)\n        for key, value in row.items()\n        if key not in HTF_ABSOLUTE_FEATURES\n        and isinstance(value, (int, float, np.integer, np.floating))\n        and np.isfinite(value)\n    }'''
if new_numeric not in text:
    if old_numeric not in text:
        raise SystemExit("numeric feature anchor missing")
    text = text.replace(old_numeric, new_numeric, 1)
text = text.replace('            "ote_lower": ote_lower,\n            "ote_upper": ote_upper,\n', '')
TARGET.write_text(text, encoding="utf-8")
print("HTF OTE stationarity fix applied")
