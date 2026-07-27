#!/usr/bin/env python3
"""Correct weighted-average entry accounting in trade-tape daily NAV."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "research/yt_trinity_ml/run_public_trade_tape_validation.py"
text = TARGET.read_text(encoding="utf-8")
old_state = '''    active_symbol: str | None = None\n    active_side = 0\n    quantity = 0.0\n    entry_price = 0.0\n    output: list[dict[str, Any]] = []'''
new_state = '''    active_symbol: str | None = None\n    active_side = 0\n    quantity = 0.0\n    entry_notional = 0.0\n    entry_price = 0.0\n    output: list[dict[str, Any]] = []'''
if new_state not in text:
    if old_state not in text:
        raise SystemExit("daily NAV state anchor missing")
    text = text.replace(old_state, new_state, 1)
old_loop = '''            if event.delta_quantity > 0:\n                if quantity <= 1e-12:\n                    active_symbol = event.symbol\n                    active_side = event.side\n                    entry_price = event.entry_price\n                quantity += event.delta_quantity\n            else:\n                quantity += event.delta_quantity\n                if quantity <= 1e-12:\n                    quantity = 0.0\n                    active_symbol = None\n                    active_side = 0\n                    entry_price = 0.0'''
new_loop = '''            if event.delta_quantity > 0:\n                if quantity <= 1e-12:\n                    active_symbol = event.symbol\n                    active_side = event.side\n                    entry_notional = 0.0\n                if active_symbol != event.symbol or active_side != event.side:\n                    raise RuntimeError("global-slot position event changed symbol or side before close")\n                entry_notional += event.delta_quantity * event.entry_price\n                quantity += event.delta_quantity\n                entry_price = entry_notional / max(quantity, 1e-12)\n            else:\n                reduction = min(quantity, -event.delta_quantity)\n                entry_notional -= reduction * entry_price\n                quantity -= reduction\n                if quantity <= 1e-12:\n                    quantity = 0.0\n                    entry_notional = 0.0\n                    active_symbol = None\n                    active_side = 0\n                    entry_price = 0.0\n                else:\n                    entry_price = entry_notional / quantity'''
if new_loop not in text:
    if old_loop not in text:
        raise SystemExit("daily NAV position-event anchor missing")
    text = text.replace(old_loop, new_loop, 1)
TARGET.write_text(text, encoding="utf-8")

TEST = ROOT / "research/yt_trinity_ml/tests/test_public_trade_tape.py"
test_text = TEST.read_text(encoding="utf-8")
if "def test_daily_nav_uses_weighted_entry_after_partial_fills" not in test_text:
    test_text += '''\n\ndef test_daily_nav_uses_weighted_entry_after_partial_fills() -> None:\n    cash_events = []\n    events = [\n        tape.PositionEvent(pd.Timestamp("2024-01-01T01:00:00Z"), "BTCUSDT", 1, 1.0, 100.0),\n        tape.PositionEvent(pd.Timestamp("2024-01-01T02:00:00Z"), "BTCUSDT", 1, 1.0, 110.0),\n    ]\n    frame = mark_frame().copy()\n    frame["bar_start"] = pd.date_range("2024-01-01T00:00:00Z", periods=len(frame), freq="1min")\n    frame["mark_close"] = 120.0\n    # Extend one row before the first official day-end mark.\n    extra = frame.iloc[[-1]].copy()\n    extra.index = pd.DatetimeIndex([pd.Timestamp("2024-01-02T00:00:00Z")])\n    extra["bar_start"] = pd.Timestamp("2024-01-01T23:59:00Z")\n    combined = pd.concat([frame, extra]).sort_index()\n    daily = tape.day_end_nav(10_000.0, cash_events, events, {"BTCUSDT": combined})\n    assert daily[0]["quantity"] == 2.0\n    assert daily[0]["unrealized_pnl"] == 30.0\n    assert daily[0]["nav"] == 10_030.0\n'''
    TEST.write_text(test_text, encoding="utf-8")
print("weighted partial-fill daily NAV fix applied")
