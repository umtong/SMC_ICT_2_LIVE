from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import causal_guard


def market_frame() -> pd.DataFrame:
    times = np.arange(
        pd.Timestamp("2021-01-01", tz="UTC").value // 1_000_000,
        pd.Timestamp("2021-01-01 04:00", tz="UTC").value // 1_000_000,
        60_000,
        dtype=np.int64,
    )
    close = 100.0 + np.linspace(0.0, 3.0, len(times))
    return pd.DataFrame(
        {
            "open_time_ms": times,
            "open": close,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "quote_volume": np.full(len(times), 1_000_000.0),
        }
    )


def test_entry_bar_close_does_not_change_entry_features() -> None:
    frame = market_frame()
    changed = frame.copy()
    j = 150
    changed.loc[j, "close"] *= 1.4
    changed.loc[j, "high"] = changed.loc[j, "close"]
    base = causal_guard.causal_returns_features(frame)
    altered = causal_guard.causal_returns_features(changed)
    for key in ("ret15", "vol60", "eff60", "prior_high", "prior_low"):
        assert np.isclose(base[key][j], altered[key][j], equal_nan=True), key
    assert not np.isclose(base["ret15"][j + 1], altered["ret15"][j + 1], equal_nan=True)


def test_unresolved_selected_path_is_fatal(tmp_path: Path) -> None:
    compact = {
        "claim_id": causal_guard.engine.CLAIM_ID,
        "status": "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1",
        "confirmation_gate": {"all": True},
        "development_gate": {"all": True},
        "development_opened": True,
        "official_2024h1_opened": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    full = {
        **compact,
        "development": {
            "costs": {
                "24": {
                    "trade_ledger": [
                        {
                            "event_id": "unresolved-event",
                            "symbol": "ETHUSDT",
                            "exit_reason": "SOURCE_BOUNDARY",
                        }
                    ]
                }
            }
        },
    }
    (tmp_path / "RESULT.json").write_text(json.dumps(compact))
    (tmp_path / "FULL_RESULT.json").write_text(json.dumps(full))
    guard = causal_guard.audit_result(tmp_path)
    corrected = json.loads((tmp_path / "RESULT.json").read_text())
    assert guard["unresolved_selected_path_count"] == 1
    assert corrected["status"] == "PRE2024_INVALID_UNRESOLVED_SELECTED_PATH"
    assert corrected["confirmation_gate"]["all"] is False
    assert corrected["development_gate"]["all"] is False
    assert (tmp_path / "SHA256SUMS.txt").is_file()
