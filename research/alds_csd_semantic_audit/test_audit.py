from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from .audit import START_MS, route_account, semantic_masks
except ImportError:
    from audit import START_MS, route_account, semantic_masks


def base_row(**overrides):
    row = {
        "candidate_id": "c0",
        "symbol": "BTCUSDT",
        "setup": "DPC",
        "dpc_trigger": "pullback_sweep",
        "decision_time_ms": START_MS + 1_000,
        "activation_time_ms": START_MS + 1_500,
        "fill_time_ms": START_MS + 60_000,
        "exit_time_ms": START_MS + 120_000,
        "label_available_at_ms": START_MS + 120_000,
        "is_filled": 1,
        "entry": 100.0,
        "risk_per_unit": 1.0,
        "net_r": 1.0,
        "target_importance": 5.0,
        "node_importance": 3.0,
        "terminal_rr": 2.5,
        "target_external": 1,
        "csd_same_bar_confirm": 0,
        "csd_delay_bars": 1,
        "pullback_depth_atr": 0.5,
        "state_agreement": 1,
        "state_transition": 0,
    }
    row.update(overrides)
    return row


def test_same_bar_csd_is_not_a_later_retest():
    frame = pd.DataFrame([base_row(csd_same_bar_confirm=1, csd_delay_bars=0)])
    masks = semantic_masks(frame)
    assert not bool(masks["DPC_contract"].iloc[0])


def test_terminal_reversal_requires_state_transition_and_higher_target():
    invalid = base_row(setup="SRR", dpc_trigger="none", pullback_depth_atr=np.nan, state_transition=0)
    valid = base_row(
        candidate_id="c1",
        setup="SRR",
        dpc_trigger="none",
        pullback_depth_atr=np.nan,
        state_transition=1,
        target_importance=5.0,
        node_importance=3.0,
    )
    frame = pd.DataFrame([invalid, valid])
    masks = semantic_masks(frame)
    assert masks["SRR_contract"].tolist() == [False, True]


def test_pending_order_consumes_global_slot_until_label_resolution():
    pending = base_row(
        candidate_id="pending",
        is_filled=0,
        fill_time_ms=np.nan,
        exit_time_ms=np.nan,
        label_available_at_ms=START_MS + 300_000,
        net_r=0.0,
    )
    blocked = base_row(
        candidate_id="blocked",
        decision_time_ms=START_MS + 100_000,
        fill_time_ms=START_MS + 160_000,
        exit_time_ms=START_MS + 200_000,
    )
    later = base_row(
        candidate_id="later",
        decision_time_ms=START_MS + 400_000,
        fill_time_ms=START_MS + 460_000,
        exit_time_ms=START_MS + 520_000,
    )
    summary, trades = route_account(pd.DataFrame([pending, blocked, later]), "fixture")
    assert summary["pending_orders"] == 1
    assert summary["slot_skips"] == 1
    assert trades["candidate_id"].tolist() == ["later"]


def test_fixed_risk_and_notional_cap_use_current_nav():
    first = base_row(candidate_id="first", entry=100.0, risk_per_unit=1.0, net_r=1.0)
    second = base_row(
        candidate_id="second",
        decision_time_ms=START_MS + 300_000,
        fill_time_ms=START_MS + 360_000,
        exit_time_ms=START_MS + 420_000,
        entry=100.0,
        risk_per_unit=50.0,
        net_r=-1.0,
    )
    summary, trades = route_account(pd.DataFrame([first, second]), "fixture")
    assert len(trades) == 2
    assert trades.iloc[0]["quantity"] == 50.0
    assert trades.iloc[1]["quantity"] < 2.0
    assert summary["final_nav"] > 0
