from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from data import BAR_MS, FEATURE_COLUMNS, build_feature_frame, load_market_data, split_contiguous, stage_frame
from hmm import DiagonalGaussianHMM
from strategy import Thresholds, generate_events, largest_positive_event_ids, route_and_replay


SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
TRAIN_START = "2021-01-01T00:00:00Z"
TRAIN_END = "2021-12-31T23:59:59Z"
FIT_START = "2022-01-01T00:00:00Z"
FIT_END = "2022-12-31T23:59:59Z"
DEVELOPMENT_START = "2023-01-01T00:00:00Z"
DEVELOPMENT_END = "2023-12-31T23:59:59Z"
RESULT_ID = "RES-20260726-ML-PO3-STATE-001"
CLAIM_ID = "CLM-20260726-1712-ML-PO3-STATE-001"
COSTS = [12, 18, 24]


def timestamp_ms(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1000)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def standardization(train_frames: dict[str, pd.DataFrame]) -> tuple[np.ndarray, np.ndarray]:
    matrix = np.concatenate(
        [frame[FEATURE_COLUMNS].to_numpy(dtype=np.float64) for frame in train_frames.values() if not frame.empty],
        axis=0,
    )
    mean = np.mean(matrix, axis=0)
    scale = np.std(matrix, axis=0, ddof=0)
    scale = np.where(scale > 1e-8, scale, 1.0)
    return mean, scale


def standardized_sequences(
    frames: dict[str, pd.DataFrame], mean: np.ndarray, scale: np.ndarray
) -> list[np.ndarray]:
    sequences: list[np.ndarray] = []
    for symbol in sorted(frames):
        for segment in split_contiguous(frames[symbol]):
            x = segment[FEATURE_COLUMNS].to_numpy(dtype=np.float64)
            sequences.append((x - mean[None, :]) / scale[None, :])
    return sequences


def attach_filtered_probabilities(
    frames: dict[str, pd.DataFrame],
    model: DiagonalGaussianHMM,
    mean: np.ndarray,
    scale: np.ndarray,
) -> dict[str, pd.DataFrame]:
    output: dict[str, pd.DataFrame] = {}
    for symbol, frame in frames.items():
        ordered = frame.sort_values("open_time").reset_index(drop=True).copy()
        ordered[["p_state_0", "p_state_1", "p_state_2"]] = np.nan
        for segment in split_contiguous(ordered):
            indexes = segment.index.to_numpy(dtype=np.int64)
            # split_contiguous resets indexes, so recover by timestamps.
            start_time = int(segment.iloc[0]["open_time"])
            end_time = int(segment.iloc[-1]["open_time"])
            mask = (ordered["open_time"] >= start_time) & (ordered["open_time"] <= end_time)
            positions = np.flatnonzero(mask.to_numpy())
            x = ordered.loc[mask, FEATURE_COLUMNS].to_numpy(dtype=np.float64)
            probabilities = model.filter((x - mean[None, :]) / scale[None, :])
            ordered.loc[positions, ["p_state_0", "p_state_1", "p_state_2"]] = probabilities
        if ordered[["p_state_0", "p_state_1", "p_state_2"]].isna().any().any():
            raise RuntimeError(f"unassigned filtered probability in {symbol}")
        sums = ordered[["p_state_0", "p_state_1", "p_state_2"]].sum(axis=1).to_numpy()
        if not np.allclose(sums, 1.0, atol=1e-10, rtol=0.0):
            raise RuntimeError(f"filtered probabilities do not sum to one for {symbol}")
        output[symbol] = ordered
    return output


def probability_thresholds(
    filtered_train: dict[str, pd.DataFrame], mapping: dict[str, int]
) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for semantic in ("accumulation", "manipulation", "distribution"):
        state = int(mapping[semantic])
        values = np.concatenate(
            [frame[f"p_state_{state}"].to_numpy(dtype=np.float64) for frame in filtered_train.values()]
        )
        thresholds[semantic] = float(max(0.50, np.quantile(values, 0.70)))
    return thresholds


