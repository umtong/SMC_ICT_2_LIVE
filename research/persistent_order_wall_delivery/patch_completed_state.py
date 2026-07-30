from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "materialized" / "run.py"
EXPECTED_RUN_SHA256 = "657aff8de4c4cd14e7d9cec599bf4b12e3a22a819bc0d31e170014031b8af398"
OLD_FUNCTION_SHA256 = "791dc4a57c1d425d3e14598781bcceb0b2da4a0556704292121356a6f4332d05"

OLD_STATE = '''def _first_state_loss_index(
    quote_tape: dict[str, np.ndarray],
    *,
    start_idx: int,
    stop_before_idx: int,
    action: str,
    wall: WallInterval,
    direction: int,
    event_extreme: float,
) -> int | None:
    qts = quote_tape["ts"]
    mids = quote_tape["mid"]
    end_idx = min(max(stop_before_idx, start_idx + 1), len(qts))
    if start_idx >= end_idx:
        return None
    secs = qts[start_idx:end_idx] // US
    changes = np.flatnonzero(np.diff(secs)) + 1
    starts = np.concatenate(([0], changes))
    ends = np.concatenate((changes, [len(secs)]))
    for rel_lo, rel_hi in zip(starts, ends):
        segment = mids[start_idx + int(rel_lo): start_idx + int(rel_hi)]
        if segment.size == 0:
            continue
        if action == "ACCEPT":
            if direction > 0:
                lost = np.mean(segment < wall.price) >= 0.80 and segment[-1] < wall.price
            else:
                lost = np.mean(segment > wall.price) >= 0.80 and segment[-1] > wall.price
        else:
            if direction < 0:
                lost = np.mean(segment > event_extreme) >= 0.80 and segment[-1] > event_extreme
            else:
                lost = np.mean(segment < event_extreme) >= 0.80 and segment[-1] < event_extreme
        if lost:
            sec = int(secs[int(rel_lo)])
            execution_us = (sec + 1) * US + 500 * MS
            idx = _first_index_ge(qts, execution_us)
            if idx < len(qts) and idx < stop_before_idx:
                return idx
            return None
    return None
'''

NEW_STATE = '''def _first_state_loss_index(
    quote_tape: dict[str, np.ndarray],
    *,
    start_idx: int,
    stop_before_idx: int,
    action: str,
    wall: WallInterval,
    direction: int,
    event_extreme: float,
) -> int | None:
    """Return the first executable index after a *complete post-entry second* loses state.

    A partial calendar second containing the entry cannot establish state loss:
    some of that second's quote path was observed before the position existed.
    Likewise, a hard target/stop touched before the end of a candidate second
    has priority and prevents that second from becoming a completed state.
    """
    qts = quote_tape["ts"]
    mids = quote_tape["mid"]
    end_idx = min(max(stop_before_idx, start_idx + 1), len(qts))
    if start_idx >= end_idx:
        return None

    entry_us = int(qts[start_idx])
    first_window_start_us = ((entry_us + US - 1) // US) * US
    if stop_before_idx < len(qts):
        barrier_us = int(qts[stop_before_idx])
    else:
        barrier_us = int(qts[-1]) + 1

    window_start_us = first_window_start_us
    while window_start_us + US <= barrier_us:
        window_end_us = window_start_us + US
        lo = max(start_idx, _first_index_ge(qts, window_start_us))
        hi = min(end_idx, _first_index_ge(qts, window_end_us))
        if hi > lo:
            segment = mids[lo:hi]
            if action == "ACCEPT":
                if direction > 0:
                    lost = np.mean(segment < wall.price) >= 0.80 and segment[-1] < wall.price
                else:
                    lost = np.mean(segment > wall.price) >= 0.80 and segment[-1] > wall.price
            else:
                if direction < 0:
                    lost = np.mean(segment > event_extreme) >= 0.80 and segment[-1] > event_extreme
                else:
                    lost = np.mean(segment < event_extreme) >= 0.80 and segment[-1] < event_extreme
            if lost:
                execution_us = window_end_us + 500 * MS
                idx = _first_index_ge(qts, execution_us)
                if idx < len(qts) and idx < stop_before_idx:
                    return idx
                return None
        window_start_us += US
    return None
'''

OLD_TARGET = '''    entry_us = int(qts[entry_idx])
    entry_price = float(ask[entry_idx] if direction > 0 else bid[entry_idx])
    target = float(target_wall.price)
'''
NEW_TARGET = '''    entry_us = int(qts[entry_idx])
    if not (target_wall.activation_us <= entry_us < target_wall.expiry_us):
        return None
    entry_price = float(ask[entry_idx] if direction > 0 else bid[entry_idx])
    target = float(target_wall.price)
'''
OLD_SLOT = '''        if a.entry_us < slot_until:
            continue
'''
NEW_SLOT = '''        if a.entry_us <= slot_until:
            continue
'''

source = RUN.read_text()
observed = hashlib.sha256(source.encode()).hexdigest()
if observed != EXPECTED_RUN_SHA256:
    raise RuntimeError(f"unexpected frozen run.py SHA-256: {observed}")
