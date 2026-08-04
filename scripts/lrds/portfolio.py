from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import Direction, ExecutablePremise, ExitDecision


@dataclass(slots=True)
class Position:
    premise: ExecutablePremise
    quantity: float
    entry_price: float
    opened_at_ms: int
    root_invalidation_price: float
    information_exit_price: float
    objective_price: float
    proof_lineage: list[str] = field(default_factory=list)


class OneSlotPortfolio:
    """One global full-position slot with no partial entry or exit semantics."""

    def __init__(self, initial_nav: float) -> None:
        if initial_nav <= 0:
            raise ValueError("initial NAV must be positive")
        self.nav = float(initial_nav)
        self.position: Position | None = None
        self.closed: list[dict[str, float | str | int]] = []

    def enter(
        self,
        premise: ExecutablePremise,
        *,
        fill_price: float,
        available_at_ms: int,
    ) -> Position:
        if self.position is not None:
            raise RuntimeError("global position slot is already occupied")
        position = Position(
            premise=premise,
            quantity=premise.quantity,
            entry_price=float(fill_price),
            opened_at_ms=available_at_ms,
            root_invalidation_price=premise.root_invalidation_price,
            information_exit_price=premise.information_exit_price,
            objective_price=premise.objective_price,
            proof_lineage=[premise.proof_id],
        )
        self.position = position
        return position

    def adopt_child_premise(self, child: ExecutablePremise) -> None:
        position = self._position()
        parent = position.premise
        if child.hypothesis_id != parent.hypothesis_id:
            raise RuntimeError("child premise must belong to the same root hypothesis")
        if child.direction is not parent.direction:
            raise RuntimeError("opposite direction requires closing the current position first")
        if child.mode is not parent.mode:
            raise RuntimeError(
                "Core and Expansion are separate full-position trades; close the slot "
                "before changing premise mode"
            )
        if child.proof_id in position.proof_lineage:
            raise RuntimeError("a consumed proof cannot be adopted twice")

        # The emergency boundary may tighten, but never widen. The child Source owns
        # information exits independently of the root market hypothesis. Quantity is
        # never changed by a post-entry Source update.
        if child.direction is Direction.UP:
            position.root_invalidation_price = max(
                position.root_invalidation_price,
                child.root_invalidation_price,
            )
            if child.objective_price < position.objective_price:
                raise RuntimeError("child objective cannot move behind the active route")
        else:
            position.root_invalidation_price = min(
                position.root_invalidation_price,
                child.root_invalidation_price,
            )
            if child.objective_price > position.objective_price:
                raise RuntimeError("child objective cannot move behind the active route")
        position.information_exit_price = child.information_exit_price
        position.objective_price = child.objective_price
        position.premise = child
        position.proof_lineage.append(child.proof_id)

    def exit_all(
        self,
        decision: ExitDecision,
        *,
        fill_price: float,
        executed_at_ms: int,
    ) -> dict[str, float | str | int]:
        position = self._position()
        if executed_at_ms < decision.available_at_ms:
            raise RuntimeError("exit execution precedes the causal decision")
        pnl = (
            (fill_price - position.entry_price) * position.quantity
            if position.premise.direction is Direction.UP
            else (position.entry_price - fill_price) * position.quantity
        )
        self.nav += pnl
        record: dict[str, float | str | int] = {
            "scope": decision.scope.value,
            "reason": decision.reason,
            "decision_at_ms": decision.available_at_ms,
            "executed_at_ms": int(executed_at_ms),
            "entry_price": position.entry_price,
            "exit_price": float(fill_price),
            "quantity": position.quantity,
            "gross_pnl": pnl,
            "nav": self.nav,
            "proof_id": decision.proof_id or "",
            "mode": position.premise.mode.value,
            "premise_id": position.premise.premise_id,
        }
        self.closed.append(record)
        self.position = None
        return record

    def _position(self) -> Position:
        if self.position is None:
            raise RuntimeError("global position slot is empty")
        return self.position
