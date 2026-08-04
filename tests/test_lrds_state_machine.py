from __future__ import annotations

import pytest

from scripts.lrds import (
    Bar,
    Branch,
    ControlAttemptState,
    Direction,
    EvidenceEvent,
    EvidenceKind,
    ExitScope,
    LRDSStateMachine,
    OneSlotPortfolio,
    PriceZone,
    RootOwnershipBasis,
    ScenarioContractError,
)
from scripts.lrds.contracts import RootHypothesis
from scripts.lrds.state_machine import AuthorizationCosts


def zone(zone_id: str, low: float, high: float, index: int = 0) -> PriceZone:
    return PriceZone(zone_id, low, high, index, index * 60_000)


def hypothesis(
    *,
    branch: Branch = Branch.CONTINUE,
    direction: Direction = Direction.UP,
) -> RootHypothesis:
    if direction is Direction.UP:
        objective, invalidation = 112.0, 94.0
    else:
        objective, invalidation = 88.0, 106.0
    return RootHypothesis(
        hypothesis_id=f"root:{branch.value}:{direction.name}",
        branch=branch,
        direction=direction,
        contact_index=3,
        contact_time_ms=240_000,
        accepted_auction=zone("auction", 95.0, 100.0, 0),
        approach_source=zone("approach", 98.0, 99.0, 1),
        interaction=zone("interaction", 100.0, 100.0, 2),
        root_invalidation_price=invalidation,
        objective_price=objective,
    )


def root_event(
    root: RootHypothesis,
    basis: RootOwnershipBasis,
    index: int = 3,
) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=f"root-proof:{basis.value}:{index}",
        kind=EvidenceKind.ROOT_OWNERSHIP,
        branch=root.branch,
        index=index,
        available_at_ms=(index + 1) * 60_000,
        description="independent root market-state ownership",
        ownership_basis=basis,
    )


def source_seed(
    root: RootHypothesis,
    source: PriceZone,
    kind: EvidenceKind = EvidenceKind.MSS,
) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=f"seed:{source.zone_id}",
        kind=kind,
        branch=root.branch,
        index=source.created_index,
        available_at_ms=source.available_at_ms,
        description="fresh causal impulse nominated a candidate Control Source",
        zone_id=source.zone_id,
    )


def prepared_machine() -> tuple[LRDSStateMachine, RootHypothesis, PriceZone]:
    machine = LRDSStateMachine()
    root = hypothesis()
    machine.register_hypothesis(root)
    machine.add_root_ownership(
        root.hypothesis_id,
        root_event(root, RootOwnershipBasis.PRE_RETEST_INITIATIVE),
    )
    source = zone("control", 101.0, 102.0, 4)
    machine.open_control_attempt(
        attempt_id="attempt-1",
        hypothesis_id=root.hypothesis_id,
        source=source,
        proof_seed=source_seed(root, source),
    )
    return machine, root, source


def test_fresh_source_cannot_confirm_itself_or_skip_separation() -> None:
    machine, _, _ = prepared_machine()
    machine.observe_bar(Bar(4, 300_000, 101.2, 103.0, 101.0, 102.8))
    attempt = machine.attempts["attempt-1"]
    assert attempt.state is ControlAttemptState.CANDIDATE

    machine.observe_bar(Bar(5, 360_000, 101.8, 102.6, 101.4, 102.2))
    assert attempt.state is ControlAttemptState.CANDIDATE

    with pytest.raises(ScenarioContractError, match="defended Control Source"):
        machine.authorize(
            attempt_id="attempt-1",
            decision_price=102.2,
            nav=10_000.0,
            costs=AuthorizationCosts(5.5, 2.0),
        )


def test_source_requires_departure_first_return_and_later_redelivery() -> None:
    machine, _, _ = prepared_machine()
    machine.observe_bar(Bar(5, 360_000, 102.4, 103.2, 102.3, 103.0))
    attempt = machine.attempts["attempt-1"]
    assert attempt.state is ControlAttemptState.SEPARATED

    machine.observe_bar(Bar(6, 420_000, 103.0, 103.1, 101.5, 101.8))
    assert attempt.state is ControlAttemptState.RETESTED
    assert attempt.proof_id is None

    machine.observe_bar(Bar(7, 480_000, 101.8, 103.6, 101.7, 103.4))
    assert attempt.state is ControlAttemptState.DEFENDED
    assert attempt.proof_id == "attempt-1:defended:7"


def test_local_tactical_evidence_cannot_replace_independent_root_ownership() -> None:
    machine = LRDSStateMachine()
    root = hypothesis()
    machine.register_hypothesis(root)
    source = zone("control", 101.0, 102.0, 4)
    with pytest.raises(ScenarioContractError, match="root ownership"):
        machine.open_control_attempt(
            attempt_id="attempt",
            hypothesis_id=root.hypothesis_id,
            source=source,
            proof_seed=source_seed(root, source, EvidenceKind.CSD),
        )


