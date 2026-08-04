from __future__ import annotations

import pytest

from scripts.lrds.contracts import (
    Bar,
    Branch,
    ControlAttemptState,
    Direction,
    EvidenceEvent,
    EvidenceKind,
    PriceZone,
    RootHypothesis,
    RootOwnershipBasis,
)
from scripts.lrds.state_machine import AuthorizationCosts, LRDSStateMachine, ScenarioContractError


def test_btc_20230121_real_continuation_requires_full_causal_sequence() -> None:
    """Golden trace from canonical BTCUSDT 5m bars on 2023-01-21.

    00:10 consumes lower liquidity and closes down; the causal up body immediately
    before it is nominated as the short Control Source. Price must then complete a
    body below that Source, make a distinct first return, and only at 00:55 complete
    renewed downward delivery. Intermediate bars must not authorize capital.
    """

    machine = LRDSStateMachine()
    root = RootHypothesis(
        hypothesis_id="BTCUSDT:20230121:down-continuation",
        branch=Branch.CONTINUE,
        direction=Direction.DOWN,
        contact_index=5762,
        contact_time_ms=1_674_259_800_000,
        accepted_auction=PriceZone(
            "BTCUSDT:precontact-auction", 22_547.0, 22_794.0, 5750, 1_674_256_500_000
        ),
        approach_source=PriceZone(
            "BTCUSDT:approach-source", 22_625.5, 22_632.5, 5761, 1_674_259_800_000
        ),
        interaction=PriceZone(
            "BTCUSDT:lower-liquidity", 22_547.0, 22_547.0, 5700, 1_674_240_000_000
        ),
        root_invalidation_price=22_794.0,
        objective_price=21_793.5,
    )
    machine.register_hypothesis(root)
    machine.add_root_ownership(
        root.hypothesis_id,
        EvidenceEvent(
            event_id="BTCUSDT:20230121:initiative-down",
            kind=EvidenceKind.ROOT_OWNERSHIP,
            branch=Branch.CONTINUE,
            index=5762,
            available_at_ms=1_674_260_100_000,
            description=(
                "the completed interaction impulse accepted price below the lower "
                "liquidity and independently established downward initiative"
            ),
            ownership_basis=RootOwnershipBasis.PRE_RETEST_INITIATIVE,
        ),
    )
    source = PriceZone(
        "BTCUSDT:20230121:control", 22_625.5, 22_632.5, 5762, 1_674_260_100_000
    )
    machine.open_control_attempt(
        attempt_id="BTCUSDT:20230121:attempt",
        hypothesis_id=root.hypothesis_id,
        source=source,
        proof_seed=EvidenceEvent(
            event_id="BTCUSDT:20230121:mss-seed",
            kind=EvidenceKind.MSS,
            branch=Branch.CONTINUE,
            index=5762,
            available_at_ms=1_674_260_100_000,
            description="the completed interaction impulse nominated the causal up body",
            zone_id=source.zone_id,
        ),
    )

    machine.observe_bar(Bar(5763, 1_674_260_400_000, 22_513.5, 22_530.0, 22_460.5, 22_526.5))
    attempt = machine.attempts["BTCUSDT:20230121:attempt"]
    assert attempt.state is ControlAttemptState.SEPARATED

    machine.observe_bar(Bar(5764, 1_674_260_700_000, 22_526.5, 22_579.0, 22_525.0, 22_538.0))
    machine.observe_bar(Bar(5765, 1_674_261_000_000, 22_538.0, 22_600.0, 22_536.5, 22_582.0))
    machine.observe_bar(Bar(5766, 1_674_261_300_000, 22_582.0, 22_655.0, 22_582.0, 22_630.0))
    assert attempt.state is ControlAttemptState.RETESTED
    assert attempt.proof_id is None

    with pytest.raises(ScenarioContractError, match="defended Control Source"):
        machine.authorize(
            attempt_id=attempt.attempt_id,
            decision_price=22_630.0,
            nav=10_000.0,
            costs=AuthorizationCosts(5.5, 2.0),
        )

    for bar in (
        Bar(5767, 1_674_261_600_000, 22_630.0, 22_644.5, 22_556.0, 22_609.5),
        Bar(5768, 1_674_261_900_000, 22_609.5, 22_632.0, 22_590.0, 22_615.5),
        Bar(5769, 1_674_262_200_000, 22_615.5, 22_634.0, 22_585.5, 22_591.0),
        Bar(5770, 1_674_262_500_000, 22_591.0, 22_614.0, 22_579.0, 22_600.0),
    ):
        machine.observe_bar(bar)
        assert attempt.state is ControlAttemptState.RETESTED

    machine.observe_bar(Bar(5771, 1_674_262_800_000, 22_600.0, 22_608.0, 22_566.0, 22_570.5))
    assert attempt.state is ControlAttemptState.DEFENDED

    premise = machine.authorize(
        attempt_id=attempt.attempt_id,
        decision_price=22_570.5,
        nav=10_000.0,
        costs=AuthorizationCosts(5.5, 2.0),
    )
    assert premise.conservative_route_r == pytest.approx(2.888, abs=0.002)
    assert premise.quantity * premise.per_unit_planned_loss == pytest.approx(300.0)
    assert premise.information_exit_price == pytest.approx(22_632.5)
    assert premise.root_invalidation_price == pytest.approx(22_794.0)
