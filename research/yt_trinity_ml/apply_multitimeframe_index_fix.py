#!/usr/bin/env python3
"""Fix as-of joins when canonical availability exists as both index and column."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def patch(path: Path, function_name: str) -> None:
    text = path.read_text(encoding="utf-8")
    old = '''    left = five.reset_index().rename(columns={five.index.name or "index": "decision_time"})\n    right_reset = right.reset_index().rename(columns={right.index.name or "index": "htf_available_at"})'''
    new = '''    # Canonical frames retain availability as both an index and a column.\n    # Resetting that index directly can collide with the existing column.\n    left = five.copy()\n    left["decision_time"] = pd.DatetimeIndex(five.index).as_unit("ns")\n    left = left.reset_index(drop=True)\n    right_reset = right.copy()\n    right_reset["htf_available_at"] = pd.DatetimeIndex(right.index).as_unit("ns")\n    right_reset = right_reset.reset_index(drop=True)'''
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"{function_name} join anchor missing in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    patch(
        ROOT / "research/yt_trinity_ml/run_htf_ote_continuation.py",
        "attach_htf_context",
    )
    patch(
        ROOT / "research/yt_trinity_ml/run_session_po3_research.py",
        "attach_hourly",
    )
    tests = ROOT / "research/yt_trinity_ml/tests/test_multitimeframe_canonical_index.py"
    if not tests.exists():
        tests.write_text(
            '''from __future__ import annotations\n\nimport numpy as np\nimport pandas as pd\n\nimport run_htf_ote_continuation as htf\nimport run_session_po3_research as po3\n\n\ndef canonical_five(count: int = 1200) -> pd.DataFrame:\n    starts = pd.date_range("2022-01-01T00:00:00Z", periods=count, freq="5min")\n    available = starts + pd.Timedelta(minutes=5)\n    wave = np.sin(np.arange(count) / 25.0)\n    close = 100.0 + np.cumsum(0.02 + 0.1 * wave)\n    open_ = np.r_[close[0], close[:-1]]\n    frame = pd.DataFrame({\n        "start_time_ms": starts.asi8 // 1_000_000,\n        "available_at_ms": available.asi8 // 1_000_000,\n        "timestamp": starts,\n        "available_at": available,\n        "bar_start": starts,\n        "open": open_,\n        "high": np.maximum(open_, close) + 0.5,\n        "low": np.minimum(open_, close) - 0.5,\n        "close": close,\n        "volume": 100.0 + np.arange(count) % 17,\n        "turnover": (100.0 + np.arange(count) % 17) * close,\n        "mark_close": close,\n    }, index=available)\n    frame.index.name = "available_at"\n    return frame\n\n\ndef test_htf_ote_handles_available_at_index_and_column() -> None:\n    frame = canonical_five()\n    features, rows = htf.generate_candidates(frame, "BTCUSDT")\n    assert len(features) == len(frame)\n    assert features.index.equals(frame.index)\n    assert isinstance(rows, list)\n\n\ndef test_session_po3_handles_available_at_index_and_column() -> None:\n    frame = canonical_five()\n    features, rows = po3.generate_candidates(frame, "BTCUSDT")\n    assert len(features) == len(frame)\n    assert features.index.equals(frame.index)\n    assert isinstance(rows, list)\n''',
            encoding="utf-8",
        )
    print("multitimeframe canonical-index fix applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
