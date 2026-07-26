from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("funding_cash_oi_screen", ROOT / "run_screen.py")
assert SPEC is not None and SPEC.loader is not None
screen = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = screen
SPEC.loader.exec_module(screen)


def thresholds() -> dict:
    return {
        "actual_notional": {symbol: {"0.5": 100.0, "0.75": 150.0} for symbol in screen.SYMBOLS},
        "balance_sheet_stress": {symbol: {"0.5": 2.0, "0.75": 3.0} for symbol in screen.SYMBOLS},
        "volatility": {symbol: {"q33": 0.001, "q67": 0.002} for symbol in screen.SYMBOLS},
    }


def event_frame() -> pd.DataFrame:
    base = screen.date_start_us("2023-01-01")
    rows = []
    for symbol, transfer, post_oi, post_price, long_ret, short_ret in (
        ("BTCUSDT", 200.0, -1.2, 0.5, -0.01, 0.01),
        ("ETHUSDT", 300.0, -1.5, 0.8, -0.02, 0.02),
    ):
        row = {
            "symbol": symbol,
            "partition": "development",
            "source_date": "2023-01-01",
            "settlement_us": base + 8 * 60 * 60 * 1_000_000,
            "funding_rate": 0.001,
            "flush_direction": -1,
            "transfer_notional": transfer,
            "balance_sheet_stress": 4.0,
            "pre_price_z": 0.0,
            "pre_oi_z": 0.0,
            "price_sigma": 0.0015,
            "confirm_bars": 1,
            "entry_boundary_us": base + 8 * 60 * 60 * 1_000_000 + 10 * 60 * 1_000_000,
            "entry_observed_us": base + 8 * 60 * 60 * 1_000_000 + 10 * 60 * 1_000_000 + 100_000,
            "confirmation_valid": True,
            "post_price_z": post_price,
            "reversal_z": -post_price,
            "post_oi_z": post_oi,
            "extension": False,
            "reclaim_fraction": 0.0,
            "vol_bucket": "mid",
        }
        for horizon in screen.HORIZONS_MINUTES:
            row[f"exit_boundary_us_{horizon}"] = row["entry_boundary_us"] + horizon * 60 * 1_000_000
            row[f"execution_valid_{horizon}"] = True
            row[f"gross_long_{horizon}"] = long_ret
            row[f"gross_short_{horizon}"] = short_ret
        rows.append(row)
    return pd.DataFrame(rows)


def test_candidate_grid_is_frozen_and_unique() -> None:
    candidates = screen.generate_candidates()
    assert len(candidates) == 512
    assert len({candidate.candidate_id for candidate in candidates}) == 512
    assert {candidate.family for candidate in candidates} == {
        "payer_closure_cascade",
        "receiver_releverage_impulse",
        "prepaid_deleverage_reversal",
    }


def test_source_url_prohibits_2024_and_nonfirst_day() -> None:
    assert "/2023/12/01/BTCUSDT.csv.gz" in screen.source_url("2023-12-01", "BTCUSDT")
    with pytest.raises(AssertionError):
        screen.source_url("2024-01-01", "BTCUSDT")
    with pytest.raises(AssertionError):
        screen.source_url("2023-12-02", "BTCUSDT")


def test_event_reconstruction_uses_actual_transfer_notional_and_extra_bar() -> None:
    source = screen.synthetic_source("2022-01-01", "BTCUSDT")
    bars = screen.build_bars(source)
    events, coverage = screen.reconstruct_events(source, bars, "BTCUSDT", "2022-01-01", "fit")
    assert coverage["valid_settlements"] == 2
    assert len(events) == 4
    first = events.sort_values(["settlement_us", "confirm_bars"]).iloc[0]
    availability = source[
        (source["funding_timestamp"] == first["settlement_us"])
        & (source["local_timestamp"] >= first["settlement_us"])
    ].iloc[0]
    expected = abs(float(availability["funding_rate"])) * float(availability["open_interest"]) * float(availability["mark_price"])
    assert first["transfer_notional"] == pytest.approx(expected)
    assert first["balance_sheet_stress"] > 0
    assert first["entry_boundary_us"] == first["settlement_us"] + 10 * 60 * 1_000_000
    assert 0 <= first["entry_delay_us"] <= screen.MAX_FRESH_US


