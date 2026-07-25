from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ARTIFACT_ID = 8621485991
EXPECTED_ARTIFACT_SHA256 = "ebd885b469c0391a5d164c8a6e540f5958ac34b39ee03a1e5a54748a7e6a1b46"
EXPECTED_DECISION_SHA256 = "148501fad341a5bcca2eb4252b7749eb3a25b36fbddc3d0d555b1f276e5c885f"
EXPECTED_SOURCE_SHA256 = "99c459ef6e45fbd5e5482807ce8785c248326034ed8d34fc50ff7956f1808064"
CORRECTION_ID = "CORR-20260726-L2-MAKER-CAUSAL-001"
SOURCE_RESULT_SCOPE = "CLM-20260725-1958-L2-MAKER-001"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError(f"unsafe archive member: {member.filename}")
        bundle.extractall(destination)


def locate_bundle_root(extracted: Path) -> Path:
    matches = list(extracted.rglob("decision_outcomes.pkl.gz"))
    candidates = [path.parent for path in matches if (path.parent / "source" / "run.py").is_file()]
    if len(candidates) != 1:
        raise RuntimeError(f"expected one bundle root, found {candidates}")
    return candidates[0]


def verify_original_bundle(archive: Path, root: Path) -> dict[str, Any]:
    artifact_sha = sha256_file(archive)
    if artifact_sha != EXPECTED_ARTIFACT_SHA256:
        raise RuntimeError(f"artifact digest mismatch: {artifact_sha}")

    decision = root / "decision_outcomes.pkl.gz"
    source = root / "source" / "run.py"
    decision_sha = sha256_file(decision)
    source_sha = sha256_file(source)
    if decision_sha != EXPECTED_DECISION_SHA256:
        raise RuntimeError(f"decision-frame digest mismatch: {decision_sha}")
    if source_sha != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(f"source digest mismatch: {source_sha}")

    manifest = root / "OUTPUT_SHA256SUMS.txt"
    verified = 0
    missing: list[str] = []
    mismatches: list[dict[str, str]] = []
    if not manifest.is_file():
        raise RuntimeError("original artifact has no OUTPUT_SHA256SUMS.txt")
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, original_path = line.split(maxsplit=1)
        original_path = original_path.strip()
        marker = "/research_runs/l2_maker_toxicity_v4/"
        if marker not in original_path:
            continue
        relative = original_path.split(marker, 1)[1]
        target = root / relative
        if not target.is_file():
            missing.append(relative)
            continue
        observed = sha256_file(target)
        if observed != expected:
            mismatches.append({"path": relative, "expected": expected, "observed": observed})
        else:
            verified += 1
    if missing or mismatches:
        raise RuntimeError(json.dumps({"missing": missing, "mismatches": mismatches}, indent=2))
    return {
        "artifact_id": ARTIFACT_ID,
        "artifact_sha256": artifact_sha,
        "decision_frame_sha256": decision_sha,
        "original_source_sha256": source_sha,
        "manifest_file_count_verified": verified,
    }