def test_defended_source_authorizes_one_cost_adjusted_full_premise() -> None:
    machine, root, _ = prepared_machine()
    machine.observe_bar(Bar(5, 360_000, 102.4, 103.2, 102.3, 103.0))
    machine.observe_bar(Bar(6, 420_000, 103.0, 103.1, 101.5, 101.8))
    machine.observe_bar(Bar(7, 480_000, 101.8, 103.6, 101.7, 103.4))
    premise = machine.authorize(
        attempt_id="attempt-1",
        decision_price=103.4,
        nav=10_000.0,
        costs=AuthorizationCosts(5.5, 2.0),
    )
    assert premise.planned_loss_budget == pytest.approx(300.0)
    assert premise.quantity * premise.per_unit_planned_loss == pytest.approx(300.0)
    assert premise.information_exit_price == 101.0
    assert premise.root_invalidation_price == root.root_invalidation_price
    assert premise.conservative_route_r >= 0.5

    with pytest.raises(ScenarioContractError, match="authorize capital only once"):
        machine.attempts["attempt-1"].state = ControlAttemptState.DEFENDED
        machine.authorize(
            attempt_id="attempt-1",
            decision_price=103.4,
            nav=10_000.0,
            costs=AuthorizationCosts(5.5, 2.0),
        )


def test_tactical_failure_exits_position_without_killing_public_root() -> None:
    machine, root, _ = prepared_machine()
    machine.observe_bar(Bar(5, 360_000, 102.4, 103.2, 102.3, 103.0))
    machine.observe_bar(Bar(6, 420_000, 103.0, 103.1, 101.5, 101.8))
    machine.observe_bar(Bar(7, 480_000, 101.8, 103.6, 101.7, 103.4))
    premise = machine.authorize(
        attempt_id="attempt-1",
        decision_price=103.4,
        nav=10_000.0,
        costs=AuthorizationCosts(5.5, 2.0),
    )
    portfolio = OneSlotPortfolio(10_000.0)
    portfolio.enter(premise, fill_price=103.4, available_at_ms=480_500)
    decision = machine.tactical_failure(
        premise,
        close=100.9,
        available_at_ms=540_000,
    )
    assert decision is not None and decision.scope is ExitScope.CONTROL_ATTEMPT
    portfolio.exit_all(decision, fill_price=100.8)
    assert portfolio.position is None
    assert machine.hypotheses[root.hypothesis_id].is_active


def test_root_invalidation_kills_root_and_future_attempts() -> None:
    machine, root, _ = prepared_machine()
    decision = machine.invalidate_root(
        root.hypothesis_id,
        reason="the pre-contact accepted auction was reclaimed from the wrong side",
        available_at_ms=600_000,
    )
    assert decision.scope is ExitScope.ROOT_HYPOTHESIS
    assert not machine.hypotheses[root.hypothesis_id].is_active
    new_source = zone("new-source", 102.0, 103.0, 9)
    with pytest.raises(ScenarioContractError, match="invalidated"):
        machine.open_control_attempt(
            attempt_id="new-attempt",
            hypothesis_id=root.hypothesis_id,
            source=new_source,
            proof_seed=source_seed(root, new_source),
        )


def test_child_source_changes_information_owner_without_changing_quantity() -> None:
    machine, root, _ = prepared_machine()
    machine.observe_bar(Bar(5, 360_000, 102.4, 103.2, 102.3, 103.0))
    machine.observe_bar(Bar(6, 420_000, 103.0, 103.1, 101.5, 101.8))
    machine.observe_bar(Bar(7, 480_000, 101.8, 103.6, 101.7, 103.4))
    parent = machine.authorize(
        attempt_id="attempt-1",
        decision_price=103.4,
        nav=10_000.0,
        costs=AuthorizationCosts(5.5, 2.0),
    )
    portfolio = OneSlotPortfolio(10_000.0)
    position = portfolio.enter(parent, fill_price=103.4, available_at_ms=480_500)
    original_quantity = position.quantity

    root.objective_price = 116.0
    child_source = zone("child-control", 104.0, 105.0, 8)
    machine.open_control_attempt(
        attempt_id="attempt-2",
        hypothesis_id=root.hypothesis_id,
        source=child_source,
        proof_seed=source_seed(root, child_source),
    )
    machine.observe_bar(Bar(9, 600_000, 105.4, 106.0, 105.3, 105.8))
    machine.observe_bar(Bar(10, 660_000, 105.8, 105.9, 104.4, 104.6))
    machine.observe_bar(Bar(11, 720_000, 104.6, 106.4, 104.5, 106.2))
    child = machine.authorize(
        attempt_id="attempt-2",
        decision_price=106.2,
        nav=portfolio.nav,
        costs=AuthorizationCosts(5.5, 2.0),
    )
    portfolio.adopt_child_premise(child)
    assert portfolio.position is not None
    assert portfolio.position.quantity == original_quantity
    assert portfolio.position.information_exit_price == child_source.low
    assert portfolio.position.proof_lineage == [parent.proof_id, child.proof_id]


