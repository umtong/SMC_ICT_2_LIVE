from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("funding_transfer_screen", ROOT / "run_screen.py")
assert SPEC is not None and SPEC.loader is not None
screen = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = screen
SPEC.loader.exec_module(screen)


def _thresholds(value: float = 0.0005) -> dict:
    return {
        "funding": {symbol: {str(q): value for q in screen.FUNDING_QUANTILES} for symbol in screen.SYMBOLS},
        "premium": {symbol: {str(q): value for q in screen.PREMIUM_QUANTILES} for symbol in screen.SYMBOLS},
        "volatility": {symbol: {"q33": 0.0005, "q67": 0.0015} for symbol in screen.SYMBOLS},
    }


def _event_frame() -> pd.DataFrame:
    base = screen.DEV_START_MS
    rows = []
    for symbol, impulse, long_ret, short_ret in (
        ("BTCUSDT", 0.5, -0.01, 0.01),
        ("ETHUSDT", 0.8, -0.02, 0.02),
    ):
        row = {
            "symbol": symbol,
            "partition": "development",
            "settlement_ms": base,
            "funding_rate": 0.001,
            "abs_funding_rate": 0.001,
            "funding_sign": 1,
            "flush_direction": -1,
            "pre_premium": 0.001,
            "abs_pre_premium": 0.001,
            "premium_sign": 1,
            "premium_aligned": True,
            "pre_move_z": 0.0,
            "sigma5": 0.001,
            "confirm_bars": 1,
            "entry_ms": base + 10 * 60 * 1000,
            "entry_price": 100.0,
            "confirmation_valid": True,
            "post_impulse_z": impulse,
            "reversal_z": -impulse,
            "extension": False,
            "reclaim_fraction": 0.2,
            "post_premium": 0.0007,
            "premium_contraction": 0.3,
            "vol_bucket": "mid",
        }
        for horizon in screen.HORIZONS_MINUTES:
            row[f"exit_ms_{horizon}"] = row["entry_ms"] + horizon * 60 * 1000
            row[f"gross_long_{horizon}"] = long_ret
            row[f"gross_short_{horizon}"] = short_ret
            row[f"execution_valid_{horizon}"] = True
        rows.append(row)
    return pd.DataFrame(rows)


def test_candidate_grid_is_frozen_and_unique() -> None:
    candidates = screen.generate_candidates()
    assert len(candidates) == 720
    assert len({candidate.candidate_id for candidate in candidates}) == 720
    assert {candidate.family for candidate in candidates} == {
        "deferred_payer_flush",
        "prepaid_sweep_reversal",
        "premium_anchor_snapback",
    }


def test_request_boundary_rejects_2024() -> None:
    screen.assert_request_boundary({"end": screen.MAX_REQUEST_MS})
    with pytest.raises(AssertionError):
        screen.assert_request_boundary({"end": screen.MAX_REQUEST_MS + 1})


def test_bar_availability_delays_entry_beyond_confirmation() -> None:
    settlement = screen.DEV_START_MS
    assert screen.last_completed_bar_start(settlement) == settlement - screen.BAR_MS
    assert screen.ceil_bar(settlement) == settlement
    one_bar_entry = screen.ceil_bar(settlement) + 2 * screen.BAR_MS
    two_bar_entry = screen.ceil_bar(settlement) + 3 * screen.BAR_MS
    assert one_bar_entry == settlement + 10 * 60 * 1000
    assert two_bar_entry == settlement + 15 * 60 * 1000


def test_positive_funding_defines_short_payer_flush() -> None:
    frame = _event_frame().iloc[[0]].copy()
    candidate = screen.Candidate("deferred_payer_flush", 0.75, 0.50, 0.5, 0.25, 1, 15)
    mask, direction, score = screen._candidate_mask_and_direction_score(frame, candidate, _thresholds())
    assert mask.tolist() == [True]
    assert direction.tolist() == [-1]
    assert np.isfinite(score[0])


def test_global_slot_uses_highest_state_score() -> None:
    candidate = screen.Candidate("deferred_payer_flush", 0.75, 0.50, 0.5, 0.25, 1, 15)
    selected, raw, unresolved = screen.select_global_events(_event_frame(), candidate, _thresholds())
    assert raw == 2
    assert unresolved == 0
    assert len(selected) == 1
    assert selected.iloc[0]["symbol"] == "ETHUSDT"
    assert math.isclose(float(selected.iloc[0]["gross_return"]), 0.02, abs_tol=1e-12)


def test_same_exit_timestamp_reentry_is_prohibited() -> None:
    frame = _event_frame().iloc[[0]].copy()
    second = frame.copy()
    second["settlement_ms"] += 15 * 60 * 1000
    second["entry_ms"] = frame.iloc[0]["exit_ms_15"]
    second["exit_ms_15"] = second["entry_ms"] + 15 * 60 * 1000
    combined = pd.concat([frame, second], ignore_index=True)
    candidate = screen.Candidate("deferred_payer_flush", 0.75, 0.50, 0.5, 0.25, 1, 15)
    selected, _, _ = screen.select_global_events(combined, candidate, _thresholds())
    assert len(selected) == 1


def test_cost_replay_and_concentration_are_deterministic() -> None:
    base = screen.DEV_START_MS
    events = pd.DataFrame(
        {
            "entry_ms": [base + i * 31 * 24 * 60 * 60 * 1000 for i in range(4)],
            "gross_return": [0.01, 0.005, -0.002, 0.004],
        }
    )
    metrics12 = screen.trade_metrics(events, 12, "development")
    metrics24 = screen.trade_metrics(events, 24, "development")
    assert metrics12["total_return"] > metrics24["total_return"]
    assert metrics12["return_after_top10_positive_removal"] < metrics12["total_return"]
    assert 0 <= metrics12["maximum_drawdown"] <= 1


def test_loader_hash_matches_scientific_implementation() -> None:
    assert screen.BUNDLED_IMPLEMENTATION_SHA256 == "a5b3b5e41e6697de766ee5b3aef4712401a2350ea3e88a97f07ada57eab636fe"