def import_original_module(source: Path):
    spec = importlib.util.spec_from_file_location("l2_maker_original_v4", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load original source module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def decision_time_valid_mask(frame: pd.DataFrame, original) -> np.ndarray:
    bbo_age = frame["bbo_age_ms"].to_numpy(dtype=float)
    depth_age = frame["depth_age_ms"].to_numpy(dtype=float)
    spread = frame["spread_bp"].to_numpy(dtype=float)
    return (
        np.isfinite(bbo_age)
        & (bbo_age >= 0.0)
        & (bbo_age <= original.MAX_BBO_AGE_US / 1000.0)
        & np.isfinite(depth_age)
        & (depth_age >= 0.0)
        & (depth_age <= original.MAX_DEPTH_AGE_US / 1000.0)
        & np.isfinite(spread)
        & (spread > 0.0)
    )


def corrected_route_mask(frame: pd.DataFrame, route: str, original) -> np.ndarray:
    # Eligibility is fixed at the decision timestamp. `valid_order` is a
    # post-decision acknowledgement outcome and therefore must never screen a
    # signal or decide which side receives the one global slot.
    valid = decision_time_valid_mask(frame, original)
    if route == "unrestricted":
        return valid
    if route == "aligned_continuation":
        return (
            valid
            & (frame["side_signed_quote_1s_norm"].to_numpy(dtype=float) > 0.0)
            & (frame["side_mid_ret_1s_bp"].to_numpy(dtype=float) > 0.0)
            & (frame["side_microprice_skew_bp"].to_numpy(dtype=float) > 0.0)
        )
    if route == "absorption_reversal":
        return (
            valid
            & (frame["side_signed_quote_1s_norm"].to_numpy(dtype=float) < 0.0)
            & (frame["side_mid_ret_1s_bp"].to_numpy(dtype=float) >= 0.0)
            & (frame["side_refill_1s"].to_numpy(dtype=float) > 0.0)
        )
    raise ValueError(route)


def corrected_portfolio_metrics(returns_bp: list[float], dates: list[str]) -> dict[str, Any]:
    values = np.asarray(returns_bp, dtype=float)
    if len(values) == 0:
        return {
            "trades": 0,
            "multiple": 1.0,
            "mean_bp": 0.0,
            "profit_factor": 0.0,
            "mdd": 0.0,
            "top10_positive_share": 1.0,
            "after_top10_multiple": 1.0,
            "geometric_daily_growth": 0.0,
            "date_multiples": {},
        }
    simple = values / 1e4
    if np.any(simple <= -1.0):
        equity = np.cumprod(1.0 + simple)
    else:
        equity = np.exp(np.cumsum(np.log1p(simple)))
    path = np.concatenate(([1.0], equity))
    peak = np.maximum.accumulate(path)
    drawdown = 1.0 - path / peak
    positives = values[values > 0.0]
    negatives = values[values < 0.0]
    pf = positives.sum() / max(-negatives.sum(), 1e-12)
    top_n = min(10, len(positives))
    top_share = (
        float(np.sort(positives)[-top_n:].sum() / max(positives.sum(), 1e-12))
        if top_n
        else 1.0
    )
    remove = np.argsort(values)[-min(10, len(values)) :]
    keep = np.ones(len(values), dtype=bool)
    keep[remove] = False
    after = float(np.prod(1.0 + simple[keep])) if keep.any() else 1.0
    date_multiples: dict[str, float] = {}
    date_arr = np.asarray(dates)
    for date in sorted(set(dates)):
        date_multiples[date] = float(np.prod(1.0 + simple[date_arr == date]))
    geometric_daily_growth = float(
        np.prod(list(date_multiples.values())) ** (1.0 / max(len(date_multiples), 1)) - 1.0
    )
    return {
        "trades": int(len(values)),
        "multiple": float(equity[-1]),
        "mean_bp": float(values.mean()),
        "profit_factor": float(pf),
        "mdd": float(drawdown.max()),
        "top10_positive_share": top_share,
        "after_top10_multiple": after,
        "geometric_daily_growth": geometric_daily_growth,
        "date_multiples": date_multiples,
    }


def corrected_execute_candidate(
    frame: pd.DataFrame,
    score: np.ndarray,
    threshold: float,
    route: str,
    q: int,
    ttl: int,
    horizon: int,
    cost: float,
    original,
) -> dict[str, Any]:
    eligible = corrected_route_mask(frame, route, original) & np.isfinite(score) & (score >= threshold)
    order = np.lexsort((-score, frame["decision_us"].to_numpy(dtype=np.int64)))
    times = frame["decision_us"].to_numpy(dtype=np.int64)
    dates = frame["date"].astype(str).to_numpy()
    ack_accepted = frame["valid_order"].to_numpy(dtype=float) > 0.5
    fill_delay = frame[f"fill_delay_bins_q{q}"].to_numpy(dtype=float)
    gross = frame[f"gross_bp_q{q}_h{horizon}"].to_numpy(dtype=float)

    busy_until = -1
    returns: list[float] = []
    used_dates: list[str] = []
    decisions = 0
    ack_rejections = 0
    accepted_unfilled = 0
    unvalued_filled = 0
    index = 0
    while index < len(order):
        current_time = times[order[index]]
        group_end = index
        while group_end < len(order) and times[order[group_end]] == current_time:
            group_end += 1
        if current_time >= busy_until:
            candidates = [row for row in order[index:group_end] if eligible[row]]
            if candidates:
                selected = max(candidates, key=lambda row: score[row])
                decisions += 1
                if not ack_accepted[selected]:
                    # A rejected post-only submission releases the slot when the
                    # acknowledgement becomes available, not at an imagined TTL.
                    ack_rejections += 1
                    busy_until = current_time + original.ACK_BINS * original.BIN_US
                else:
                    delay = fill_delay[selected]
                    if np.isfinite(delay) and delay <= ttl * original.BINS_PER_SECOND:
                        fill_time = current_time + (original.ACK_BINS + int(delay)) * original.BIN_US
                        busy_until = fill_time + (
                            horizon * original.BINS_PER_SECOND + original.EXIT_LATENCY_BINS
                        ) * original.BIN_US
                        if np.isfinite(gross[selected]):
                            returns.append(float(gross[selected] - cost))
                            used_dates.append(str(dates[selected]))
                        else:
                            # A filled position may not disappear merely because
                            # the sampled exit quote is unavailable. Without a
                            # defensible price the candidate is hard-invalidated.
                            unvalued_filled += 1
                    else:
                        accepted_unfilled += 1
                        busy_until = current_time + (
                            original.ACK_BINS + ttl * original.BINS_PER_SECOND
                        ) * original.BIN_US
        index = group_end

    metrics = corrected_portfolio_metrics(returns, used_dates)
    metrics["order_decisions"] = decisions
    metrics["ack_rejections"] = ack_rejections
    metrics["accepted_unfilled"] = accepted_unfilled
    metrics["unvalued_filled_trades"] = unvalued_filled
    metrics["execution_path_valid"] = unvalued_filled == 0
    if unvalued_filled:
        # fit_and_screen's frozen gate requires both calibration sample dates
        # in date_multiples. Emptying it guarantees a filled-but-unvalued path
        # cannot advance and accidentally open validation.
        metrics["date_multiples"] = {}
    return metrics


def install_corrections(original) -> None:
    original.route_mask = lambda frame, route: corrected_route_mask(frame, route, original)
    original.portfolio_metrics = corrected_portfolio_metrics
    original.execute_candidate = lambda frame, score, threshold, route, q, ttl, horizon, cost: corrected_execute_candidate(
        frame, score, threshold, route, q, ttl, horizon, cost, original
    )


def run_self_tests(original) -> dict[str, bool]:
    base = {
        "date": ["2025-01-01", "2025-01-01"],
        "decision_us": [0, 5_000_000],
        "bbo_age_ms": [10.0, 10.0],
        "depth_age_ms": [10.0, 10.0],
        "spread_bp": [1.0, 1.0],
        "side_signed_quote_1s_norm": [1.0, 1.0],
        "side_mid_ret_1s_bp": [1.0, 1.0],
        "side_microprice_skew_bp": [1.0, 1.0],
        "side_refill_1s": [1.0, 1.0],
        "valid_order": [0.0, 1.0],
        "fill_delay_bins_q1": [np.nan, 1.0],
        "gross_bp_q1_h3": [np.nan, 20.0],
    }
    frame = pd.DataFrame(base)
    mask = corrected_route_mask(frame, "unrestricted", original)
    assert mask.tolist() == [True, True], "post-ack valid_order leaked into eligibility"
    metrics = corrected_execute_candidate(
        frame,
        np.asarray([2.0, 1.0]),
        threshold=0.0,
        route="unrestricted",
        q=1,
        ttl=10,
        horizon=3,
        cost=9.0,
        original=original,
    )
    assert metrics["order_decisions"] == 2, "ACK rejection did not release the global slot"
    assert metrics["ack_rejections"] == 1 and metrics["trades"] == 1

    invalid_exit = frame.copy()
    invalid_exit.loc[0, "valid_order"] = 1.0
    invalid_exit.loc[0, "fill_delay_bins_q1"] = 1.0
    invalid_exit.loc[0, "gross_bp_q1_h3"] = np.nan
    invalid_metrics = corrected_execute_candidate(
        invalid_exit.iloc[[0]],
        np.asarray([1.0]),
        threshold=0.0,
        route="unrestricted",
        q=1,
        ttl=10,
        horizon=3,
        cost=9.0,
        original=original,
    )
    assert invalid_metrics["unvalued_filled_trades"] == 1
    assert invalid_metrics["execution_path_valid"] is False
    assert invalid_metrics["date_multiples"] == {}

    dd = corrected_portfolio_metrics([100.0, -200.0, 50.0], ["a", "a", "a"])["mdd"]
    assert dd > 0.0, "maximum drawdown must be a positive magnitude"
    return {
        "decision_eligibility_ignores_post_ack_outcome": True,
        "ack_rejection_releases_slot": True,
        "filled_unvalued_path_cannot_advance": True,
        "maximum_drawdown_is_positive_magnitude": True,
    }


def finite_number(value: Any) -> Any:
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def candidate_snapshot(results: pd.DataFrame) -> dict[str, Any]:
    if results.empty:
        return {"candidate_count": 0}
    output: dict[str, Any] = {
        "candidate_count": int(len(results)),
        "calibration_gate_count": int(results["calibration_gate"].sum()),
        "validation_gate_count": int(results["validation_gate"].sum()),
        "positive_calibration_multiple_9bp_count": int((results["calib_9_multiple"] > 1.0).sum()),
        "positive_calibration_multiple_17bp_count": int((results["calib_17_multiple"] > 1.0).sum()),
        "max_calibration_trades_9bp": int(results["calib_9_trades"].max()),
        "candidates_with_unvalued_fills_9bp": int((results["calib_9_unvalued_filled_trades"] > 0).sum()),
        "candidates_with_unvalued_fills_17bp": int((results["calib_17_unvalued_filled_trades"] > 0).sum()),
    }
    nonzero = results[results["calib_9_trades"] > 0].copy()
    if not nonzero.empty:
        best_idx = nonzero["calib_9_mean_bp"].idxmax()
        row = results.loc[best_idx]
        fields = [
            "q",
            "ttl",
            "horizon",
            "mark_model",
            "route",
            "quantile",
            "threshold",
            "calib_9_order_decisions",
            "calib_9_ack_rejections",
            "calib_9_accepted_unfilled",
            "calib_9_unvalued_filled_trades",
            "calib_9_trades",
            "calib_9_mean_bp",
            "calib_9_multiple",
            "calib_9_profit_factor",
            "calib_9_mdd",
            "calib_9_after_top10_multiple",
            "calib_17_trades",
            "calib_17_mean_bp",
            "calib_17_multiple",
            "calib_17_mdd",
        ]
        output["best_nonzero_by_9bp_mean"] = {field: finite_number(row[field]) for field in fields}
    active = results[results["calib_9_trades"] >= 10].copy()
    if not active.empty:
        idx = active["calib_9_multiple"].idxmax()
        row = results.loc[idx]
        output["best_at_least_10_trades_by_9bp_multiple"] = {
            "q": int(row.q),
            "ttl": int(row.ttl),
            "horizon": int(row.horizon),
            "mark_model": str(row.mark_model),
            "route": str(row.route),
            "quantile": float(row.quantile),
            "trades": int(row.calib_9_trades),
            "mean_bp": float(row.calib_9_mean_bp),
            "multiple": float(row.calib_9_multiple),
            "mdd": float(row.calib_9_mdd),
            "stress_17bp_multiple": float(row.calib_17_multiple),
        }
    return output


def write_sha_manifest(output: Path) -> None:
    rows = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            rows.append(f"{sha256_file(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Causal correction of L2 maker V4 screen")
    parser.add_argument("--artifact-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="l2-causal-correction-") as temporary:
        extracted = Path(temporary) / "original"
        safe_extract(args.artifact_zip, extracted)
        root = locate_bundle_root(extracted)
        verification = verify_original_bundle(args.artifact_zip, root)
        original = import_original_module(root / "source" / "run.py")
        self_tests = run_self_tests(original)
        frame = pd.read_pickle(root / "decision_outcomes.pkl.gz", compression="gzip")

        causal_valid = decision_time_valid_mask(frame, original)
        post_ack_valid = frame["valid_order"].to_numpy(dtype=float) > 0.5
        audit = {
            "decision_rows": int(len(frame)),
            "decision_time_valid_rows": int(causal_valid.sum()),
            "original_post_ack_valid_order_rows": int(post_ack_valid.sum()),
            "future_ack_rejected_but_decision_valid_rows": int((causal_valid & ~post_ack_valid).sum()),
            "post_ack_valid_but_decision_invalid_rows": int((post_ack_valid & ~causal_valid).sum()),
            "original_route_mask_used_post_ack_valid_order": True,
            "original_mdd_was_signed_negative": True,
            "original_filled_unvalued_paths_by_queue_and_horizon": {},
        }
        for q in (1, 2, 3):
            delay = frame[f"fill_delay_bins_q{q}"].notna()
            for horizon in (3, 10, 30):
                gross_missing = frame[f"gross_bp_q{q}_h{horizon}"].isna()
                audit["original_filled_unvalued_paths_by_queue_and_horizon"][f"q{q}_h{horizon}"] = int(
                    (delay & gross_missing).sum()
                )

        install_corrections(original)
        results, screen_summary = original.fit_and_screen(frame)
        results.to_csv(args.output / "corrected_candidate_results.csv", index=False)
        survivors = results[results["calibration_gate"]].copy() if not results.empty else results.copy()
        survivors.to_csv(args.output / "corrected_calibration_survivors.csv", index=False)

        original_summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        snapshot = candidate_snapshot(results)
        correction_status = (
            "CORRECTED_SURVIVOR_REQUIRES_FURTHER_REVIEW"
            if screen_summary["calibration_gate_count"] > 0
            else "HARD_VALID_NEGATIVE_AFTER_CAUSAL_CORRECTION"
        )
        report = {
            "schema_version": 1,
            "correction_id": CORRECTION_ID,
            "source_claim_id": SOURCE_RESULT_SCOPE,
            "status": correction_status,
            "purpose": "Remove post-decision acknowledgement leakage, preserve causal global-slot state, invalidate filled-but-unvalued exits, and report MDD as a positive magnitude without changing the frozen economic grid.",
            "original_artifact": verification,
            "causal_audit": audit,
            "self_tests": self_tests,
            "frozen_scope": {
                "symbols": [original.SYMBOL],
                "fit_dates": list(original.FIT_DATES),
                "calibration_dates": list(original.CALIB_DATES),
                "validation_dates": list(original.VALID_DATES),
                "queue_multipliers": list(original.QUEUE_MULTIPLIERS),
                "ttls_seconds": list(original.TTLS_SECONDS),
                "horizons_seconds": list(original.HORIZONS_SECONDS),
                "routes": list(original.ROUTES),
                "score_quantiles": list(original.SCORE_QUANTILES),
                "cost_bps": list(original.COST_BPS),
                "grid_changed": False,
                "models_changed": False,
                "features_changed": False,
                "dates_opened_beyond_original": False
            },
            "original_reported_summary": original_summary,
            "corrected_screen_summary": screen_summary,
            "corrected_candidate_snapshot": snapshot,
            "interpretation": (
                "No calibration survivor remains after causal correction; the L2 maker family is reusable negative component evidence only and is not strategy-ranking or deployment eligible."
                if screen_summary["calibration_gate_count"] == 0
                else "At least one corrected calibration survivor exists; validation output must be independently audited before any project-state or ranking change."
            ),
            "orders_submitted": False,
            "paper_or_live_started": False
        }
        (args.output / "CORRECTION_RESULT.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (args.output / "AUDIT_FINDINGS.json").write_text(
            json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (args.output / "SELF_TESTS.json").write_text(
            json.dumps(self_tests, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        shutil.copy2(root / "summary.json", args.output / "ORIGINAL_SUMMARY.json")
        write_sha_manifest(args.output)
        print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
