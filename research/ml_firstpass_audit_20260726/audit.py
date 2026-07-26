from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Mapping, Sequence


class FirstPassageLabel(StrEnum):
    UPPER_FIRST = "UPPER_FIRST"
    LOWER_FIRST = "LOWER_FIRST"
    CENSORED = "CENSORED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class FirstPassageOutcome:
    label: FirstPassageLabel
    offset: int | None


@dataclass(frozen=True)
class EconomicDecision:
    action: str
    expected_value_bps: float
    long_ev_bps: float
    short_ev_bps: float


def first_passage_label(
    highs: Sequence[float],
    lows: Sequence[float],
    upper_pool: float,
    lower_pool: float,
) -> FirstPassageOutcome:
    """Label the first completed bar that touches either frozen pool.

    A bar touching both pools is explicitly AMBIGUOUS. It must not be assigned
    the favorable direction in model fitting. In account replay, ambiguity is
    resolved adversely by the strategy engine.
    """
    if not highs or len(highs) != len(lows):
        raise ValueError("highs and lows must be non-empty and equally sized")
    if not (math.isfinite(upper_pool) and math.isfinite(lower_pool)):
        raise ValueError("pool prices must be finite")
    if upper_pool <= lower_pool:
        raise ValueError("upper_pool must exceed lower_pool")

    for offset, (high, low) in enumerate(zip(highs, lows, strict=True)):
        if not (math.isfinite(high) and math.isfinite(low)):
            raise ValueError("path contains non-finite price")
        hit_upper = high >= upper_pool
        hit_lower = low <= lower_pool
        if hit_upper and hit_lower:
            return FirstPassageOutcome(FirstPassageLabel.AMBIGUOUS, offset)
        if hit_upper:
            return FirstPassageOutcome(FirstPassageLabel.UPPER_FIRST, offset)
        if hit_lower:
            return FirstPassageOutcome(FirstPassageLabel.LOWER_FIRST, offset)
    return FirstPassageOutcome(FirstPassageLabel.CENSORED, None)


