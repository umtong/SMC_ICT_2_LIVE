from __future__ import annotations

import pytest

from scripts.lrds import (
    Bar,
    Branch,
    Direction,
    EvidenceEvent,
    EvidenceKind,
    LRDSStateMachine,
    OneSlotPortfolio,
    PremiseMode,
    PriceZone,
    RootOwnershipBasis,
    ScenarioContractError,
)
from scripts.lrds.contracts import RootHypothesis
from scripts.lrds.state_machine import AuthorizationCosts


COSTS = AuthorizationCosts(5.5, 2.0)


def zone(zone_id: str, low: float, high: float, index: int) -> PriceZone:
    return PriceZone(zone_id, low, high, index, index * 60_000)


def root_machine() -> tuple[LRDSStateMachine, RootHypothesis]:
    machine = LRDSStateMachine()
    root = RootHypothesis(
        hypothesis_id="root:accepted-delivery",
        branch=Branch.CONTINUE,
        direction=Direction.UP,
        contact_index=3,
        contact_time_ms=240_000,
        accepted_auction=zone("auction", 95.0, 100.0, 0),
        approach_source=zone("approach", 98.0, 99.0, 1),
        interaction=zone("interaction", 100.0, 100.0, 2),
        root_invalidation_price=94.0,
        objective_price=110.0,
    )
    machine.register_hypothesis(root)
    machine.add_root_ownership(
        root.hypothesis_id,
        EvidenceEvent(
            event_id="root-initiative",
            kind=EvidenceKind.ROOT_OWNERSHIP,
            branch=root.branch,
            index=3,
            available_at_ms=240_000,
            description="outside acceptance independently owns the Core route",
            ownership_basis=RootOwnershipBasis.PRE_RETEST_INITIATIVE,
        ),
    )
    return machine, root


def seed(root: RootHypothesis, source: PriceZone, event_id: str) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=event_id,
        kind=EvidenceKind.MSS,
        branch=root.branch,
        index=source.created_index,
        available_at_ms=source.available_at_ms,
        description="fresh completed impulse nominated a Control Source",
        zone_id=source.zone_id,
    )


def defend_attempt(
    machine: LRDSStateMachine,
    *,
    attempt_id: str,
    source: PriceZone,
    start_index: int,
) -> None:
    machine.observe_bar(
        Bar(start_index, start_index * 60_000, source.high + 0.4, source.high + 1.2, source.high + 0.3, source.high + 1.0)
    )
    machine.observe_bar(
        Bar(start_index + 1, (start_index + 1) * 60_000, source.high + 1.0, source.high + 1.1, source.midpoint, source.high - 0.2)
    )
    machine.observe_bar(
        Bar(start_index + 2, (start_index + 2) * 60_000, source.high - 0.2, source.high + 1.6, source.high - 0.3, source.high + 1.4)
    )
    assert machine.attempts[attempt_id].proof_id is not None


def authorize_core(
    machine: LRDSStateMachine,
    root: RootHypothesis,
) -> tuple[OneSlotPortfolio, object]:
    source = zone("core-control", 101.0, 102.0, 4)
    machine.open_control_attempt(
        attempt_id="core-attempt",
        hypothesis_id=root.hypothesis_id,
        source=source,
        proof_seed=seed(root, source, "core-seed"),
    )
    defend_attempt(machine, attempt_id="core-attempt", source=source, start_index=5)
    premise = machine.authorize(
        attempt_id="core-attempt",
        decision_price=103.4,
        nav=10_000.0,
        costs=COSTS,
    )
    assert premise.mode is PremiseMode.CORE
    portfolio = OneSlotPortfolio(10_000.0)
    portfolio.enter(premise, fill_price=103.4, available_at_ms=480_500)
    return portfolio, premise


def promotion(
    root: RootHypothesis,
    *,
    event_id: str,
    index: int,
    available_at_ms: int,
) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=event_id,
        kind=EvidenceKind.BOUNDARY_PROMOTED,
        branch=root.branch,
        index=index,
        available_at_ms=available_at_ms,
        description="a later completed same-direction expansion promoted the frozen boundary",
        zone_id=root.interaction.zone_id,
        ownership_basis=RootOwnershipBasis.PROMOTED_BOUNDARY,
    )


def test_expansion_cannot_exist_before_full_core_completion() -> None:
    machine, root = root_machine()
    _, core = authorize_core(machine, root)
    with pytest.raises(ScenarioContractError, match="completed Core"):
        machine.add_expansion_promotion(
            root.hypothesis_id,
            parent_premise_id=core.premise_id,
            event=promotion(root, event_id="promotion", index=9, available_at_ms=600_000),
        )


def test_promotion_must_be_new_information_after_core_completion() -> None:
    machine, root = root_machine()
    portfolio, core = authorize_core(machine, root)
    completed_at = 600_000
    decision = machine.route_complete(core, available_at_ms=completed_at)
    portfolio.exit_all(decision, fill_price=110.0)
    with pytest.raises(ScenarioContractError, match="new information"):
        machine.add_expansion_promotion(
            root.hypothesis_id,
            parent_premise_id=core.premise_id,
            event=promotion(
                root,
                event_id="same-time-promotion",
                index=9,
                available_at_ms=completed_at,
            ),
        )


