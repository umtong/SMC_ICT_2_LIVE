#!/usr/bin/env python3
"""Make one-hour aggregation require only causal OHLCV columns."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "research/yt_trinity_ml/run_htf_ote_continuation.py"
text = TARGET.read_text(encoding="utf-8")
old = '''    grouped = raw.groupby("hour_start", sort=True)\n    output = grouped.agg(\n        open=("open", "first"),\n        high=("high", "max"),\n        low=("low", "min"),\n        close=("close", "last"),\n        volume=("volume", "sum"),\n        turnover=("turnover", "sum"),\n        mark_close=("mark_close", "last"),\n        source_rows=("close", "size"),\n    )\n    output = output[output["source_rows"] == 12].copy()'''
new = '''    grouped = raw.groupby("hour_start", sort=True)\n    aggregation: dict[str, tuple[str, str]] = {\n        "open": ("open", "first"),\n        "high": ("high", "max"),\n        "low": ("low", "min"),\n        "close": ("close", "last"),\n        "volume": ("volume", "sum"),\n        "source_rows": ("close", "size"),\n    }\n    if "turnover" in raw.columns:\n        aggregation["turnover"] = ("turnover", "sum")\n    if "mark_close" in raw.columns:\n        aggregation["mark_close"] = ("mark_close", "last")\n    output = grouped.agg(**aggregation)\n    if "turnover" not in output.columns:\n        output["turnover"] = output["close"] * output["volume"]\n    if "mark_close" not in output.columns:\n        output["mark_close"] = output["close"]\n    output = output[output["source_rows"] == 12].copy()'''
if new not in text:
    if old not in text:
        raise SystemExit("one-hour aggregation anchor missing")
    text = text.replace(old, new, 1)
TARGET.write_text(text, encoding="utf-8")

TEST = ROOT / "research/yt_trinity_ml/tests/test_multitimeframe_canonical_index.py"
test_text = TEST.read_text(encoding="utf-8")
if "def test_one_hour_frame_requires_only_ohlcv" not in test_text:
    test_text += '''\n\ndef test_one_hour_frame_requires_only_ohlcv() -> None:\n    frame = canonical_five().drop(columns=["turnover", "mark_close"])\n    hourly = htf.one_hour_frame(frame)\n    assert not hourly.empty\n    assert {"open", "high", "low", "close", "volume", "turnover", "mark_close"} <= set(hourly.columns)\n    assert (hourly["mark_close"] == hourly["close"]).all()\n'''
    TEST.write_text(test_text, encoding="utf-8")
print("hourly optional-column fix applied")