def choose_cost_adjusted_action(
    *,
    p_upper_first: float,
    p_lower_first: float,
    upper_distance_bps: float,
    lower_distance_bps: float,
    roundtrip_cost_bps: float,
    minimum_edge_bps: float = 0.0,
) -> EconomicDecision:
    """Choose exactly one of LONG, SHORT or FLAT from frozen pool geometry."""
    values = (
        p_upper_first,
        p_lower_first,
        upper_distance_bps,
        lower_distance_bps,
        roundtrip_cost_bps,
        minimum_edge_bps,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("decision inputs must be finite")
    if p_upper_first < 0.0 or p_lower_first < 0.0:
        raise ValueError("probabilities must be non-negative")
    if not math.isclose(p_upper_first + p_lower_first, 1.0, abs_tol=1e-9):
        raise ValueError("first-passage probabilities must sum to one")
    if upper_distance_bps <= 0.0 or lower_distance_bps <= 0.0:
        raise ValueError("both structural distances must be positive")
    if roundtrip_cost_bps < 0.0 or minimum_edge_bps < 0.0:
        raise ValueError("cost and minimum edge must be non-negative")

    raw_directional_ev = (
        p_upper_first * upper_distance_bps
        - p_lower_first * lower_distance_bps
    )
    long_ev = raw_directional_ev - roundtrip_cost_bps
    short_ev = -raw_directional_ev - roundtrip_cost_bps
    threshold = minimum_edge_bps

    if long_ev > max(short_ev, threshold):
        return EconomicDecision("LONG", long_ev, long_ev, short_ev)
    if short_ev > max(long_ev, threshold):
        return EconomicDecision("SHORT", short_ev, long_ev, short_ev)
    return EconomicDecision("FLAT", max(long_ev, short_ev), long_ev, short_ev)


def weighted_brier(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    weights: Sequence[float],
) -> float:
    """Censoring-aware Brier component using externally frozen IPCW weights."""
    if not (len(probabilities) == len(outcomes) == len(weights)) or not probabilities:
        raise ValueError("probabilities, outcomes and weights must be equal non-zero length")
    numerator = 0.0
    denominator = 0.0
    for probability, outcome, weight in zip(
        probabilities, outcomes, weights, strict=True
    ):
        if not (0.0 <= probability <= 1.0):
            raise ValueError("probability outside [0, 1]")
        if outcome not in (0, 1):
            raise ValueError("outcomes must be binary")
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError("weights must be finite and non-negative")
        numerator += weight * (probability - outcome) ** 2
        denominator += weight
    if denominator <= 0.0:
        raise ValueError("positive total weight required")
    return numerator / denominator


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp lacks timezone: {value}")
    return parsed.astimezone(timezone.utc)


def validate_chronology(partitions: Mapping[str, Mapping[str, str]]) -> None:
    required = ("train", "calibration", "confirmation", "development")
    missing = [name for name in required if name not in partitions]
    if missing:
        raise ValueError(f"missing chronological partitions: {missing}")

    previous_end: datetime | None = None
    for name in required:
        start = parse_utc(partitions[name]["start"])
        end = parse_utc(partitions[name]["end"])
        if end < start:
            raise ValueError(f"{name} end precedes start")
        if previous_end is not None and start <= previous_end:
            raise ValueError(f"{name} overlaps or touches prior partition")
        previous_end = end
    assert previous_end is not None
    if previous_end >= datetime(2024, 1, 1, tzinfo=timezone.utc):
        raise ValueError("audit contract prohibits 2024 or later data")


def validate_manifest(manifest: Mapping[str, object]) -> None:
    if manifest.get("claim_id") != "CLM-20260726-1703-ML-LIQUIDITY-DRAW-001":
        raise ValueError("unexpected target claim_id")
    if manifest.get("model_family_count") != 1:
        raise ValueError("exactly one model family is allowed")
    if manifest.get("hyperparameter_candidate_count") != 1:
        raise ValueError("hyperparameter search is not allowed in the core screen")
    if manifest.get("economic_decision_rule_count") != 1:
        raise ValueError("exactly one cost-adjusted EV decision rule is allowed")
    if manifest.get("one_global_slot") is not True:
        raise ValueError("one_global_slot must be true")
    if manifest.get("2024_opened") is not False:
        raise ValueError("2024 must remain sealed")
    if manifest.get("orders_submitted") is not False:
        raise ValueError("orders_submitted must be false")
    partitions = manifest.get("partitions")
    if not isinstance(partitions, Mapping):
        raise ValueError("manifest.partitions must be an object")
    validate_chronology(partitions)  # type: ignore[arg-type]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def validate_prediction_rows(rows: Iterable[Mapping[str, str]]) -> int:
    count = 0
    for row in rows:
        count += 1
        p_upper = float(row["p_upper_first"])
        p_lower = float(row["p_lower_first"])
        if not math.isclose(p_upper + p_lower, 1.0, abs_tol=1e-8):
            raise ValueError(f"probabilities do not sum to one at row {count}")
        expected = choose_cost_adjusted_action(
            p_upper_first=p_upper,
            p_lower_first=p_lower,
            upper_distance_bps=float(row["upper_distance_bps"]),
            lower_distance_bps=float(row["lower_distance_bps"]),
            roundtrip_cost_bps=float(row["roundtrip_cost_bps"]),
            minimum_edge_bps=float(row.get("minimum_edge_bps", "0") or 0.0),
        )
        if row["action"] != expected.action:
            raise ValueError(f"action mismatch at row {count}")
        if not math.isclose(
            float(row["expected_value_bps"]),
            expected.expected_value_bps,
            abs_tol=1e-8,
        ):
            raise ValueError(f"EV mismatch at row {count}")
    if count == 0:
        raise ValueError("prediction ledger is empty")
    return count


def validate_nonoverlapping_ledger(rows: Iterable[Mapping[str, str]]) -> int:
    accepted = [row for row in rows if row.get("action") in {"LONG", "SHORT"}]
    accepted.sort(key=lambda row: (parse_utc(row["entry_ts"]), row["symbol"]))
    prior_exit: datetime | None = None
    for row in accepted:
        entry = parse_utc(row["entry_ts"])
        exit_time = parse_utc(row["exit_ts"])
        if exit_time < entry:
            raise ValueError("exit precedes entry")
        if prior_exit is not None and entry < prior_exit:
            raise ValueError("global position overlap detected")
        prior_exit = exit_time
    return len(accepted)


def validate_cost_monotonicity(rows: Iterable[Mapping[str, str]]) -> None:
    grouped: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        grouped.setdefault(row["path_id"], []).append(
            (float(row["roundtrip_cost_bps"]), float(row["net_return_bps"]))
        )
    if not grouped:
        raise ValueError("cost ledger is empty")
    for path_id, values in grouped.items():
        ordered = sorted(values)
        for (_, prior_return), (_, current_return) in zip(
            ordered, ordered[1:], strict=False
        ):
            if current_return > prior_return + 1e-9:
                raise ValueError(f"cost monotonicity failed for {path_id}")


def run_self_test() -> None:
    assert first_passage_label([101.0], [99.5], 101.0, 99.0).label == FirstPassageLabel.UPPER_FIRST
    assert first_passage_label([100.5], [99.0], 101.0, 99.0).label == FirstPassageLabel.LOWER_FIRST
    assert first_passage_label([101.0], [99.0], 101.0, 99.0).label == FirstPassageLabel.AMBIGUOUS
    assert first_passage_label([100.5], [99.5], 101.0, 99.0).label == FirstPassageLabel.CENSORED

    long_decision = choose_cost_adjusted_action(
        p_upper_first=0.8,
        p_lower_first=0.2,
        upper_distance_bps=80.0,
        lower_distance_bps=30.0,
        roundtrip_cost_bps=12.0,
    )
    assert long_decision.action == "LONG"
    short_decision = choose_cost_adjusted_action(
        p_upper_first=0.2,
        p_lower_first=0.8,
        upper_distance_bps=30.0,
        lower_distance_bps=80.0,
        roundtrip_cost_bps=12.0,
    )
    assert short_decision.action == "SHORT"
    flat_decision = choose_cost_adjusted_action(
        p_upper_first=0.5,
        p_lower_first=0.5,
        upper_distance_bps=20.0,
        lower_distance_bps=20.0,
        roundtrip_cost_bps=12.0,
    )
    assert flat_decision.action == "FLAT"
    assert math.isclose(weighted_brier([0.8, 0.2], [1, 0], [1.0, 1.0]), 0.04)

    validate_chronology(
        {
            "train": {"start": "2022-01-01T00:00:00Z", "end": "2022-06-30T23:59:59Z"},
            "calibration": {"start": "2022-07-01T00:00:00Z", "end": "2022-09-30T23:59:59Z"},
            "confirmation": {"start": "2022-10-01T00:00:00Z", "end": "2022-12-31T23:59:59Z"},
            "development": {"start": "2023-01-01T00:00:00Z", "end": "2023-12-31T23:59:59Z"},
        }
    )
    print("ML_FIRSTPASS_AUDIT_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--predictions", type=Path, required=True)
    validate.add_argument("--ledger", type=Path, required=True)
    validate.add_argument("--cost-ledger", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "self-test":
        run_self_test()
        return 0

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    prediction_count = validate_prediction_rows(read_csv(args.predictions))
    accepted_count = validate_nonoverlapping_ledger(read_csv(args.ledger))
    validate_cost_monotonicity(read_csv(args.cost_ledger))
    print(
        json.dumps(
            {
                "status": "PASS",
                "prediction_rows": prediction_count,
                "accepted_trades": accepted_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
