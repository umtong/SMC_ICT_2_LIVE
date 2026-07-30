#!/usr/bin/env python3
"""Preserve file order and skip days with no possible structural interaction."""

from pathlib import Path

TARGET = Path(__file__).with_name("run_public_trade_tape_validation.py")
text = TARGET.read_text(encoding="utf-8")

old_frame = '''            "side": frame[side_column].astype(str).str.lower() if side_column else "",\n            "sequence": frame[sequence_column].astype(str) if sequence_column else np.arange(len(frame)).astype(str),\n        }\n    )'''
new_frame = '''            "side": frame[side_column].astype(str).str.lower() if side_column else "",\n            "sequence": frame[sequence_column].astype(str) if sequence_column else np.arange(len(frame)).astype(str),\n            "row_order": np.arange(len(frame), dtype=np.int64),\n        }\n    )'''
if new_frame not in text:
    if old_frame not in text:
        raise SystemExit("trade-frame anchor missing")
    text = text.replace(old_frame, new_frame, 1)
old_sort = 'result = result.sort_values(["timestamp", "sequence"], kind="stable").reset_index(drop=True)'
new_sort = 'result = result.sort_values(["timestamp", "row_order"], kind="stable").reset_index(drop=True)'
if new_sort not in text:
    if old_sort not in text:
        raise SystemExit("trade-sort anchor missing")
    text = text.replace(old_sort, new_sort, 1)

anchor = '''def resolve_signal(\n    signal: FrozenSignal,'''
helper = '''def day_requires_trade_archive(\n    signal: FrozenSignal,\n    day: pd.Timestamp,\n    activation: pd.Timestamp,\n    mark_frame: pd.DataFrame,\n    entry_filled: float,\n    open_quantity: float,\n) -> bool:\n    if signal.chosen_action == "MARKETABLE" and entry_filled <= 0:\n        return day == activation.floor("D")\n    start = max(day, activation)\n    end = min(day + pd.Timedelta(days=1), OFFICIAL_END)\n    bars = mark_frame.loc[(mark_frame["bar_start"] >= start) & (mark_frame["bar_start"] < end)]\n    if bars.empty:\n        raise ArchiveGap(f"no one-minute interaction index for {signal.symbol} {day.date()}")\n    low = float(bars["low"].min())\n    high = float(bars["high"].max())\n    if open_quantity > 1e-12:\n        return low <= signal.stop_reference or high >= signal.target_reference\n    if signal.side > 0:\n        return low < signal.entry_reference or low <= signal.stop_reference or high >= signal.target_reference\n    return high > signal.entry_reference or high >= signal.stop_reference or low <= signal.target_reference\n\n\ndef resolve_signal(\n    signal: FrozenSignal,'''
if helper not in text:
    if anchor not in text:
        raise SystemExit("resolve anchor missing")
    text = text.replace(anchor, helper, 1)

old_loop = '''    while day < OFFICIAL_END.floor("D") + pd.Timedelta(days=1):\n        trades = archive.get(signal.symbol, day)\n        subset = trades.loc['''
new_loop = '''    while day < OFFICIAL_END.floor("D") + pd.Timedelta(days=1):\n        if not day_requires_trade_archive(\n            signal, day, activation, mark_frame, entry_filled, open_quantity\n        ):\n            day += pd.Timedelta(days=1)\n            cursor = day\n            if day >= OFFICIAL_END:\n                break\n            continue\n        trades = archive.get(signal.symbol, day)\n        subset = trades.loc['''
if new_loop not in text:
    if old_loop not in text:
        raise SystemExit("day-loop anchor missing")
    text = text.replace(old_loop, new_loop, 1)
TARGET.write_text(text, encoding="utf-8")
print("trade-tape efficiency and order fix applied")
