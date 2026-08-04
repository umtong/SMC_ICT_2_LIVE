from __future__ import annotations

from dataclasses import dataclass
import math

from .contracts import (
    Bar,
    ControlAttempt,
    ControlAttemptState,
    Direction,
    EvidenceEvent,
    EvidenceKind,
    ExecutablePremise,
    ExitDecision,
    ExitScope,
    RootHypothesis,
)


class ScenarioContractError(RuntimeError):
    """Raised when code attempts an action unsupported by the causal scenario."""


@dataclass(frozen=True, slots=True)
class AuthorizationCosts:
    fee_bps_per_side: float
    slippage_bps_per_side: float

    def __post_init__(self) -> None:
        if self.fee_bps_per_side < 0 or self.slippage_bps_per_side < 0:
            raise ValueError("costs cannot be negative")

    def round_trip_per_unit(self, price: float) -> float:
        return price * 2.0 * (self.fee_bps_per_side + self.slippage_bps_per_side) / 10_000.0


class LRDSStateMachine:
    """Hierarchical LRDS scenario state machine.

    Public root hypotheses, tactical Control attempts and capital premises have
    different owners. A local retest cannot silently become root market-state
    evidence, and a fresh Source cannot confirm its own first retest.
    """

    def __init__(self) -> None:
        self.hypotheses: dict[str, RootHypothesis] = {}
        self.attempts: dict[str, ControlAttempt] = {}
        self.consumed_proof_ids: set[str] = set()
        self.trace: list[EvidenceEvent] = []

    @staticmethod
    def _ahead(direction: Direction, current: float, target: float) -> bool:
        return target > current if direction is Direction.UP else target < current

    @staticmethod
    def _wrong_side(direction: Direction, close: float, source) -> bool:
        return close < source.low if direction is Direction.UP else close > source.high

    @staticmethod
    def _body_separated(direction: Direction, bar: Bar, source) -> bool:
        return bar.body_low > source.high if direction is Direction.UP else bar.body_high < source.low

    @staticmethod
    def _retest_redelivered(direction: Direction, bar: Bar, attempt: ControlAttempt) -> bool:
        assert attempt.retest_body_low is not None and attempt.retest_body_high is not None
        if direction is Direction.UP:
            return (
                bar.close > attempt.retest_body_high
                and bar.close > attempt.source.high
                and bar.close > bar.open
            )
        return (
            bar.close < attempt.retest_body_low
            and bar.close < attempt.source.low
            and bar.close < bar.open
        )

    def register_hypothesis(self, hypothesis: RootHypothesis) -> None:
        if hypothesis.hypothesis_id in self.hypotheses:
            raise ScenarioContractError(f"duplicate root hypothesis {hypothesis.hypothesis_id}")
        if hypothesis.contact_index < max(
            hypothesis.accepted_auction.created_index,
            hypothesis.approach_source.created_index,
            hypothesis.interaction.created_index,
        ):
            raise ScenarioContractError("root market objects must exist by the contact event")
        if not self._ahead(
            hypothesis.direction,
            hypothesis.interaction.midpoint,
            hypothesis.objective_price,
        ):
            raise ScenarioContractError("natural objective is not ahead of the interaction")
        self.hypotheses[hypothesis.hypothesis_id] = hypothesis

    def add_root_ownership(self, hypothesis_id: str, event: EvidenceEvent) -> None:
        hypothesis = self._active_hypothesis(hypothesis_id)
        if event.kind is not EvidenceKind.ROOT_OWNERSHIP:
            raise ScenarioContractError("root ownership requires ROOT_OWNERSHIP evidence")
        if event.branch is not hypothesis.branch:
            raise ScenarioContractError("root ownership branch mismatch")
        if event.index < hypothesis.contact_index:
            # Existing price discovery is the only basis allowed to predate contact.
            if event.ownership_basis is not RootOwnershipBasis.EXISTING_PRICE_DISCOVERY:
                raise ScenarioContractError("only existing discovery may predate contact")
        hypothesis.ownership_event = event
        hypothesis.evidence.append(event)
        self.trace.append(event)

    def open_control_attempt(
        self,
        *,
        attempt_id: str,
        hypothesis_id: str,
        source,
        proof_seed: EvidenceEvent,
    ) -> None:
        hypothesis = self._active_hypothesis(hypothesis_id)
        if hypothesis.ownership_event is None:
            raise ScenarioContractError("tactical Source cannot open before root ownership")
        if attempt_id in self.attempts:
            raise ScenarioContractError(f"duplicate Control attempt {attempt_id}")
        if source.created_index < hypothesis.contact_index:
            raise ScenarioContractError("Control Source cannot be backdated before liquidity contact")
        if proof_seed.branch is not hypothesis.branch or proof_seed.index != source.created_index:
            raise ScenarioContractError("Source proof seed must causally nominate this Source")
        if proof_seed.kind not in {
            EvidenceKind.MSS,
            EvidenceKind.CSD,
            EvidenceKind.SOURCE_CREATED,
        }:
            raise ScenarioContractError("unsupported Control Source proof seed")
        attempt = ControlAttempt(
            attempt_id=attempt_id,
            hypothesis_id=hypothesis_id,
            branch=hypothesis.branch,
            direction=hypothesis.direction,
            source=source,
            proof_seed=proof_seed,
            evidence=[proof_seed],
        )
        self.attempts[attempt_id] = attempt
        self.trace.append(proof_seed)

    def observe_bar(self, bar: Bar) -> tuple[EvidenceEvent, ...]:
        emitted: list[EvidenceEvent] = []
        for attempt in self.attempts.values():
            if attempt.state in {ControlAttemptState.FAILED, ControlAttemptState.CONSUMED}:
                continue
            hypothesis = self.hypotheses[attempt.hypothesis_id]
            if not hypothesis.is_active or bar.index <= attempt.source.created_index:
                continue

            if self._wrong_side(attempt.direction, bar.close, attempt.source):
                event = self._event(
                    attempt,
                    bar,
                    EvidenceKind.SOURCE_FAILED,
                    "completed price accepted through the far side of the candidate Control Source",
                )
                attempt.state = ControlAttemptState.FAILED
                attempt.failure_reason = event.description
                attempt.evidence.append(event)
                self.trace.append(event)
                emitted.append(event)
                continue

            if attempt.state is ControlAttemptState.CANDIDATE:
                if self._body_separated(attempt.direction, bar, attempt.source):
                    attempt.state = ControlAttemptState.SEPARATED
                    attempt.separated_index = bar.index
                    attempt.separated_at_ms = bar.available_at_ms
                    event = self._event(
                        attempt,
                        bar,
                        EvidenceKind.SOURCE_SEPARATED,
                        "a later completed body traded wholly on the thesis side of the pre-existing Source",
                    )
                    attempt.evidence.append(event)
                    self.trace.append(event)
                    emitted.append(event)
                continue

            if attempt.state is ControlAttemptState.SEPARATED:
                # A Source can be retested only after a separate completed body first
                # left it. The Source-creation bar and the separation bar cannot also
                # be the first retest.
                if bar.index > int(attempt.separated_index) and attempt.source.touches(bar):
                    attempt.state = ControlAttemptState.RETESTED
                    attempt.retest_index = bar.index
                    attempt.retest_at_ms = bar.available_at_ms
                    attempt.retest_body_low = bar.body_low
                    attempt.retest_body_high = bar.body_high
                    attempt.retest_extreme_low = bar.low
                    attempt.retest_extreme_high = bar.high
                    event = self._event(
                        attempt,
                        bar,
                        EvidenceKind.SOURCE_RETESTED,
                        "the first completed return reached the previously separated Source; capital still waits for renewed delivery",
                    )
                    attempt.evidence.append(event)
                    self.trace.append(event)
                    emitted.append(event)
                continue

            if attempt.state is ControlAttemptState.RETESTED:
                if bar.index <= int(attempt.retest_index):
                    continue
                if self._retest_redelivered(attempt.direction, bar, attempt):
                    attempt.state = ControlAttemptState.DEFENDED
                    attempt.defended_index = bar.index
                    attempt.defended_at_ms = bar.available_at_ms
                    attempt.proof_id = f"{attempt.attempt_id}:defended:{bar.index}"
                    event = self._event(
                        attempt,
                        bar,
                        EvidenceKind.SOURCE_DEFENDED,
                        "a later completed thesis-side body reclaimed the whole pullback body and renewed delivery",
                    )
                    attempt.evidence.append(event)
                    self.trace.append(event)
                    emitted.append(event)
        return tuple(emitted)

    def authorize(
        self,
        *,
        attempt_id: str,
        decision_price: float,
        nav: float,
        costs: AuthorizationCosts,
        risk_fraction: float = 0.03,
        minimum_route_r: float = 0.5,
    ) -> ExecutablePremise:
        attempt = self.attempts[attempt_id]
        hypothesis = self._active_hypothesis(attempt.hypothesis_id)
        if attempt.state is not ControlAttemptState.DEFENDED or attempt.proof_id is None:
            raise ScenarioContractError("capital requires a defended Control Source")
        if attempt.proof_id in self.consumed_proof_ids:
            raise ScenarioContractError("one Control proof can authorize capital only once")
        if hypothesis.ownership_event is None or hypothesis.ownership_event.ownership_basis is None:
            raise ScenarioContractError("root hypothesis lacks independent ownership")
        if not (math.isfinite(decision_price) and decision_price > 0 and nav > 0):
            raise ValueError("authorization price and NAV must be positive")
        if not self._ahead(hypothesis.direction, decision_price, hypothesis.objective_price):
            raise ScenarioContractError("natural objective is no longer ahead")
        if hypothesis.direction is Direction.UP and decision_price <= hypothesis.root_invalidation_price:
            raise ScenarioContractError("root premise already failed")
        if hypothesis.direction is Direction.DOWN and decision_price >= hypothesis.root_invalidation_price:
            raise ScenarioContractError("root premise already failed")

        information_exit = (
            attempt.source.low if attempt.direction is Direction.UP else attempt.source.high
        )
        per_unit_cost = costs.round_trip_per_unit(decision_price)
        per_unit_loss = abs(decision_price - hypothesis.root_invalidation_price) + per_unit_cost
        route_net = abs(hypothesis.objective_price - decision_price) - per_unit_cost
        route_r = route_net / per_unit_loss
        if route_r + 1e-12 < minimum_route_r:
            raise ScenarioContractError(
                "cost-adjusted natural route is below the fixed 0.5R floor"
            )
        loss_budget = nav * risk_fraction
        quantity = loss_budget / per_unit_loss
        premise = ExecutablePremise(
            premise_id=f"premise:{attempt.proof_id}",
            hypothesis_id=hypothesis.hypothesis_id,
            attempt_id=attempt.attempt_id,
            proof_id=attempt.proof_id,
            branch=hypothesis.branch,
            direction=hypothesis.direction,
            control_source=attempt.source,
            root_invalidation_price=hypothesis.root_invalidation_price,
            information_exit_price=information_exit,
            objective_price=hypothesis.objective_price,
            decision_price=decision_price,
            authorized_index=int(attempt.defended_index),
            authorized_at_ms=int(attempt.defended_at_ms),
            root_ownership_basis=hypothesis.ownership_event.ownership_basis,
            evidence_ids=tuple(
                event.event_id for event in hypothesis.evidence + attempt.evidence
            ),
            quantity=quantity,
            planned_loss_budget=loss_budget,
            per_unit_planned_loss=per_unit_loss,
            conservative_route_r=route_r,
        )
        attempt.state = ControlAttemptState.CONSUMED
        attempt.consumed_at_ms = premise.authorized_at_ms
        self.consumed_proof_ids.add(attempt.proof_id)
        return premise

    def tactical_failure(
        self,
        premise: ExecutablePremise,
        *,
        close: float,
        available_at_ms: int,
    ) -> ExitDecision | None:
        failed = (
            close < premise.information_exit_price
            if premise.direction is Direction.UP
            else close > premise.information_exit_price
        )
        if not failed:
            return None
        return ExitDecision(
            scope=ExitScope.CONTROL_ATTEMPT,
            reason=(
                "the position-owned Control Source failed; exit this position but "
                "preserve the public root hypothesis"
            ),
            available_at_ms=available_at_ms,
            proof_id=premise.proof_id,
        )

    def invalidate_root(
        self,
        hypothesis_id: str,
        *,
        reason: str,
        available_at_ms: int,
    ) -> ExitDecision:
        hypothesis = self._active_hypothesis(hypothesis_id)
        hypothesis.invalidated_at_ms = available_at_ms
        hypothesis.invalidation_reason = reason
        for attempt in self.attempts.values():
            if (
                attempt.hypothesis_id == hypothesis_id
                and attempt.state
                not in {ControlAttemptState.FAILED, ControlAttemptState.CONSUMED}
            ):
                attempt.state = ControlAttemptState.FAILED
                attempt.failure_reason = "root hypothesis invalidated"
        return ExitDecision(
            scope=ExitScope.ROOT_HYPOTHESIS,
            reason=reason,
            available_at_ms=available_at_ms,
        )

    def route_complete(
        self,
        premise: ExecutablePremise,
        *,
        available_at_ms: int,
    ) -> ExitDecision:
        return ExitDecision(
            scope=ExitScope.ROUTE_COMPLETE,
            reason=(
                "the natural objective was consumed and no confirmed extension owns "
                "a farther destination"
            ),
            available_at_ms=available_at_ms,
            proof_id=premise.proof_id,
        )

    def _active_hypothesis(self, hypothesis_id: str) -> RootHypothesis:
        try:
            hypothesis = self.hypotheses[hypothesis_id]
        except KeyError as exc:
            raise ScenarioContractError(f"unknown root hypothesis {hypothesis_id}") from exc
        if not hypothesis.is_active:
            raise ScenarioContractError(f"root hypothesis {hypothesis_id} is invalidated")
        return hypothesis

    @staticmethod
    def _event(
        attempt: ControlAttempt,
        bar: Bar,
        kind: EvidenceKind,
        description: str,
    ) -> EvidenceEvent:
        return EvidenceEvent(
            event_id=f"{attempt.attempt_id}:{kind.value}:{bar.index}",
            kind=kind,
            branch=attempt.branch,
            index=bar.index,
            available_at_ms=bar.available_at_ms,
            description=description,
            zone_id=attempt.source.zone_id,
        )
