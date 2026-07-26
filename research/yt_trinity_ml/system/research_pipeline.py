from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
import json

import numpy as np
import pandas as pd

from .coarse import CoarseEventReplay, CoarseExecutionConfig, CoarseLabeler
from .core import (
    EventCandidate,
    EventFamily,
    FeatureConfig,
    RiskConfig,
    build_causal_features,
    generate_event_candidates,
)
from .metrics import AccountMetrics, select_pre2024_configuration, summarize_account
from .model import ChronologicalEventModel, ModelConfig, ScoredCandidate
from .policy import GlobalSlotPolicy


@dataclass(frozen=True)
class InstrumentRule:
    symbol: str
    quantity_step: float
    minimum_quantity: float


@dataclass(frozen=True)
class ResearchConfiguration:
    identifier: str
    symbols: tuple[str, ...]
    model: ModelConfig
    update_cadence_days: int
    training_completion_lag_minutes: int
    passive_fill_threshold: float
    risk: RiskConfig
    instrument_rules: tuple[InstrumentRule, ...]


@dataclass(frozen=True)
class ModelUpdateRecord:
    update_started_at: pd.Timestamp
    model_activated_at: pd.Timestamp
    training_rows: int
    latest_label_end: pd.Timestamp


@dataclass(frozen=True)
class ConfigurationResult:
    configuration: ResearchConfiguration
    metrics: AccountMetrics
    update_records: tuple[ModelUpdateRecord, ...]
    candidate_count: int
    scored_positive_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "configuration": _jsonable(asdict(self.configuration)),
            "metrics": self.metrics.as_dict(),
            "update_records": [_jsonable(asdict(row)) for row in self.update_records],
            "candidate_count": self.candidate_count,
            "scored_positive_count": self.scored_positive_count,
        }


@dataclass(frozen=True)
class Pre2024Decision:
    status: str
    selected: ConfigurationResult | None
    all_results: tuple[ConfigurationResult, ...]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "selected": self.selected.as_dict() if self.selected else None,
            "all_results": [row.as_dict() for row in self.all_results],
            "reason": self.reason,
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def configuration_sha256(configuration: ResearchConfiguration) -> str:
    return sha256(canonical_json(asdict(configuration)).encode("utf-8")).hexdigest()


def _event_identity(candidate: EventCandidate) -> tuple[Any, ...]:
    return (
        candidate.timestamp,
        candidate.symbol,
        candidate.family.value,
        candidate.side,
        candidate.entry_reference,
        candidate.stop_reference,
        candidate.target_reference,
    )


def encode_event_features(candidate: EventCandidate) -> dict[str, float]:
    row = {
        key: float(value)
        for key, value in candidate.feature_row.items()
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)
    }
    row.update(
        {
            "side": float(candidate.side),
            "stop_distance_fraction": candidate.stop_distance / max(candidate.entry_reference, 1e-12),
            "target_distance_fraction": candidate.target_distance / max(candidate.entry_reference, 1e-12),
            "raw_reward_risk": candidate.target_distance / max(candidate.stop_distance, 1e-12),
            "family_liquidity_sweep": float(candidate.family == EventFamily.LIQUIDITY_SWEEP_REVERSAL),
            "family_displacement_retest": float(candidate.family == EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION),
            "symbol_btc": float(candidate.symbol == "BTCUSDT"),
            "symbol_eth": float(candidate.symbol == "ETHUSDT"),
            "symbol_sol": float(candidate.symbol == "SOLUSDT"),
            "symbol_xrp": float(candidate.symbol == "XRPUSDT"),
        }
    )
    return row


def label_event_dataset(
    candidates: Sequence[EventCandidate],
    execution_bars_by_symbol: Mapping[str, pd.DataFrame],
    config: CoarseExecutionConfig = CoarseExecutionConfig(),
) -> pd.DataFrame:
    """Create fully timestamped labels without treating censoring as loss."""
    rows: list[dict[str, Any]] = []
    labelers = {symbol: CoarseLabeler(frame, config) for symbol, frame in execution_bars_by_symbol.items()}
    for candidate in sorted(candidates, key=_event_identity):
        labeler = labelers.get(candidate.symbol)
        if labeler is None:
            continue
        market = labeler.label(candidate, passive=False)
        passive = labeler.label(candidate, passive=True)
        if market.target_before_stop is None or market.net_r is None or market.event_end is None:
            continue
        passive_resolved = passive.status in {"TARGET", "STOP", "CANCELLED_BEFORE_FILL"}
        if not passive_resolved or passive.event_end is None:
            continue
        event_end = max(market.event_end, passive.event_end)
        row: dict[str, Any] = {
            "event_start": candidate.timestamp,
            "event_end": event_end,
            "target_before_stop": int(market.target_before_stop),
            "net_r": float(market.net_r),
            "passive_filled": int(passive.passive_filled),
            "market_status": market.status,
            "passive_status": passive.status,
            "symbol": candidate.symbol,
            "family": candidate.family.value,
        }
        row.update(encode_event_features(candidate))
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["event_end", "event_start", "symbol"], kind="stable").reset_index(drop=True)


