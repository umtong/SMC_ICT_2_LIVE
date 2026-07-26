from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "run.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fair_value_raid_run", RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_self_test_contract():
    module = load_module()
    assert module.self_test() == 0


def test_2024_is_prohibited_before_network(monkeypatch, tmp_path):
    module = load_module()

    class Session:
        def get(self, *args, **kwargs):
            raise AssertionError("network must not be called for prohibited years")

    try:
        module.download_source(tmp_path, "2024-01-01", "BTCUSDT", Session())
    except module.ScientificFailure as exc:
        assert "prohibited year" in str(exc)
    else:
        raise AssertionError("2024 request was not rejected")


def test_global_slot_and_winner_removal_are_event_key_based():
    module = load_module()
    frame = module.synthetic_states()
    events = module.extract_events(
        {("2022-01-01", "BTCUSDT"): frame},
        ("2022-01-01",),
        {"BTCUSDT": {"fair_gap_abs_bps": 10.0, "last_mark_abs_bps": 10.0}},
    ).iloc[[0]].copy()
    events["route"] = "FADE_TO_FAIR_VALUE"
    events["authorized"] = True
    events["gross_bps"] = events["reversion_win_bps"]
    events["planned_loss_bps"] = events["reversion_loss_bps"]
    duplicate = events.copy()
    duplicate["event_key"] = duplicate["event_key"] + "-duplicate"
    selected = module.global_slot(module.pd.concat([events, duplicate], ignore_index=True))
    assert len(selected) == 1
    stressed = module.winner_removed(module.pd.concat([events, duplicate], ignore_index=True), ("2022-01-01",), 24.0)
    assert stressed["removed_event_count"] in {0, 1}


def test_stale_last_trade_cannot_be_a_raid():
    module = load_module()
    frame = module.synthetic_states()
    frame["last_price_age_seconds"] = 10.0
    events = module.extract_events(
        {("2022-01-01", "BTCUSDT"): frame},
        ("2022-01-01",),
        {"BTCUSDT": {"fair_gap_abs_bps": 10.0, "last_mark_abs_bps": 10.0}},
    )
    assert events.empty


def test_global_slot_reserves_from_decision_not_entry():
    module = load_module()
    base = module.synthetic_states()
    event = module.extract_events(
        {("2022-01-01", "BTCUSDT"): base},
        ("2022-01-01",),
        {"BTCUSDT": {"fair_gap_abs_bps": 10.0, "last_mark_abs_bps": 10.0}},
    ).iloc[[0]].copy()
    event["route"] = "FADE_TO_FAIR_VALUE"
    event["authorized"] = True
    event["gross_bps"] = event["reversion_win_bps"]
    event["planned_loss_bps"] = event["reversion_loss_bps"]
    first = event.copy()
    first["event_key"] = "first"
    first["decision_ts"] = 100
    first["entry_ts"] = 101
    first["exit_ts"] = 110
    pending_overlap = event.copy()
    pending_overlap["event_key"] = "pending-overlap"
    pending_overlap["decision_ts"] = 109
    pending_overlap["entry_ts"] = 110
    pending_overlap["exit_ts"] = 120
    after_exit = event.copy()
    after_exit["event_key"] = "after-exit"
    after_exit["decision_ts"] = 110
    after_exit["entry_ts"] = 111
    after_exit["exit_ts"] = 130
    selected = module.global_slot(
        module.pd.concat([first, pending_overlap, after_exit], ignore_index=True)
    )
    assert selected["event_key"].tolist() == ["first", "after-exit"]