def stage_evaluation(
    stage_name: str,
    filtered_frames: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    thresholds: Thresholds,
    start_ms: int,
    end_ms: int,
    output: Path,
) -> dict[str, object]:
    events = generate_events(filtered_frames, thresholds)
    event_frame = pd.DataFrame(events)
    event_path = output / f"{stage_name}_events.csv.gz"
    event_frame.to_csv(event_path, index=False, compression="gzip")

    paths: dict[str, object] = {}
    base_trades: dict[int, list[dict[str, object]]] = {}
    for cost in COSTS:
        trades, metrics = route_and_replay(
            events,
            filtered_frames,
            funding,
            start_ms,
            end_ms,
            float(cost),
        )
        base_trades[cost] = trades
        pd.DataFrame(trades).to_csv(output / f"{stage_name}_{cost}bp_trades.csv", index=False)
        paths[str(cost)] = {"metrics": metrics}

    removed_ids = largest_positive_event_ids(base_trades[12], fraction=0.10)
    for cost in COSTS:
        removed_trades, removed_metrics = route_and_replay(
            events,
            filtered_frames,
            funding,
            start_ms,
            end_ms,
            float(cost),
            excluded_event_ids=removed_ids,
        )
        pd.DataFrame(removed_trades).to_csv(
            output / f"{stage_name}_{cost}bp_top10_removed_trades.csv", index=False
        )
        paths[str(cost)]["top10_removed_metrics"] = removed_metrics

    return {
        "stage": stage_name,
        "event_count": int(len(events)),
        "removed_event_ids": sorted(removed_ids),
        "removed_event_count": int(len(removed_ids)),
        "paths": paths,
    }


def fit_gate(evaluation: dict[str, object]) -> tuple[bool, dict[str, bool]]:
    paths = evaluation["paths"]
    m18 = paths["18"]["metrics"]
    m24 = paths["24"]["metrics"]
    removed18 = paths["18"]["top10_removed_metrics"]
    profit_factor = m24["profit_factor"]
    if profit_factor is None and float(m24["total_return"]) > 0.0:
        profit_factor_value = math.inf
    else:
        profit_factor_value = float(profit_factor or 0.0)
    mean24 = m24["mean_net_bps"]
    median24 = m24["median_net_bps"]
    conditions = {
        "minimum_trades_24bp": int(m24["trades"]) >= 80,
        "positive_mean_24bp": mean24 is not None and float(mean24) > 0.0,
        "positive_median_24bp": median24 is not None and float(median24) > 0.0,
        "profit_factor_24bp_above_one": profit_factor_value > 1.0,
        "positive_total_return_24bp": float(m24["total_return"]) > 0.0,
        "positive_18bp_first_half": float(m18["half_returns"][0]) > 0.0,
        "positive_18bp_second_half": float(m18["half_returns"][1]) > 0.0,
        "minimum_positive_18bp_quarters": int(m18["positive_quarters"]) >= 3,
        "positive_18bp_top10_removed_return": float(removed18["total_return"]) > 0.0,
        "minimum_18bp_geometric_daily_growth": float(m18["geometric_daily_growth"]) >= 0.001,
        "maximum_18bp_drawdown": float(m18["maximum_drawdown"]) <= 0.25,
        "maximum_unresolved_fraction": float(m18["unresolved_fraction"]) <= 0.10,
    }
    return all(conditions.values()), conditions


def model_payload(
    model: DiagonalGaussianHMM,
    mean: np.ndarray,
    scale: np.ndarray,
    mapping: dict[str, int],
    threshold_values: dict[str, float],
    log_likelihoods: list[float],
) -> dict[str, object]:
    return {
        "model": model.to_dict(),
        "feature_columns": FEATURE_COLUMNS,
        "feature_mean_2021": mean.tolist(),
        "feature_scale_2021": scale.tolist(),
        "semantic_mapping": mapping,
        "probability_thresholds": threshold_values,
        "training_log_likelihoods": [float(value) for value in log_likelihoods],
        "causal_inference": "scaled forward filter only",
    }


