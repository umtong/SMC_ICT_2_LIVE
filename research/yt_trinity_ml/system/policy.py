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
        # Retained only for backward-compatible ScoredCandidate objects. New model
        # outputs contain action-specific utility and never select an action by a
        # fill-probability threshold alone.
        self.passive_fill_threshold = passive_fill_threshold

    def choose(
        self,
        scored_candidates: Iterable[ScoredCandidate],
        slot_available: bool,
    ) -> SelectedDecision:
        if not slot_available:
            return SelectedDecision(PolicyDecision.ABSTAIN, None, "global entry slot occupied")

        action_rows: list[tuple[float, float, int, float, str, ScoredCandidate, PolicyDecision]] = []
        for item in scored_candidates:
            if item.market_lower_confidence_score is not None:
                market_lower = item.market_lower_confidence_score
                market_log = item.market_expected_log_growth if item.market_expected_log_growth is not None else item.expected_log_growth
                action_rows.append((market_lower, market_log, 0, item.win_probability, item.candidate.symbol, item, PolicyDecision.MARKETABLE))
                if item.passive_lower_confidence_score is not None:
                    passive_log = item.passive_expected_log_growth if item.passive_expected_log_growth is not None else item.expected_log_growth
                    action_rows.append((item.passive_lower_confidence_score, passive_log, 1, item.passive_fill_probability, item.candidate.symbol, item, PolicyDecision.PASSIVE_RETEST))
            else:
                # Legacy score: preserve prior behavior while keeping the global
                # rank by lower-confidence utility.
                action = (
                    PolicyDecision.PASSIVE_RETEST
                    if item.passive_fill_probability >= self.passive_fill_threshold
                    else PolicyDecision.MARKETABLE
                )
                action_rows.append((item.lower_confidence_score, item.expected_log_growth, int(action == PolicyDecision.PASSIVE_RETEST), item.win_probability, item.candidate.symbol, item, action))

        positive = [row for row in action_rows if row[0] > 0]
        if not positive:
            return SelectedDecision(PolicyDecision.ABSTAIN, None, "no positive lower-confidence after-cost action value")
        selected = max(positive, key=lambda row: row[:5])
        return SelectedDecision(selected[6], selected[5], "highest positive global-slot action value")
