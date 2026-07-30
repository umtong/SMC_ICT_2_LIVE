from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "materialized" / "run.py"
EXPECTED_RUN_SHA256 = "657aff8de4c4cd14e7d9cec599bf4b12e3a22a819bc0d31e170014031b8af398"
OLD_FUNCTION_SHA256 = "791dc4a57c1d425d3e14598781bcceb0b2da4a0556704292121356a6f4332d05"

OLD = '''def _first_state_loss_index(
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

NEW = '''def _first_state_loss_index(
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
        # The final source quote cannot complete a later calendar second.
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

source = RUN.read_text()
observed = hashlib.sha256(source.encode()).hexdigest()
if observed != EXPECTED_RUN_SHA256:
    raise RuntimeError(f"unexpected frozen run.py SHA-256: {observed}")
if source.count(OLD) != 1:
    raise RuntimeError(f"expected exactly one old state-loss function, got {source.count(OLD)}")
if hashlib.sha256(OLD.encode()).hexdigest() != OLD_FUNCTION_SHA256:
    raise RuntimeError("embedded old-function identity mismatch")

patched = source.replace(OLD, NEW)
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

# A losing partial entry-second must not trigger. The next complete second is
# healthy; the first full losing second is [3s,4s), executable after 4.5s.
qts = np.arange(1_200_000, 4_800_001, 200_000, dtype=np.int64)
mids = np.where(qts < 2_000_000, 99.0, np.where(qts < 3_000_000, 101.0, 99.0))
idx = mod._first_state_loss_index(
    {"ts": qts, "mid": mids}, start_idx=0, stop_before_idx=len(qts),
    action="ACCEPT", wall=wall, direction=1, event_extreme=100.5,
)
if idx is None or int(qts[idx]) < 4_500_000:
    raise AssertionError(f"partial-second causality failed: {idx}")

# Entry exactly on a second boundary permits that full second.
qts2 = np.arange(1_000_000, 2_800_001, 200_000, dtype=np.int64)
mids2 = np.full(qts2.size, 99.0)
idx2 = mod._first_state_loss_index(
    {"ts": qts2, "mid": mids2}, start_idx=0, stop_before_idx=len(qts2),
    action="ACCEPT", wall=wall, direction=1, event_extreme=100.5,
)
if idx2 is None or int(qts2[idx2]) < 2_500_000:
    raise AssertionError(f"boundary-second completion failed: {idx2}")

# A hard barrier inside the candidate full second prevents state completion.
barrier_idx = int(np.searchsorted(qts, 3_600_000))
idx3 = mod._first_state_loss_index(
    {"ts": qts, "mid": mids}, start_idx=0, stop_before_idx=barrier_idx,
    action="ACCEPT", wall=wall, direction=1, event_extreme=100.5,
)
if idx3 is not None:
    raise AssertionError(f"hard-barrier priority failed: {idx3}")

print(json.dumps({
    "patched_run_sha256": patched_sha,
    "partial_second_test_execution_us": int(qts[idx]),
    "boundary_second_test_execution_us": int(qts2[idx2]),
    "hard_barrier_test": "PASS",
}, sort_keys=True))
