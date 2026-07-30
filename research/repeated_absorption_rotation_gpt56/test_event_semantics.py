from __future__ import annotations

from dataclasses import dataclass

CLUSTER_SECONDS = 30 * 60

@dataclass
class State:
    first: int
    last: int
    boundary: float
    midpoint: float
    extreme: float
    count: int = 1


def update(state: State | None, decision: int, breach: int, boundary: float,
           midpoint: float, extreme: float, rearmed: bool) -> tuple[State | None, bool]:
    if state is not None and decision - state.first > CLUSTER_SECONDS:
        state = None
    if state is not None and not rearmed:
        return state, False
    if state is None:
        return State(decision, decision, boundary, midpoint, extreme), False
    state.last = decision
    state.count += 1
    state.extreme = max(state.extreme, extreme) if breach > 0 else min(state.extreme, extreme)
    if state.count >= 3:
        return None, True
    return state, False


def test_high_cluster() -> None:
    state = None
    completed = []
    for t in (0, 600, 1200):
        state, done = update(state, t, 1, 1000.0, 950.0, 1002.0, state is None or True)
        completed.append(done)
    assert completed == [False, False, True]


def test_low_cluster_symmetry() -> None:
    state = None
    for i, t in enumerate((0, 600, 1200)):
        state, done = update(state, t, -1, 900.0, 950.0, 898.0, state is None or True)
        assert done is (i == 2)


def test_no_rearm() -> None:
    state, done = update(None, 0, 1, 1000.0, 950.0, 1002.0, True)
    assert not done
    state, done = update(state, 600, 1, 1000.0, 950.0, 1003.0, False)
    assert not done and state is not None and state.count == 1


def test_cluster_expiry() -> None:
    state, _ = update(None, 0, 1, 1000.0, 950.0, 1002.0, True)
    state, _ = update(state, 600, 1, 1000.0, 950.0, 1003.0, True)
    state, done = update(state, 1861, 1, 1000.0, 950.0, 1004.0, True)
    assert not done and state is not None and state.count == 1 and state.first == 1861


if __name__ == "__main__":
    test_high_cluster(); test_low_cluster_symmetry(); test_no_rearm(); test_cluster_expiry()
    print("PASS repeated-absorption state semantics")
