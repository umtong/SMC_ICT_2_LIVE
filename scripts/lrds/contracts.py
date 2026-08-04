from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
import math


class Direction(IntEnum):
    DOWN = -1
    UP = 1

    @property
    def opposite(self) -> "Direction":
        return Direction(-int(self))


class Branch(str, Enum):
    CONTINUE = "continue"
    ROTATE = "rotate"


class PremiseMode(str, Enum):
    """Capital role owned by one full-position premise.

    CORE completes the first natural liquidity route. EXPANSION is a separate later
    trade authorized only by new post-Core promotion evidence. It is never a partial
    runner retained from the Core position.
    """

    CORE = "core"
    EXPANSION = "expansion"


class RootOwnershipBasis(str, Enum):
    """Independent evidence that owns the root market hypothesis.

    A tactical Source retest is intentionally absent. It can prove the entry
    location, but it cannot by itself prove market-wide continuation/rotation.
    """

    PRE_RETEST_INITIATIVE = "pre_retest_initiative"
    EXISTING_PRICE_DISCOVERY = "existing_price_discovery"
    PRECONTACT_STRUCTURE_BREAK = "precontact_structure_break"
    ACCEPTED_VALUE_MIGRATION = "accepted_value_migration"
    AUCTION_RECLAIM = "auction_reclaim"
    DIRECT_CONTROL_SHIFT = "direct_control_shift"
    PROMOTED_BOUNDARY = "promoted_boundary"


class EvidenceKind(str, Enum):
    ROOT_OWNERSHIP = "root_ownership"
    SOURCE_CREATED = "source_created"
    SOURCE_SEPARATED = "source_separated"
    SOURCE_RETESTED = "source_retested"
    SOURCE_DEFENDED = "source_defended"
    SOURCE_FAILED = "source_failed"
    ROOT_INVALIDATED = "root_invalidated"
    OBJECTIVE_CONSUMED = "objective_consumed"
    BOUNDARY_PROMOTED = "boundary_promoted"
    MSS = "mss"
    CSD = "csd"
    VALUE_ACCEPTED = "value_accepted"
    VALUE_REJECTED = "value_rejected"


class ControlAttemptState(str, Enum):
    CANDIDATE = "candidate"
    SEPARATED = "separated"
    RETESTED = "retested"
    DEFENDED = "defended"
    FAILED = "failed"
    CONSUMED = "consumed"


class ExitScope(str, Enum):
    CONTROL_ATTEMPT = "control_attempt"
    ROOT_HYPOTHESIS = "root_hypothesis"
    ROUTE_COMPLETE = "route_complete"


@dataclass(frozen=True, slots=True)
class PriceZone:
    zone_id: str
    low: float
    high: float
    created_index: int
    available_at_ms: int

    def __post_init__(self) -> None:
        if not self.zone_id:
            raise ValueError("zone_id is required")
        if not (math.isfinite(self.low) and math.isfinite(self.high)):
            raise ValueError("zone prices must be finite")
        if self.low > self.high:
            raise ValueError("zone low exceeds high")
        if self.created_index < 0 or self.available_at_ms < 0:
            raise ValueError("zone availability cannot be negative")

    @property
    def midpoint(self) -> float:
        return 0.5 * (self.low + self.high)

    def touches(self, bar: "Bar") -> bool:
        return bar.high >= self.low and bar.low <= self.high


@dataclass(frozen=True, slots=True)
class Bar:
    index: int
    available_at_ms: int
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        values = (self.open, self.high, self.low, self.close)
        if self.index < 0 or self.available_at_ms < 0:
            raise ValueError("bar identity cannot be negative")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("bar prices must be finite")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar OHLC geometry is invalid")
        if self.low > self.high:
            raise ValueError("bar low exceeds high")

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    event_id: str
    kind: EvidenceKind
    branch: Branch
    index: int
    available_at_ms: int
    description: str
    zone_id: str | None = None
    ownership_basis: RootOwnershipBasis | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.description:
            raise ValueError("evidence identity and description are required")
        if self.index < 0 or self.available_at_ms < 0:
            raise ValueError("evidence availability cannot be negative")
        if self.kind is EvidenceKind.ROOT_OWNERSHIP and self.ownership_basis is None:
            raise ValueError("root ownership evidence requires a basis")
        if self.kind is EvidenceKind.BOUNDARY_PROMOTED:
            if self.ownership_basis is not RootOwnershipBasis.PROMOTED_BOUNDARY:
                raise ValueError("boundary promotion requires PROMOTED_BOUNDARY ownership")


