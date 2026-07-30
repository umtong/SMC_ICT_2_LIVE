"""Causal event-gated ML system derived from the YT Trinity corpus."""

from .core import (
    EventCandidate,
    EventFamily,
    FeatureConfig,
    RiskConfig,
    build_causal_features,
    generate_event_candidates,
    size_position_from_nav,
)
from .model import ChronologicalEventModel, ModelConfig, ScoredCandidate
from .policy import GlobalSlotPolicy, PolicyDecision

__all__ = [
    "ChronologicalEventModel",
    "EventCandidate",
    "EventFamily",
    "FeatureConfig",
    "GlobalSlotPolicy",
    "ModelConfig",
    "PolicyDecision",
    "RiskConfig",
    "ScoredCandidate",
    "build_causal_features",
    "generate_event_candidates",
    "size_position_from_nav",
]