def _purged_rows_asof(rows: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    if rows.empty:
        return rows.copy()
    eligible = rows[pd.to_datetime(rows["event_end"], utc=True) <= asof].copy()
    return eligible.sort_values(["event_end", "event_start"], kind="stable").reset_index(drop=True)


def _distribution(rows: pd.DataFrame) -> tuple[float, float]:
    wins = rows.loc[rows["target_before_stop"] == 1, "net_r"].astype(float)
    losses = rows.loc[rows["target_before_stop"] == 0, "net_r"].astype(float)
    winner = float(wins.median()) if not wins.empty else 1.0
    loser = float(losses.median()) if not losses.empty else -1.0
    if winner <= 0:
        winner = max(0.01, float(rows["net_r"].quantile(0.75)))
    if loser >= 0:
        loser = min(-0.01, float(rows["net_r"].quantile(0.25)))
    return winner, loser


def _aligned_updates(start: pd.Timestamp, end: pd.Timestamp, cadence_days: int) -> list[pd.Timestamp]:
    if cadence_days <= 0:
        raise ValueError("cadence_days must be positive")
    return list(pd.date_range(start.floor("D"), end, freq=pd.Timedelta(days=cadence_days), tz="UTC"))


def score_candidates_walk_forward(
    candidates: Sequence[EventCandidate],
    label_rows: pd.DataFrame,
    configuration: ResearchConfiguration,
    evaluation_start: pd.Timestamp,
    evaluation_end_exclusive: pd.Timestamp,
) -> tuple[list[ScoredCandidate], tuple[ModelUpdateRecord, ...]]:
    ordered = [
        candidate
        for candidate in sorted(candidates, key=lambda item: (item.timestamp, item.symbol, item.family.value, item.side))
        if evaluation_start <= candidate.timestamp < evaluation_end_exclusive
    ]
    if not ordered:
        return [], ()
    lag = pd.Timedelta(minutes=configuration.training_completion_lag_minutes)
    update_starts = _aligned_updates(evaluation_start, evaluation_end_exclusive, configuration.update_cadence_days)
    update_index = 0
    active_model: ChronologicalEventModel | None = None
    active_distribution = (1.0, -1.0)
    pending: tuple[pd.Timestamp, ChronologicalEventModel, tuple[float, float], int, pd.Timestamp] | None = None
    scored: list[ScoredCandidate] = []
    ledger: list[ModelUpdateRecord] = []

    def start_update(update_start: pd.Timestamp) -> tuple[pd.Timestamp, ChronologicalEventModel, tuple[float, float], int, pd.Timestamp] | None:
        training = _purged_rows_asof(label_rows, update_start)
        minimum = max(50, configuration.model.min_samples_leaf * 2)
        if len(training) < minimum:
            return None
        try:
            model = ChronologicalEventModel(configuration.model).fit(training)
        except ValueError:
            return None
        latest = pd.Timestamp(training["event_end"].max())
        return update_start + lag, model, _distribution(training), len(training), latest

    initial_started = evaluation_start - lag
    initial = start_update(initial_started)
    if initial is not None:
        activated_at, active_model, active_distribution, count, latest = initial
        ledger.append(ModelUpdateRecord(initial_started, activated_at, count, latest))

    for candidate in ordered:
        while update_index < len(update_starts) and update_starts[update_index] <= candidate.timestamp:
            candidate_update = start_update(update_starts[update_index])
            if candidate_update is not None:
                pending = candidate_update
            update_index += 1
        if pending is not None and pending[0] <= candidate.timestamp:
            activated_at, active_model, active_distribution, count, latest = pending
            ledger.append(
                ModelUpdateRecord(
                    update_started_at=activated_at - lag,
                    model_activated_at=activated_at,
                    training_rows=count,
                    latest_label_end=latest,
                )
            )
            pending = None
        if active_model is None:
            continue
        winner, loser = active_distribution
        scored.append(
            active_model.score(
                candidate,
                risk_fraction=configuration.risk.risk_fraction,
                winner_net_r=winner,
                loser_net_r=loser,
                fixed_cost_fraction=0.0,
            )
        )
    return scored, tuple(ledger)


def generate_candidates_by_symbol(
    decision_frames: Mapping[str, pd.DataFrame],
    feature_config: FeatureConfig = FeatureConfig(),
) -> tuple[dict[str, pd.DataFrame], list[EventCandidate]]:
    features: dict[str, pd.DataFrame] = {}
    candidates: list[EventCandidate] = []
    for symbol, frame in sorted(decision_frames.items()):
        calculated = build_causal_features(frame, feature_config)
        features[symbol] = calculated
        candidates.extend(generate_event_candidates(calculated, symbol, feature_config))
    candidates.sort(key=lambda item: (item.timestamp, item.symbol, item.family.value, item.side))
    return features, candidates


def evaluate_configuration(
    configuration: ResearchConfiguration,
    candidates: Sequence[EventCandidate],
    label_rows: pd.DataFrame,
    execution_bars_by_symbol: Mapping[str, pd.DataFrame],
    evaluation_start: pd.Timestamp,
    evaluation_end_exclusive: pd.Timestamp,
    initial_nav: float = 10000.0,
    execution_config: CoarseExecutionConfig = CoarseExecutionConfig(),
    funding: Mapping[tuple[str, pd.Timestamp], float] | None = None,
) -> ConfigurationResult:
    selected_symbols = set(configuration.symbols)
    selected_candidates = [candidate for candidate in candidates if candidate.symbol in selected_symbols]
    selected_labels = label_rows[label_rows["symbol"].isin(selected_symbols)].copy() if not label_rows.empty else label_rows.copy()
    selected_bars = {symbol: frame for symbol, frame in execution_bars_by_symbol.items() if symbol in selected_symbols}
    scored, updates = score_candidates_walk_forward(
        selected_candidates,
        selected_labels,
        configuration,
        evaluation_start,
        evaluation_end_exclusive,
    )
    policy = GlobalSlotPolicy(configuration.passive_fill_threshold)
    instrument_rules = {rule.symbol: (rule.quantity_step, rule.minimum_quantity) for rule in configuration.instrument_rules}
    account = CoarseEventReplay(selected_bars, execution_config).run(
        scored,
        policy,
        configuration.risk,
        evaluation_start,
        evaluation_end_exclusive,
        initial_nav=initial_nav,
        funding=funding,
        instrument_rules=instrument_rules,
    )
    last_candidates = [
        frame.loc[frame["bar_start"] < evaluation_end_exclusive]
        for frame in selected_bars.values()
        if not frame.empty and "bar_start" in frame.columns
    ]
    final_prices = [float(frame.iloc[-1].get("mark_close", frame.iloc[-1]["close"])) for frame in last_candidates if not frame.empty]
    final_mark = final_prices[-1] if final_prices else 0.0
    if account.position is not None:
        symbol_frame = selected_bars[account.position.candidate.symbol]
        eligible = symbol_frame.loc[symbol_frame["bar_start"] < evaluation_end_exclusive]
        if not eligible.empty:
            final_mark = float(eligible.iloc[-1].get("mark_close", eligible.iloc[-1]["close"]))
    metrics = summarize_account(account, evaluation_start, evaluation_end_exclusive, final_mark)
    return ConfigurationResult(
        configuration=configuration,
        metrics=metrics,
        update_records=updates,
        candidate_count=sum(evaluation_start <= row.timestamp < evaluation_end_exclusive for row in selected_candidates),
        scored_positive_count=sum(row.lower_confidence_score > 0 for row in scored),
    )


def select_pre2024(
    configurations: Sequence[ResearchConfiguration],
    candidates: Sequence[EventCandidate],
    label_rows: pd.DataFrame,
    execution_bars_by_symbol: Mapping[str, pd.DataFrame],
    evaluation_start: pd.Timestamp,
    evaluation_end_exclusive: pd.Timestamp,
    execution_config: CoarseExecutionConfig = CoarseExecutionConfig(),
    funding: Mapping[tuple[str, pd.Timestamp], float] | None = None,
) -> Pre2024Decision:
    results = tuple(
        evaluate_configuration(
            configuration,
            candidates,
            label_rows,
            execution_bars_by_symbol,
            evaluation_start,
            evaluation_end_exclusive,
            execution_config=execution_config,
            funding=funding,
        )
        for configuration in configurations
    )
    if not results:
        return Pre2024Decision("NO_CONFIGURATIONS", None, (), "no frozen configuration supplied")
    identifier, metrics = select_pre2024_configuration((row.configuration.identifier, row.metrics) for row in results)
    selected = next(row for row in results if row.configuration.identifier == identifier)
    if metrics.geometric_daily_growth <= 0:
        return Pre2024Decision(
            "ECONOMIC_FAIL_NO_OFFICIAL_OPEN",
            selected,
            results,
            "best basic-risk pre-2024 sequential account has nonpositive after-cost geometric growth",
        )
    return Pre2024Decision(
        "POSITIVE_BASIC_ALPHA_OPEN_RISK_SEARCH",
        selected,
        results,
        "positive after-cost pre-2024 sequential account; risk/leverage/order-style refinement may proceed before freezing",
    )


def write_decision(output: Path, decision: Pre2024Decision) -> None:
    output.mkdir(parents=True, exist_ok=True)
    payload = decision.as_dict()
    path = output / "PRE2024_DECISION.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "PRE2024_DECISION.sha256").write_text(f"{sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8")