@dataclass(frozen=True, slots=True)
class ExecutablePremise:
    premise_id: str
    hypothesis_id: str
    attempt_id: str
    proof_id: str
    mode: PremiseMode
    branch: Branch
    direction: Direction
    control_source: PriceZone
    root_invalidation_price: float
    information_exit_price: float
    objective_price: float
    decision_price: float
    authorized_index: int
    authorized_at_ms: int
    root_ownership_basis: RootOwnershipBasis
    evidence_ids: tuple[str, ...]
    quantity: float
    planned_loss_budget: float
    per_unit_planned_loss: float
    conservative_route_r: float
    parent_premise_id: str | None = None
    promotion_event_id: str | None = None

    def __post_init__(self) -> None:
        scalars = (
            self.root_invalidation_price,
            self.information_exit_price,
            self.objective_price,
            self.decision_price,
            self.quantity,
            self.planned_loss_budget,
            self.per_unit_planned_loss,
            self.conservative_route_r,
        )
        if not all(math.isfinite(value) for value in scalars):
            raise ValueError("premise numeric fields must be finite")
        if self.quantity <= 0 or self.planned_loss_budget <= 0 or self.per_unit_planned_loss <= 0:
            raise ValueError("premise sizing must be positive")
        if self.conservative_route_r < 0.5:
            raise ValueError("premise violates the fixed 0.5R economic floor")
        if self.mode is PremiseMode.CORE:
            if self.parent_premise_id is not None or self.promotion_event_id is not None:
                raise ValueError("Core premise cannot carry Expansion parent/promotion identity")
            if self.root_ownership_basis is RootOwnershipBasis.PROMOTED_BOUNDARY:
                raise ValueError("Core premise cannot be owned by a later promotion")
        else:
            if not self.parent_premise_id or not self.promotion_event_id:
                raise ValueError("Expansion premise requires completed Core and promotion identity")
            if self.root_ownership_basis is not RootOwnershipBasis.PROMOTED_BOUNDARY:
                raise ValueError("Expansion premise requires promoted-boundary ownership")


@dataclass(frozen=True, slots=True)
class ExitDecision:
    scope: ExitScope
    reason: str
    available_at_ms: int
    proof_id: str | None = None


@dataclass(slots=True)
class RootHypothesis:
    hypothesis_id: str
    branch: Branch
    direction: Direction
    contact_index: int
    contact_time_ms: int
    accepted_auction: PriceZone
    approach_source: PriceZone
    interaction: PriceZone
    root_invalidation_price: float
    objective_price: float
    ownership_event: EvidenceEvent | None = None
    invalidated_at_ms: int | None = None
    invalidation_reason: str | None = None
    evidence: list[EvidenceEvent] = field(default_factory=list)
    completed_core_premises: dict[str, int] = field(default_factory=dict)
    promotion_events: dict[str, EvidenceEvent] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.invalidated_at_ms is None


@dataclass(slots=True)
class ControlAttempt:
    attempt_id: str
    hypothesis_id: str
    branch: Branch
    direction: Direction
    source: PriceZone
    proof_seed: EvidenceEvent
    mode: PremiseMode = PremiseMode.CORE
    parent_premise_id: str | None = None
    promotion_event_id: str | None = None
    state: ControlAttemptState = ControlAttemptState.CANDIDATE
    separated_index: int | None = None
    separated_at_ms: int | None = None
    retest_index: int | None = None
    retest_at_ms: int | None = None
    retest_body_low: float | None = None
    retest_body_high: float | None = None
    retest_extreme_low: float | None = None
    retest_extreme_high: float | None = None
    defended_index: int | None = None
    defended_at_ms: int | None = None
    proof_id: str | None = None
    failure_reason: str | None = None
    consumed_at_ms: int | None = None
    evidence: list[EvidenceEvent] = field(default_factory=list)
