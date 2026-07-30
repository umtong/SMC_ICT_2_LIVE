from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .model import ScoredCandidate


class PolicyDecision(str, Enum):
    ABSTAIN = "ABSTAIN"
    MARKETABLE = "MARKETABLE"
    PASSIVE_RETEST = "PASSIVE_RETEST"


@dataclass(frozen=True)
class SelectedDecision:
    action: PolicyDecision
    scored: ScoredCandidate | None
    reason: str


class GlobalSlotPolicy:
    def __init__(self, passive_fill_threshold: float = 0.55) -> None:
        if not 0 <= passive_fill_threshold <= 1:
            raise ValueError("passive_fill_threshold must be in [0, 1]")
        self.passive_fill_threshold = passive_fill_threshold

    def choose(
        self,
        scored_candidates: Iterable[ScoredCandidate],
        slot_available: bool,
    ) -> SelectedDecision:
        if not slot_available:
            return SelectedDecision(PolicyDecision.ABSTAIN, None, "global entry slot occupied")
        candidates = [candidate for candidate in scored_candidates if candidate.lower_confidence_score > 0]
        if not candidates:
            return SelectedDecision(PolicyDecision.ABSTAIN, None, "no positive lower-confidence after-cost log edge")
        selected = max(
            candidates,
            key=lambda item: (
                item.lower_confidence_score,
                item.expected_log_growth,
                item.win_probability,
                item.candidate.symbol,
            ),
        )
        action = (
            PolicyDecision.PASSIVE_RETEST
            if selected.passive_fill_probability >= self.passive_fill_threshold
            else PolicyDecision.MARKETABLE
        )
        return SelectedDecision(action, selected, "highest positive global-slot score")