def run(cache: Path, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    train_start = timestamp_ms(TRAIN_START)
    train_end = timestamp_ms(TRAIN_END)
    fit_start = timestamp_ms(FIT_START)
    fit_end = timestamp_ms(FIT_END)
    development_start = timestamp_ms(DEVELOPMENT_START)
    development_end = timestamp_ms(DEVELOPMENT_END)

    bars, funding, initial_manifest = load_market_data(
        SYMBOLS,
        bar_years=[2021, 2022],
        funding_years=[2022],
        cache_root=cache,
    )
    feature_frames = {symbol: build_feature_frame(frame) for symbol, frame in bars.items()}
    train_frames = {
        symbol: stage_frame(frame, train_start, train_end) for symbol, frame in feature_frames.items()
    }
    fit_frames = {
        symbol: stage_frame(frame, fit_start, fit_end) for symbol, frame in feature_frames.items()
    }
    if any(frame.empty for frame in train_frames.values()) or any(frame.empty for frame in fit_frames.values()):
        raise RuntimeError("missing required train or fit frame")

    mean, scale = standardization(train_frames)
    train_sequences = standardized_sequences(train_frames, mean, scale)
    model = DiagonalGaussianHMM(
        n_states=3,
        n_iter=12,
        covariance_floor=0.05,
        diagonal_prior=5.0,
        random_seed=20260726,
    )
    fit_result = model.fit(train_sequences)
    mapping = model.semantic_mapping()
    filtered_train = attach_filtered_probabilities(train_frames, model, mean, scale)
    threshold_values = probability_thresholds(filtered_train, mapping)
    thresholds = Thresholds(
        accumulation=threshold_values["accumulation"],
        manipulation=threshold_values["manipulation"],
        distribution=threshold_values["distribution"],
        accumulation_state=int(mapping["accumulation"]),
        manipulation_state=int(mapping["manipulation"]),
        distribution_state=int(mapping["distribution"]),
        accumulation_run_bars=6,
        minimum_reward_risk=1.5,
    )
    write_json(
        output / "model.json",
        model_payload(model, mean, scale, mapping, threshold_values, fit_result.log_likelihoods),
    )

    filtered_fit = attach_filtered_probabilities(fit_frames, model, mean, scale)
    fit_evaluation = stage_evaluation(
        "fit_2022",
        filtered_fit,
        funding,
        thresholds,
        fit_start,
        fit_end,
        output,
    )
    fit_pass, fit_conditions = fit_gate(fit_evaluation)
    development_evaluation: dict[str, object] | None = None
    development_opened = False
    combined_manifest = dict(initial_manifest)

    if fit_pass:
        development_opened = True
        development_bars, development_funding, development_manifest = load_market_data(
            SYMBOLS,
            bar_years=[2023],
            funding_years=[2023],
            cache_root=cache,
        )
        combined_records = list(initial_manifest["records"]) + list(development_manifest["records"])
        combined_manifest = {
            **initial_manifest,
            "records": combined_records,
            "record_count": len(combined_records),
            "bar_years": [2021, 2022, 2023],
            "funding_years": [2022, 2023],
            "total_compressed_bytes": int(
                sum(int(record["compressed_bytes"]) for record in combined_records)
            ),
        }
        development_feature_frames: dict[str, pd.DataFrame] = {}
        for symbol in SYMBOLS:
            history = pd.concat([bars[symbol].loc[bars[symbol]["open_time"] >= fit_start], development_bars[symbol]], ignore_index=True)
            feature = build_feature_frame(history)
            development_feature_frames[symbol] = stage_frame(
                feature, development_start, development_end
            )
        filtered_development = attach_filtered_probabilities(
            development_feature_frames, model, mean, scale
        )
        development_evaluation = stage_evaluation(
            "development_2023",
            filtered_development,
            development_funding,
            thresholds,
            development_start,
            development_end,
            output,
        )

    combined_manifest.update(
        {
            "claim_id": CLAIM_ID,
            "result_id": RESULT_ID,
            "train_period": [TRAIN_START, TRAIN_END],
            "fit_period": [FIT_START, FIT_END],
            "development_period": [DEVELOPMENT_START, DEVELOPMENT_END],
            "development_opened": development_opened,
            "2024_opened": False,
            "2025_opened": False,
            "2026_opened": False,
            "orders_submitted": False,
        }
    )
    write_json(output / "source_manifest.json", combined_manifest)

    status = "CANDIDATE_PROXY_SURVIVOR" if fit_pass else "TESTED_BELOW_GATE"
    result = {
        "schema_version": 1,
        "result_id": RESULT_ID,
        "claim_id": CLAIM_ID,
        "status": status,
        "hard_validity_status": "PASS_PROXY_FATAL_SCREEN",
        "economic_status": "FIT_GATE_PASS" if fit_pass else "BELOW_GATE",
        "ranking_role": "NOT_RANK_ELIGIBLE_PROXY",
        "model_count": 1,
        "candidate_count": 1,
        "state_count": 3,
        "feature_count": 5,
        "entry_path_count": 1,
        "semantic_mapping": mapping,
        "probability_thresholds": threshold_values,
        "fit_2022": fit_evaluation,
        "fit_gate_pass": fit_pass,
        "fit_gate_conditions": fit_conditions,
        "development_2023": development_evaluation,
        "2023_opened": development_opened,
        "2024_opened": False,
        "2025_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_or_live_started": False,
        "current_first_place_changed": False,
        "interpretation": (
            "One latent PO3 state model and one structural raid-reclaim path only. "
            "A fit pass permits unchanged 2023 evaluation but never ranking; exact Bybit "
            "BBO/depth replay remains mandatory."
        ),
    }
    write_json(output / "result_summary.json", result)

    # One candidate row keeps the registry surface explicit without pretending
    # that model-state labels are a broad parameter search.
    candidate_row: dict[str, object] = {
        "candidate_id": "single_frozen_ml_po3_policy",
        "fit_gate": fit_pass,
        **{f"gate_{key}": value for key, value in fit_conditions.items()},
    }
    for cost in COSTS:
        metrics = fit_evaluation["paths"][str(cost)]["metrics"]
        removed = fit_evaluation["paths"][str(cost)]["top10_removed_metrics"]
        for key, value in metrics.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                candidate_row[f"fit_{cost}bp_{key}"] = value
        candidate_row[f"fit_{cost}bp_top10_removed_total_return"] = removed["total_return"]
        candidate_row[f"fit_{cost}bp_top10_removed_growth"] = removed["geometric_daily_growth"]
    pd.DataFrame([candidate_row]).to_csv(output / "candidate_results.csv", index=False)

    validation = {
        "schema_version": 1,
        "attestation_id": "VAL-20260726-ML-PO3-STATE-001",
        "status": "PASS",
        "candidate_count": 1,
        "model_count": 1,
        "feature_count": 5,
        "state_count": 3,
        "entry_path_count": 1,
        "causal_filter": True,
        "cost_monotonicity": all(
            float(fit_evaluation["paths"][str(left)]["metrics"]["final_nav"])
            + 1e-9
            >= float(fit_evaluation["paths"][str(right)]["metrics"]["final_nav"])
            for left, right in ((12, 18), (18, 24))
        ),
        "development_opened_iff_fit_gate": development_opened == fit_pass,
        "2024_opened": False,
        "2025_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
    }
    if not validation["cost_monotonicity"] or not validation["development_opened_iff_fit_gate"]:
        raise RuntimeError(f"validation invariant failed: {validation}")
    write_json(output / "VALIDATION_ATTESTATION.json", validation)

    dependencies = {
        "implementation_files": ["run.py", "data.py", "strategy.py", "hmm.py"],
        "evaluation_contract": "preregistration.json",
        "source_manifest_sha256": file_sha256(output / "source_manifest.json"),
        "model_sha256": file_sha256(output / "model.json"),
        "candidate_results_sha256": file_sha256(output / "candidate_results.csv"),
        "result_summary_sha256": file_sha256(output / "result_summary.json"),
        "orders_submitted": False,
    }
    write_json(output / "dependency_manifest.json", dependencies)
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


def synthetic_bars(count: int = 420) -> pd.DataFrame:
    rng = np.random.default_rng(20260726)
    times = np.arange(count, dtype=np.int64) * BAR_MS + timestamp_ms("2020-01-01T00:00:00Z")
    returns = rng.normal(0.0, 0.001, size=count)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_price = np.r_[close[0], close[:-1]]
    spread = np.maximum(0.02, np.abs(rng.normal(0.08, 0.02, size=count)))
    high = np.maximum(open_price, close) + spread
    low = np.minimum(open_price, close) - spread
    quote = rng.uniform(1_000_000.0, 2_000_000.0, size=count)
    taker = quote * rng.uniform(0.35, 0.65, size=count)
    return pd.DataFrame(
        {
            "open_time": times,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "quote_volume": quote,
            "trade_count": 100,
            "taker_buy_quote": taker,
        }
    )


def self_test() -> int:
    # Feature construction is prefix invariant when future bars change.
    base = synthetic_bars()
    first = build_feature_frame(base)
    mutated = base.copy()
    mutated.loc[350:, ["open", "high", "low", "close"]] *= 1.5
    second = build_feature_frame(mutated)
    cutoff = int(base.iloc[300]["open_time"])
    left = first.loc[first["open_time"] <= cutoff, FEATURE_COLUMNS].to_numpy()
    right = second.loc[second["open_time"] <= cutoff, FEATURE_COLUMNS].to_numpy()
    assert left.shape == right.shape and np.allclose(left, right, atol=0.0, rtol=0.0)

    # Forward state probability is prefix invariant; no backward smoothing is
    # available to the strategy.
    rng = np.random.default_rng(7)
    sequences = [rng.normal(size=(240, 5)), rng.normal(loc=0.3, size=(220, 5))]
    model = DiagonalGaussianHMM(n_states=3, n_iter=3)
    model.fit(sequences)
    full = model.filter(sequences[0])
    prefix = model.filter(sequences[0][:120])
    assert np.allclose(full[:120], prefix, atol=1e-12, rtol=0.0)

    # One synthetic causal PO3 event: six accumulation bars, an upper raid and
    # reclaim, then a learned bearish distribution confirmation.
    rows = []
    start = timestamp_ms("2022-01-01T00:00:00Z")
    for index in range(10):
        row = {
            "open_time": start + index * BAR_MS,
            "bar_end": start + (index + 1) * BAR_MS,
            "open": 95.0,
            "high": 100.0,
            "low": 90.0,
            "close": 95.0,
            "quote_volume": 10_000_000.0,
            "body_efficiency": 0.0,
            "flow_imbalance": 0.0,
            "p_state_0": 0.8 if index < 6 else 0.1,
            "p_state_1": 0.1,
            "p_state_2": 0.1,
        }
        rows.append(row)
    rows[6].update({"open": 99.5, "high": 101.0, "low": 98.0, "close": 99.2, "p_state_0": 0.1, "p_state_1": 0.8, "p_state_2": 0.1})
    rows[7].update({"open": 99.0, "high": 99.2, "low": 96.0, "close": 96.5, "body_efficiency": -0.7, "flow_imbalance": -0.6, "p_state_0": 0.1, "p_state_1": 0.1, "p_state_2": 0.8})
    rows[8].update({"open": 96.4, "high": 97.0, "low": 89.0, "close": 90.0})
    synthetic = pd.DataFrame(rows)
    thresholds = Thresholds(0.6, 0.6, 0.6, 0, 1, 2, 6, 1.5)
    events = generate_events({"BTCUSDT": synthetic}, thresholds)
    assert len(events) == 1
    assert int(events[0]["entry_time"]) >= int(events[0]["decision_time"])
    trades, metrics = route_and_replay(
        events,
        {"BTCUSDT": synthetic},
        {"BTCUSDT": pd.DataFrame(columns=["funding_time", "funding_rate"])},
        start,
        start + 10 * BAR_MS - 1,
        12.0,
    )
    assert len(trades) == 1 and trades[0]["exit_reason"] == "target"
    assert int(metrics["trades"]) == 1
    print("SELF_TEST_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "self-test":
        return self_test()
    if arguments.command == "run":
        return run(arguments.cache, arguments.output)
    raise RuntimeError("unreachable")


if __name__ == "__main__":
    sys.exit(main())
