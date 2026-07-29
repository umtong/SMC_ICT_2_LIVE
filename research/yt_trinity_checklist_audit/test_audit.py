from __future__ import annotations

import numpy as np
import pandas as pd

from research.yt_trinity_checklist_audit.audit import (
    START_MS,
    audit_target_consumption,
    direct_eligibility,
    route_direct,
    strict_masks,
)


def candidate_row(**overrides):
    payload = {
        "candidate_id": "c0",
        "decision_time": pd.Timestamp("2022-01-02", tz="UTC"),
        "symbol": "BTCUSDT",
        "side": 1,
        "family": "RAID_CISD_RETEST",
        "pool_quality": 9,
        "zone_kind": "BPR",
        "target_reference": 110.0,
        "feature__target_quality": 9,
        "feature__target_previous_day": 1.0,
        "feature__target_previous_week": 0.0,
        "feature__premium_discount_alignment": 1.0,
        "feature__htf_bias": 3.0,
    }
    payload.update(overrides)
    return payload


def test_lower_importance_target_fails_scale_matched_checklist():
    frame = pd.DataFrame([candidate_row(**{"feature__target_quality": 8})])
    frame["target_auditable"] = True
    frame["target_consumed"] = False
    mask = strict_masks(frame)["transcript_checklist_post_rejection"]
    assert not bool(mask.iloc[0])


def test_ob_only_is_not_core_efficiency_entry():
    frame = pd.DataFrame([candidate_row(zone_kind="OB")])
    frame["target_auditable"] = True
    frame["target_consumed"] = False
    mask = strict_masks(frame)["transcript_checklist_post_rejection"]
    assert not bool(mask.iloc[0])


def test_consumed_previous_day_target_is_rejected():
    frame = pd.DataFrame([candidate_row(target_reference=105.0)])
    five = pd.DataFrame(
        {
            "available_at_ms": [int(pd.Timestamp("2022-01-02", tz="UTC").value // 1_000_000)],
            "day_cum_high": [106.0],
            "day_cum_low": [90.0],
            "week_cum_high": [106.0],
            "week_cum_low": [90.0],
        }
    )
    dummy = pd.DataFrame()
    audited = audit_target_consumption(frame, {"BTCUSDT": (dummy, five, dummy)})
    assert bool(audited.loc[0, "target_auditable"])
    assert bool(audited.loc[0, "target_consumed"])


def test_low_resistance_requires_confirmed_order_flow_alignment():
    row = pd.Series(
        candidate_row(
            family="ACCEPTANCE_RETEST",
            pool_quality=7,
            **{"feature__target_quality": 9},
        )
    )
    ok, _ = direct_eligibility(
        row,
        pd.Series({"htf_bias_confirm": -3.0}),
        "lowres_direct",
    )
    assert not ok
    ok, target = direct_eligibility(
        row,
        pd.Series({"htf_bias_confirm": 3.0}),
        "lowres_direct",
    )
    assert ok and target == "PREVIOUS_DAY"


def test_unfilled_pending_order_consumes_global_slot():
    rows = pd.DataFrame(
        [
            {
                "candidate_id": "pending",
                "symbol": "BTCUSDT",
                "side": 1,
                "confirmation_time_ms": START_MS + 1_000,
                "pending_end_time_ms": START_MS + 300_000,
                "filled": False,
                "target_quality": 9,
                "pool_quality": 9,
                "direct_rr": 3.0,
                "entry_time_ms": np.nan,
                "exit_time_ms": np.nan,
                "entry_price": np.nan,
                "planned_unit_loss": np.nan,
                "unit_pnl": np.nan,
                "net_r": np.nan,
            },
            {
                "candidate_id": "blocked",
                "symbol": "ETHUSDT",
                "side": 1,
                "confirmation_time_ms": START_MS + 100_000,
                "pending_end_time_ms": START_MS + 150_000,
                "filled": True,
                "target_quality": 10,
                "pool_quality": 9,
                "direct_rr": 4.0,
                "entry_time_ms": START_MS + 120_000,
                "exit_time_ms": START_MS + 200_000,
                "entry_price": 100.0,
                "planned_unit_loss": 1.0,
                "unit_pnl": 1.0,
                "net_r": 1.0,
            },
            {
                "candidate_id": "later",
                "symbol": "ETHUSDT",
                "side": 1,
                "confirmation_time_ms": START_MS + 400_000,
                "pending_end_time_ms": START_MS + 450_000,
                "filled": True,
                "target_quality": 10,
                "pool_quality": 9,
                "direct_rr": 4.0,
                "entry_time_ms": START_MS + 420_000,
                "exit_time_ms": START_MS + 500_000,
                "entry_price": 100.0,
                "planned_unit_loss": 1.0,
                "unit_pnl": 1.0,
                "net_r": 1.0,
            },
        ]
    )
    summary, ledger = route_direct(rows, "fixture")
    assert summary["pending_orders"] == 1
    assert summary["skips"] == 1
    assert ledger["candidate_id"].tolist() == ["later"]