def test_core_and_expansion_are_separate_full_positions_with_new_sizing() -> None:
    machine, root = root_machine()
    portfolio, core = authorize_core(machine, root)
    core_quantity = core.quantity
    completed_at = 600_000
    decision = machine.route_complete(core, available_at_ms=completed_at)
    portfolio.exit_all(decision, fill_price=110.0)
    nav_after_core = portfolio.nav
    assert portfolio.position is None
    assert portfolio.closed[-1]["mode"] == PremiseMode.CORE.value

    promoted = promotion(
        root,
        event_id="promotion-after-core",
        index=10,
        available_at_ms=660_000,
    )
    machine.add_expansion_promotion(
        root.hypothesis_id,
        parent_premise_id=core.premise_id,
        event=promoted,
    )
    root.objective_price = 120.0
    expansion_source = zone("expansion-control", 110.5, 111.5, 11)
    machine.open_control_attempt(
        attempt_id="expansion-attempt",
        hypothesis_id=root.hypothesis_id,
        source=expansion_source,
        proof_seed=seed(root, expansion_source, "expansion-seed"),
        mode=PremiseMode.EXPANSION,
        parent_premise_id=core.premise_id,
        promotion_event_id=promoted.event_id,
    )
    defend_attempt(
        machine,
        attempt_id="expansion-attempt",
        source=expansion_source,
        start_index=12,
    )
    expansion = machine.authorize(
        attempt_id="expansion-attempt",
        decision_price=113.0,
        nav=nav_after_core,
        costs=COSTS,
    )
    assert expansion.mode is PremiseMode.EXPANSION
    assert expansion.parent_premise_id == core.premise_id
    assert expansion.promotion_event_id == promoted.event_id
    assert expansion.root_ownership_basis is RootOwnershipBasis.PROMOTED_BOUNDARY
    assert expansion.planned_loss_budget == pytest.approx(nav_after_core * 0.03)
    assert expansion.quantity != pytest.approx(core_quantity)

    position = portfolio.enter(
        expansion,
        fill_price=113.0,
        available_at_ms=840_500,
    )
    assert position.quantity == expansion.quantity
    assert position.premise.mode is PremiseMode.EXPANSION
    expansion_exit = machine.route_complete(expansion, available_at_ms=960_000)
    portfolio.exit_all(expansion_exit, fill_price=120.0)
    assert [record["mode"] for record in portfolio.closed] == ["core", "expansion"]


def test_expansion_premise_cannot_be_adopted_as_core_child() -> None:
    machine, root = root_machine()
    portfolio, core = authorize_core(machine, root)
    # Build a valid Expansion ancestry in the public state, but leave the Core slot
    # occupied. The portfolio must reject changing modes as a child update.
    root.completed_core_premises[core.premise_id] = 600_000
    promoted = promotion(root, event_id="promotion", index=10, available_at_ms=660_000)
    machine.add_expansion_promotion(
        root.hypothesis_id,
        parent_premise_id=core.premise_id,
        event=promoted,
    )
    root.objective_price = 120.0
    source = zone("expansion-control", 110.5, 111.5, 11)
    machine.open_control_attempt(
        attempt_id="expansion-attempt",
        hypothesis_id=root.hypothesis_id,
        source=source,
        proof_seed=seed(root, source, "expansion-seed"),
        mode=PremiseMode.EXPANSION,
        parent_premise_id=core.premise_id,
        promotion_event_id=promoted.event_id,
    )
    defend_attempt(machine, attempt_id="expansion-attempt", source=source, start_index=12)
    expansion = machine.authorize(
        attempt_id="expansion-attempt",
        decision_price=113.0,
        nav=portfolio.nav,
        costs=COSTS,
    )
    with pytest.raises(RuntimeError, match="separate full-position trades"):
        portfolio.adopt_child_premise(expansion)


def test_root_reacceptance_after_promotion_prevents_expansion_entry() -> None:
    machine, root = root_machine()
    portfolio, core = authorize_core(machine, root)
    completion = machine.route_complete(core, available_at_ms=600_000)
    portfolio.exit_all(completion, fill_price=110.0)
    promoted = promotion(root, event_id="promotion", index=10, available_at_ms=660_000)
    machine.add_expansion_promotion(
        root.hypothesis_id,
        parent_premise_id=core.premise_id,
        event=promoted,
    )
    machine.invalidate_root(
        root.hypothesis_id,
        reason="completed price reaccepted inside the promoted frozen boundary",
        available_at_ms=720_000,
    )
    source = zone("late-expansion-control", 110.5, 111.5, 12)
    with pytest.raises(ScenarioContractError, match="invalidated"):
        machine.open_control_attempt(
            attempt_id="late-expansion-attempt",
            hypothesis_id=root.hypothesis_id,
            source=source,
            proof_seed=seed(root, source, "late-expansion-seed"),
            mode=PremiseMode.EXPANSION,
            parent_premise_id=core.premise_id,
            promotion_event_id=promoted.event_id,
        )