if source.count(OLD_STATE) != 1:
    raise RuntimeError(f"expected exactly one old state-loss function, got {source.count(OLD_STATE)}")
if hashlib.sha256(OLD_STATE.encode()).hexdigest() != OLD_FUNCTION_SHA256:
    raise RuntimeError("embedded old-function identity mismatch")
if source.count(OLD_TARGET) != 1:
    raise RuntimeError(f"expected exactly one target-liveness insertion point, got {source.count(OLD_TARGET)}")
if source.count(OLD_SLOT) != 1:
    raise RuntimeError(f"expected exactly one slot-overlap condition, got {source.count(OLD_SLOT)}")

patched = source.replace(OLD_STATE, NEW_STATE).replace(OLD_TARGET, NEW_TARGET).replace(OLD_SLOT, NEW_SLOT)
compile(patched, str(RUN), "exec")
RUN.write_text(patched)
patched_sha = hashlib.sha256(patched.encode()).hexdigest()

spec = importlib.util.spec_from_file_location("persistent_wall_patched", RUN)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load patched module")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

wall = mod.WallInterval("w", "d", "BTCUSDT", "ask", 100.0, 0, 10_000_000, 1000.0, 10.0, 0.1)

qts = np.arange(1_200_000, 4_800_001, 200_000, dtype=np.int64)
mids = np.where(qts < 2_000_000, 99.0, np.where(qts < 3_000_000, 101.0, 99.0))
idx = mod._first_state_loss_index(
    {"ts": qts, "mid": mids}, start_idx=0, stop_before_idx=len(qts),
    action="ACCEPT", wall=wall, direction=1, event_extreme=100.5,
)
if idx is None or int(qts[idx]) < 4_500_000:
    raise AssertionError(f"partial-second causality failed: {idx}")

qts2 = np.arange(1_000_000, 2_800_001, 200_000, dtype=np.int64)
mids2 = np.full(qts2.size, 99.0)
idx2 = mod._first_state_loss_index(
    {"ts": qts2, "mid": mids2}, start_idx=0, stop_before_idx=len(qts2),
    action="ACCEPT", wall=wall, direction=1, event_extreme=100.5,
)
if idx2 is None or int(qts2[idx2]) < 2_500_000:
    raise AssertionError(f"boundary-second completion failed: {idx2}")

barrier_idx = int(np.searchsorted(qts, 3_600_000))
idx3 = mod._first_state_loss_index(
    {"ts": qts, "mid": mids}, start_idx=0, stop_before_idx=barrier_idx,
    action="ACCEPT", wall=wall, direction=1, event_extreme=100.5,
)
if idx3 is not None:
    raise AssertionError(f"hard-barrier priority failed: {idx3}")

quotes = pd.DataFrame({
    "local_timestamp": [1_000_000, 2_000_000, 3_000_000],
    "ask_price": [100.1, 101.1, 101.1],
    "bid_price": [100.0, 100.9, 100.9],
    "ask_amount": [1.0, 1.0, 1.0],
    "bid_amount": [1.0, 1.0, 1.0],
})
expired_target = mod.WallInterval(
    "expired", "d", "BTCUSDT", "ask", 101.0, 0, 500_000, 1000.0, 10.0, 0.1
)
expired = mod.resolve_action(
    date="d", wall=wall, action="ACCEPT", consumption_us=0,
    adjudication_end_us=0, event_extreme=100.2, consumed_qty=5.0,
    replenish_notional=0.0, beyond_fraction=1.0, target_wall=expired_target,
    quote_tape=mod.prepare_quote_tape(quotes),
    funding=pd.DataFrame(columns=["timestamp_us", "funding_rate"]),
)
if expired is not None:
    raise AssertionError("expired target wall remained tradeable")

def make_action(key: str, entry_us: int, exit_us: int) -> object:
    return mod.Action(
        event_key=key, date="d", symbol="BTCUSDT", wall_id=key,
        wall_side="ask", action="ACCEPT", direction=1,
        consumption_us=entry_us - 2, adjudication_end_us=entry_us - 1,
        entry_us=entry_us, entry_price=100.0, target_price=101.0,
        stop_price=99.0, event_extreme=100.0, exit_us=exit_us,
        exit_price=101.0, exit_reason="TARGET", target_wall_id="t",
        activation_notional=1000.0, consumed_qty=10.0,
        replenish_notional=0.0, beyond_fraction=1.0,
        holding_seconds=(exit_us-entry_us)/mod.US,
        boundary_mark=False, funding_unit_pnl=0.0,
    )

sim, ledger = mod.simulate(
    [make_action("a", 1_000_000, 2_000_000), make_action("b", 2_000_000, 3_000_000)],
    funding=pd.DataFrame(), cost_bp=0.0,
)
if sim["selected_rows"] != 1 or len(ledger) != 1:
    raise AssertionError(f"equal-timestamp global-slot adversity failed: {sim}")

print(json.dumps({
    "patched_run_sha256": patched_sha,
    "partial_second_test_execution_us": int(qts[idx]),
    "boundary_second_test_execution_us": int(qts2[idx2]),
    "hard_barrier_test": "PASS",
    "expired_target_test": "PASS",
    "equal_timestamp_slot_test": "PASS",
}, sort_keys=True))