def test_payer_closure_routes_in_flush_direction() -> None:
    candidate = screen.Candidate(
        "payer_closure_cascade", "actual_notional", 0.5, 1.0, 0.25, None, 1, 15
    )
    frame = event_frame().iloc[[0]].copy()
    mask, direction, score = screen.candidate_mask_direction_score(frame, candidate, thresholds())
    assert mask.tolist() == [True]
    assert direction.tolist() == [-1]
    assert np.isfinite(score[0])


def test_receiver_releverage_requires_oi_expansion() -> None:
    candidate = screen.Candidate(
        "receiver_releverage_impulse", "balance_sheet_stress", 0.5, 1.0, 0.25, None, 1, 15
    )
    frame = event_frame().iloc[[0]].copy()
    mask, _, _ = screen.candidate_mask_direction_score(frame, candidate, thresholds())
    assert mask.tolist() == [False]
    frame.loc[:, "post_oi_z"] = 1.2
    mask, direction, _ = screen.candidate_mask_direction_score(frame, candidate, thresholds())
    assert mask.tolist() == [True]
    assert direction.tolist() == [-1]


def test_prepaid_reversal_requires_pre_deleveraging_extension_and_reclaim() -> None:
    candidate = screen.Candidate(
        "prepaid_deleverage_reversal", "actual_notional", 0.5, 0.5, 0.5, 0.25, 1, 15
    )
    frame = event_frame().iloc[[0]].copy()
    frame.loc[:, "pre_oi_z"] = -0.8
    frame.loc[:, "pre_price_z"] = 0.8
    frame.loc[:, "post_oi_z"] = -0.1
    frame.loc[:, "post_price_z"] = -0.5
    frame.loc[:, "reversal_z"] = 0.5
    frame.loc[:, "extension"] = True
    frame.loc[:, "reclaim_fraction"] = 0.7
    mask, direction, _ = screen.candidate_mask_direction_score(frame, candidate, thresholds())
    assert mask.tolist() == [True]
    assert direction.tolist() == [1]


def test_global_slot_selects_highest_transfer_state_score() -> None:
    candidate = screen.Candidate(
        "payer_closure_cascade", "actual_notional", 0.5, 1.0, 0.25, None, 1, 15
    )
    selected, raw, unresolved = screen.select_global_events(event_frame(), candidate, thresholds())
    assert raw == 2
    assert unresolved == 0
    assert len(selected) == 1
    assert selected.iloc[0]["symbol"] == "ETHUSDT"
    assert selected.iloc[0]["gross_return"] == pytest.approx(0.02)


def test_same_exit_timestamp_reentry_is_prohibited() -> None:
    candidate = screen.Candidate(
        "payer_closure_cascade", "actual_notional", 0.5, 1.0, 0.25, None, 1, 15
    )
    first = event_frame().iloc[[0]].copy()
    second = first.copy()
    second.loc[:, "entry_boundary_us"] = first.iloc[0]["exit_boundary_us_15"]
    second.loc[:, "exit_boundary_us_15"] = second.iloc[0]["entry_boundary_us"] + 15 * 60 * 1_000_000
    selected, _, _ = screen.select_global_events(pd.concat([first, second], ignore_index=True), candidate, thresholds())
    assert len(selected) == 1


def test_cost_replay_cannot_improve_with_higher_cost() -> None:
    base = screen.date_start_us("2023-01-01")
    events = pd.DataFrame(
        {
            "entry_boundary_us": [base + index * 31 * 24 * 60 * 60 * 1_000_000 for index in range(4)],
            "gross_return": [0.01, 0.005, -0.002, 0.004],
        }
    )
    low = screen.metrics(events, 12, 0, 4)
    high = screen.metrics(events, 24, 0, 4)
    assert low["total_return"] > high["total_return"]
    assert low["return_after_top10_positive_removal"] < low["total_return"]


def test_loader_hash_matches_frozen_scientific_implementation() -> None:
    assert screen.BUNDLED_IMPLEMENTATION_SHA256 == "ef44113ddbc8c11f362bbc943269c99d62ea497e017ce725b4723b3c2de56688"