def test_one_global_slot_and_no_partial_semantics() -> None:
    machine, _, _ = prepared_machine()
    machine.observe_bar(Bar(5, 360_000, 102.4, 103.2, 102.3, 103.0))
    machine.observe_bar(Bar(6, 420_000, 103.0, 103.1, 101.5, 101.8))
    machine.observe_bar(Bar(7, 480_000, 101.8, 103.6, 101.7, 103.4))
    premise = machine.authorize(
        attempt_id="attempt-1",
        decision_price=103.4,
        nav=10_000.0,
        costs=AuthorizationCosts(5.5, 2.0),
    )
    portfolio = OneSlotPortfolio(10_000.0)
    portfolio.enter(premise, fill_price=103.4, available_at_ms=480_500)
    with pytest.raises(RuntimeError, match="already occupied"):
        portfolio.enter(premise, fill_price=103.5, available_at_ms=481_000)


@pytest.mark.parametrize(
    (
        "direction",
        "source_bounds",
        "separation_bar",
        "retest_bar",
        "redelivery_bar",
        "decision_price",
    ),
    [
        (
            Direction.UP,
            (101.0, 102.0),
            Bar(5, 360_000, 102.4, 103.2, 102.3, 103.0),
            Bar(6, 420_000, 103.0, 103.1, 101.5, 101.8),
            Bar(7, 480_000, 101.8, 103.6, 101.7, 103.4),
            103.4,
        ),
        (
            Direction.DOWN,
            (98.0, 99.0),
            Bar(5, 360_000, 97.6, 97.7, 96.8, 97.0),
            Bar(6, 420_000, 97.0, 98.5, 96.9, 98.2),
            Bar(7, 480_000, 98.2, 98.3, 96.4, 96.6),
            96.6,
        ),
    ],
)
def test_control_lifecycle_is_directionally_symmetric(
    direction: Direction,
    source_bounds: tuple[float, float],
    separation_bar: Bar,
    retest_bar: Bar,
    redelivery_bar: Bar,
    decision_price: float,
) -> None:
    machine = LRDSStateMachine()
    root = hypothesis(direction=direction)
    machine.register_hypothesis(root)
    machine.add_root_ownership(
        root.hypothesis_id,
        root_event(root, RootOwnershipBasis.PRE_RETEST_INITIATIVE),
    )
    source = zone("symmetric-control", *source_bounds, 4)
    machine.open_control_attempt(
        attempt_id="symmetric-attempt",
        hypothesis_id=root.hypothesis_id,
        source=source,
        proof_seed=source_seed(root, source, EvidenceKind.CSD),
    )
    machine.observe_bar(separation_bar)
    machine.observe_bar(retest_bar)
    machine.observe_bar(redelivery_bar)
    attempt = machine.attempts["symmetric-attempt"]
    assert attempt.state is ControlAttemptState.DEFENDED
    premise = machine.authorize(
        attempt_id="symmetric-attempt",
        decision_price=decision_price,
        nav=10_000.0,
        costs=AuthorizationCosts(5.5, 2.0),
    )
    assert premise.direction is direction
    assert premise.quantity > 0


def test_source_failure_before_first_retest_retires_only_that_attempt() -> None:
    machine, root, _ = prepared_machine()
    machine.observe_bar(Bar(5, 360_000, 101.5, 101.8, 100.6, 100.8))
    attempt = machine.attempts["attempt-1"]
    assert attempt.state is ControlAttemptState.FAILED
    assert root.is_active
    with pytest.raises(ScenarioContractError, match="defended Control Source"):
        machine.authorize(
            attempt_id="attempt-1",
            decision_price=101.0,
            nav=10_000.0,
            costs=AuthorizationCosts(5.5, 2.0),
        )


def test_non_discovery_root_evidence_cannot_be_backdated_before_contact() -> None:
    machine = LRDSStateMachine()
    root = hypothesis()
    machine.register_hypothesis(root)
    with pytest.raises(ScenarioContractError, match="only existing discovery"):
        machine.add_root_ownership(
            root.hypothesis_id,
            root_event(root, RootOwnershipBasis.PRE_RETEST_INITIATIVE, index=2),
        )

    discovery = root_event(
        root,
        RootOwnershipBasis.EXISTING_PRICE_DISCOVERY,
        index=2,
    )
    machine.add_root_ownership(root.hypothesis_id, discovery)
    assert root.ownership_event is discovery


def test_competing_branch_needs_its_own_root_and_control_proofs() -> None:
    machine = LRDSStateMachine()
    continuation = hypothesis(branch=Branch.CONTINUE, direction=Direction.UP)
    rotation = hypothesis(branch=Branch.ROTATE, direction=Direction.DOWN)
    rotation.hypothesis_id = "root:rotate:DOWN"
    machine.register_hypothesis(continuation)
    machine.register_hypothesis(rotation)
    machine.add_root_ownership(
        continuation.hypothesis_id,
        root_event(continuation, RootOwnershipBasis.PRE_RETEST_INITIATIVE),
    )
    source = zone("rotation-control", 98.0, 99.0, 4)
    with pytest.raises(ScenarioContractError, match="root ownership"):
        machine.open_control_attempt(
            attempt_id="rotation-attempt",
            hypothesis_id=rotation.hypothesis_id,
            source=source,
            proof_seed=source_seed(rotation, source, EvidenceKind.CSD),
        )
