#!/usr/bin/env python3
"""Conditional third alpha: BTC/ETH SMT divergence -> CISD -> BPR/IFVG.

The information source differs from the single-market routes: a liquidity move
is eligible only when the paired major does not confirm it.  The event then
requires completed-bar delivery reversal and a causal repricing zone before the
action-value model chooses marketable confirmation or a passive retest.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

import run_cisd_bpr_ifvg_research as engine
from system.core import EventCandidate, FeatureConfig, build_causal_features


class SmtFamily(str, Enum):
    SMT_CISD_BPR_REVERSAL = "SMT_CISD_BPR_REVERSAL"


@dataclass(frozen=True)
class Divergence:
    position: int
    side: int
    swept_symbol: str
    partner_symbol: str
    swept_level: float
    sweep_extreme: float
    normalized_confirmation_gap: float
    relative_strength_z: float


def numeric_row(row: pd.Series) -> dict[str, float]:
    return {
        str(key): float(value)
        for key, value in row.items()
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)
    }


def prior_fvg(features: pd.DataFrame, position: int, bearish: bool, lookback: int = 24):
    for index in range(position - 1, max(2, position - lookback), -1):
        row = features.iloc[index]
        lower = row.get("bear_fvg_lower" if bearish else "bull_fvg_lower")
        upper = row.get("bear_fvg_upper" if bearish else "bull_fvg_upper")
        if pd.notna(lower) and pd.notna(upper) and float(lower) < float(upper):
            return index, float(lower), float(upper)
    return None


def external_target(row: pd.Series, side: int, price: float) -> float | None:
    if side > 0:
        values = (row.get("last_swing_high"), row.get("previous_day_high"), row.get("previous_week_high"))
        valid = sorted(float(value) for value in values if pd.notna(value) and float(value) > price)
    else:
        values = (row.get("last_swing_low"), row.get("previous_day_low"), row.get("previous_week_low"))
        valid = sorted((float(value) for value in values if pd.notna(value) and float(value) < price), reverse=True)
    return valid[0] if valid else None


def delivery_origin(features: pd.DataFrame, divergence_position: int, side: int) -> float | None:
    # Bullish reversal breaks the open of the last bearish delivery candle;
    # bearish reversal breaks the open of the last bullish delivery candle.
    for index in range(divergence_position, max(-1, divergence_position - 8), -1):
        row = features.iloc[index]
        if side > 0 and float(row["close"]) < float(row["open"]):
            return float(row["open"])
        if side < 0 and float(row["close"]) > float(row["open"]):
            return float(row["open"])
    return None


def rolling_relative_context(aligned: pd.DataFrame) -> pd.DataFrame:
    output = pd.DataFrame(index=aligned.index)
    btc_return = np.log(aligned["BTC_close"]).diff()
    eth_return = np.log(aligned["ETH_close"]).diff()
    output["btc_eth_corr_96"] = btc_return.rolling(96, min_periods=48).corr(eth_return)
    btc_12 = np.log(aligned["BTC_close"] / aligned["BTC_close"].shift(12))
    eth_12 = np.log(aligned["ETH_close"] / aligned["ETH_close"].shift(12))
    relative = btc_12 - eth_12
    mean = relative.rolling(288, min_periods=144).mean()
    std = relative.rolling(288, min_periods=144).std(ddof=0)
    output["btc_minus_eth_return_12"] = relative
    output["btc_minus_eth_strength_z"] = (relative - mean) / std.replace(0, np.nan)
    covariance = btc_return.rolling(288, min_periods=144).cov(eth_return)
    variance = eth_return.rolling(288, min_periods=144).var(ddof=0)
    beta = covariance / variance.replace(0, np.nan)
    output["btc_eth_beta_288"] = beta
    residual = btc_return - beta * eth_return
    residual_mean = residual.rolling(288, min_periods=144).mean()
    residual_std = residual.rolling(288, min_periods=144).std(ddof=0)
    output["btc_beta_residual_z"] = (residual - residual_mean) / residual_std.replace(0, np.nan)
    return output


def align_features(frames: Mapping[str, pd.DataFrame]):
    feature_config = FeatureConfig(
        atr_window=14,
        rsi_window=14,
        fast_ema=20,
        slow_ema=50,
        long_ema=200,
        volume_window=50,
        pivot_left=3,
        pivot_right=3,
        equal_tolerance_atr=0.12,
        displacement_body_atr=0.65,
        sweep_buffer_atr=0.02,
        retest_tolerance_atr=0.15,
    )
    calculated = {symbol: build_causal_features(frame, feature_config) for symbol, frame in frames.items()}
    common = calculated["BTCUSDT"].index.intersection(calculated["ETHUSDT"].index).sort_values()
    calculated = {symbol: frame.loc[common].copy() for symbol, frame in calculated.items()}
    aligned = pd.DataFrame(
        {
            "BTC_open": calculated["BTCUSDT"]["open"],
            "BTC_high": calculated["BTCUSDT"]["high"],
            "BTC_low": calculated["BTCUSDT"]["low"],
            "BTC_close": calculated["BTCUSDT"]["close"],
            "BTC_atr": calculated["BTCUSDT"]["atr"],
            "ETH_open": calculated["ETHUSDT"]["open"],
            "ETH_high": calculated["ETHUSDT"]["high"],
            "ETH_low": calculated["ETHUSDT"]["low"],
            "ETH_close": calculated["ETHUSDT"]["close"],
            "ETH_atr": calculated["ETHUSDT"]["atr"],
        },
        index=common,
    )
    context = rolling_relative_context(aligned)
    return calculated, aligned.join(context)


def find_divergence(
    aligned: pd.DataFrame,
    position: int,
    side: int,
    swept_symbol: str,
    partner_symbol: str,
) -> Divergence | None:
    # side > 0 is bullish SMT after a low sweep; side < 0 is bearish SMT after a high sweep.
    if position < 300:
        return None
    swept_prefix = "BTC" if swept_symbol == "BTCUSDT" else "ETH"
    partner_prefix = "BTC" if partner_symbol == "BTCUSDT" else "ETH"
    swept_atr = float(aligned.iloc[position][f"{swept_prefix}_atr"])
    partner_atr = float(aligned.iloc[position][f"{partner_prefix}_atr"])
    if not np.isfinite(swept_atr) or not np.isfinite(partner_atr) or swept_atr <= 0 or partner_atr <= 0:
        return None
    prior = aligned.iloc[position - 18 : position]
    current = aligned.iloc[position]
    if side > 0:
        swept_level = float(prior[f"{swept_prefix}_low"].min())
        partner_level = float(prior[f"{partner_prefix}_low"].min())
        sweep_extreme = float(current[f"{swept_prefix}_low"])
        partner_extreme = float(current[f"{partner_prefix}_low"])
        swept_distance = (swept_level - sweep_extreme) / swept_atr
        partner_distance = (partner_level - partner_extreme) / partner_atr
        reclaimed = float(current[f"{swept_prefix}_close"]) > swept_level
        unconfirmed = partner_distance < 0.03
    else:
        swept_level = float(prior[f"{swept_prefix}_high"].max())
        partner_level = float(prior[f"{partner_prefix}_high"].max())
        sweep_extreme = float(current[f"{swept_prefix}_high"])
        partner_extreme = float(current[f"{partner_prefix}_high"])
        swept_distance = (sweep_extreme - swept_level) / swept_atr
        partner_distance = (partner_extreme - partner_level) / partner_atr
        reclaimed = float(current[f"{swept_prefix}_close"]) < swept_level
        unconfirmed = partner_distance < 0.03
    if swept_distance < 0.035 or not reclaimed or not unconfirmed:
        return None
    gap = swept_distance - partner_distance
    if gap < 0.10:
        return None
    relative_z = float(current.get("btc_minus_eth_strength_z")) if pd.notna(current.get("btc_minus_eth_strength_z")) else 0.0
    return Divergence(
        position=position,
        side=side,
        swept_symbol=swept_symbol,
        partner_symbol=partner_symbol,
        swept_level=swept_level,
        sweep_extreme=sweep_extreme,
        normalized_confirmation_gap=gap,
        relative_strength_z=relative_z,
    )


def confirmed_candidate(
    calculated: Mapping[str, pd.DataFrame],
    aligned: pd.DataFrame,
    position: int,
    divergence: Divergence,
    last_key: dict[tuple[str, int, str], int],
) -> EventCandidate | None:
    features = calculated[divergence.swept_symbol]
    row = features.iloc[position]
    atr = float(row.get("atr")) if pd.notna(row.get("atr")) else math.nan
    if not np.isfinite(atr) or atr <= 0:
        return None
    origin = delivery_origin(features, divergence.position, divergence.side)
    if origin is None:
        return None
    close = float(row["close"])
    body_atr = float(row.get("body_atr")) if pd.notna(row.get("body_atr")) else 0.0
    if divergence.side > 0:
        confirmed = close > origin and body_atr >= 0.50 and close > float(features.iloc[position - 1]["high"])
        current_lower, current_upper = row.get("bull_fvg_lower"), row.get("bull_fvg_upper")
        opposite = prior_fvg(features, position, bearish=True)
    else:
        confirmed = close < origin and body_atr <= -0.50 and close < float(features.iloc[position - 1]["low"])
        current_lower, current_upper = row.get("bear_fvg_lower"), row.get("bear_fvg_upper")
        opposite = prior_fvg(features, position, bearish=False)
    if not confirmed or pd.isna(current_lower) or pd.isna(current_upper):
        return None
    current_lower, current_upper = float(current_lower), float(current_upper)
    if current_lower >= current_upper:
        return None
    variant = "CISD_FVG"
    zone_lower, zone_upper = current_lower, current_upper
    opposite_age = math.nan
    if opposite is not None:
        opposite_position, opposite_lower, opposite_upper = opposite
        opposite_age = float(position - opposite_position)
        overlap_lower = max(current_lower, opposite_lower)
        overlap_upper = min(current_upper, opposite_upper)
        if overlap_lower < overlap_upper:
            variant = "BPR"
            zone_lower, zone_upper = overlap_lower, overlap_upper
        else:
            inverted = close > opposite_upper if divergence.side > 0 else close < opposite_lower
            if inverted:
                variant = "IFVG"
                zone_lower, zone_upper = opposite_lower, opposite_upper
    key = (divergence.swept_symbol, divergence.side, variant)
    if key in last_key and position - last_key[key] < 12:
        return None
    entry = (zone_lower + zone_upper) / 2
    buffer = 0.05 * atr
    stop = divergence.sweep_extreme - buffer if divergence.side > 0 else divergence.sweep_extreme + buffer
    target = external_target(row, divergence.side, close)
    if target is None:
        return None
    protective = divergence.side * (entry - stop)
    reward = divergence.side * (target - entry)
    if protective <= 0 or reward <= 0:
        return None
    raw_rr = reward / protective
    minimum_rr = 1.35 if variant == "BPR" else 1.55 if variant == "IFVG" else 1.85
    if raw_rr < minimum_rr:
        return None
    zone_distance = divergence.side * (close - entry) / atr
    if not -0.15 <= zone_distance <= 2.4:
        return None
    partner = calculated[divergence.partner_symbol].iloc[position]
    aligned_row = aligned.iloc[position]
    feature_row = numeric_row(row)
    feature_row.update(
        {
            "alpha_smt_cisd": 1.0,
            "alpha_cisd_bpr_ifvg": 0.0,
            "variant_bpr": float(variant == "BPR"),
            "variant_ifvg": float(variant == "IFVG"),
            "variant_cisd_fvg": float(variant == "CISD_FVG"),
            "variant_code": engine.VARIANT_CODE[variant],
            "side": float(divergence.side),
            "smt_confirmation_gap_atr": divergence.normalized_confirmation_gap,
            "smt_divergence_age_bars": float(position - divergence.position),
            "smt_relative_strength_z": divergence.relative_strength_z,
            "btc_eth_corr_96": float(aligned_row.get("btc_eth_corr_96")) if pd.notna(aligned_row.get("btc_eth_corr_96")) else 0.0,
            "btc_eth_beta_288": float(aligned_row.get("btc_eth_beta_288")) if pd.notna(aligned_row.get("btc_eth_beta_288")) else 0.0,
            "btc_beta_residual_z": float(aligned_row.get("btc_beta_residual_z")) if pd.notna(aligned_row.get("btc_beta_residual_z")) else 0.0,
            "partner_body_atr": float(partner.get("body_atr")) if pd.notna(partner.get("body_atr")) else 0.0,
            "partner_ema_spread_atr": float(partner.get("ema_spread_atr")) if pd.notna(partner.get("ema_spread_atr")) else 0.0,
            "cisd_break_atr": divergence.side * (close - origin) / atr,
            "zone_width_atr": (zone_upper - zone_lower) / atr,
            "zone_distance_atr": zone_distance,
            "opposite_fvg_age_bars": opposite_age,
            "raw_reward_risk": raw_rr,
            "stop_distance_fraction": protective / max(entry, 1e-12),
            "target_distance_fraction": reward / max(entry, 1e-12),
            "symbol_btc": float(divergence.swept_symbol == "BTCUSDT"),
            "symbol_eth": float(divergence.swept_symbol == "ETHUSDT"),
            "decision_position": float(position),
        }
    )
    last_key[key] = position
    return EventCandidate(
        timestamp=pd.Timestamp(features.index[position]),
        symbol=divergence.swept_symbol,
        family=SmtFamily.SMT_CISD_BPR_REVERSAL,  # type: ignore[arg-type]
        side=divergence.side,
        decision_price=close,
        entry_reference=entry,
        stop_reference=stop,
        target_reference=target,
        structural_level=divergence.swept_level,
        feature_row=feature_row,
    )


def generate_joint_candidates(frames: Mapping[str, pd.DataFrame]):
    calculated, aligned = align_features(frames)
    pending: list[Divergence] = []
    candidates: list[EventCandidate] = []
    last_key: dict[tuple[str, int, str], int] = {}
    for position in range(300, len(aligned)):
        for side in (1, -1):
            for swept, partner in (("BTCUSDT", "ETHUSDT"), ("ETHUSDT", "BTCUSDT")):
                divergence = find_divergence(aligned, position, side, swept, partner)
                if divergence is not None:
                    pending.append(divergence)
        next_pending: list[Divergence] = []
        for divergence in pending:
            age = position - divergence.position
            if age < 1:
                next_pending.append(divergence)
                continue
            if age > 6:
                continue
            candidate = confirmed_candidate(calculated, aligned, position, divergence, last_key)
            if candidate is not None:
                candidates.append(candidate)
            else:
                next_pending.append(divergence)
        pending = next_pending
    candidates.sort(key=lambda row: (row.timestamp, row.symbol, row.side, row.entry_reference))
    return calculated, candidates


def run(args: argparse.Namespace) -> dict[str, Any]:
    data_start = engine.utc_timestamp(args.data_start)
    pre2024_start = engine.utc_timestamp(args.pre2024_start)
    official_start = engine.utc_timestamp(args.official_start)
    official_end = engine.utc_timestamp(args.official_end_exclusive)
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(engine.SYMBOLS)) as pool:
        futures = {
            symbol: pool.submit(engine.fetch_minute_klines, symbol, data_start, official_end, args.cache_dir)
            for symbol in engine.SYMBOLS
        }
        execution_frames = {symbol: future.result() for symbol, future in futures.items()}
    funding: dict[tuple[str, pd.Timestamp], float] = {}
    for symbol in engine.SYMBOLS:
        funding.update(engine.fetch_funding(symbol, data_start, official_end, args.cache_dir))
    decision_frames = {symbol: engine.resample_decision(frame) for symbol, frame in execution_frames.items()}
    calculated, candidates = generate_joint_candidates(decision_frames)
    labels = engine.build_action_labels(candidates, execution_frames, engine.DEFAULT_EXECUTION)
    label_path = args.output / "SMT_CISD_ACTION_LABELS.parquet"
    labels.to_parquet(label_path, index=False)

    basic_results: list[dict[str, Any]] = []
    prediction_cache: dict[tuple[str, str], tuple[list[engine.PredictionRecord], list[dict[str, Any]]]] = {}
    for variant_name, variants in engine.VARIANT_SETS.items():
        for spec in engine.MODEL_SPECS:
            predictions, ledger = engine.walk_forward_predictions(
                candidates, labels, pre2024_start, official_start, spec, variants
            )
            prediction_cache[(variant_name, spec.name)] = (predictions, ledger)
            metrics, _ = engine.replay_predictions(
                predictions,
                execution_frames,
                funding,
                pre2024_start,
                official_start,
                risk_fraction=0.01,
                maximum_leverage=5.0,
                confidence_penalty=spec.confidence_penalty,
            )
            result = {
                "identifier": f"{variant_name}_{spec.name}",
                "variant_set": variant_name,
                "model_spec": dataclasses.asdict(spec),
                "prediction_count": len(predictions),
                "update_records": ledger,
                "metrics": metrics,
            }
            basic_results.append(result)
            print(json.dumps({"stage": "basic", "id": result["identifier"], "metrics": metrics}, ensure_ascii=False), flush=True)

    selected_basic = max(basic_results, key=lambda row: engine.result_key(row["metrics"])) if basic_results else None
    positive_basic = bool(selected_basic and float(selected_basic["metrics"].get("geometric_daily_growth") or 0.0) > 0)
    risk_results: list[dict[str, Any]] = []
    selected_risk = None
    official_result = None
    if positive_basic and selected_basic is not None:
        variant_name = str(selected_basic["variant_set"])
        spec = next(row for row in engine.MODEL_SPECS if row.name == selected_basic["model_spec"]["name"])
        predictions, _ = prediction_cache[(variant_name, spec.name)]
        for risk_fraction in (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.20):
            for leverage in (2.0, 5.0, 10.0, 20.0, 50.0, 100.0):
                metrics, _ = engine.replay_predictions(
                    predictions,
                    execution_frames,
                    funding,
                    pre2024_start,
                    official_start,
                    risk_fraction=risk_fraction,
                    maximum_leverage=leverage,
                    confidence_penalty=spec.confidence_penalty,
                )
                risk_results.append({
                    "identifier": f"RISK_{risk_fraction:.4f}_LEV_{leverage:.0f}",
                    "risk_fraction": risk_fraction,
                    "maximum_leverage": leverage,
                    "metrics": metrics,
                })
        selected_risk = max(risk_results, key=lambda row: engine.result_key(row["metrics"]))
        predictions, ledger = engine.walk_forward_predictions(
            candidates,
            labels,
            official_start,
            official_end,
            spec,
            engine.VARIANT_SETS[variant_name],
        )
        metrics, account = engine.replay_predictions(
            predictions,
            execution_frames,
            funding,
            official_start,
            official_end,
            risk_fraction=float(selected_risk["risk_fraction"]),
            maximum_leverage=float(selected_risk["maximum_leverage"]),
            confidence_penalty=spec.confidence_penalty,
        )
        official_result = {
            "stage": "OFFICIAL_2024H1_COARSE_PENDING_EVENT_TAPE",
            "configuration": {
                "variant_set": variant_name,
                "model_spec": dataclasses.asdict(spec),
                "risk_fraction": selected_risk["risk_fraction"],
                "maximum_leverage": selected_risk["maximum_leverage"],
            },
            "prediction_count": len(predictions),
            "update_records": ledger,
            "metrics": metrics,
            "closed_trade_count": len(account.closed_trades),
        }

    summary = {
        "schema_version": 1,
        "strategy_id": "YT_TRINITY_SMT_CISD_BPR_ACTION_VALUE_V1",
        "stage": "PRE2024_CAUSAL_COARSE_SCREEN_NOT_RANKABLE",
        "economic_hypothesis": "unconfirmed BTC/ETH external-liquidity execution followed by CISD and BPR/IFVG repricing",
        "data": {
            "venue": "Bybit",
            "category": "linear",
            "symbols": list(engine.SYMBOLS),
            "data_start": data_start.isoformat(),
            "pre2024_start": pre2024_start.isoformat(),
            "official_start": official_start.isoformat(),
            "official_end_exclusive": official_end.isoformat(),
            "decision_timeframe": "synchronized 5m completed bars",
            "execution_timeframe": "1m conservative stop-first",
            "minute_row_counts": {symbol: len(frame) for symbol, frame in execution_frames.items()},
            "feature_row_counts": {symbol: len(frame) for symbol, frame in calculated.items()},
            "funding_event_count": len(funding),
        },
        "execution_contract": dataclasses.asdict(engine.DEFAULT_EXECUTION),
        "candidate_count": len(candidates),
        "variant_candidate_counts": {
            name: sum(
                ("BPR" if row.feature_row.get("variant_bpr") else "IFVG" if row.feature_row.get("variant_ifvg") else "CISD_FVG") == name
                for row in candidates
            )
            for name in ("BPR", "IFVG", "CISD_FVG")
        },
        "action_label_count": len(labels),
        "action_label_sha256": engine.sha256_file(label_path),
        "basic_results": basic_results,
        "selected_basic": selected_basic,
        "pre2024_positive_basic_alpha": positive_basic,
        "risk_results": risk_results,
        "selected_risk": selected_risk,
        "official_2024h1": official_result,
        "official_open_authority": positive_basic,
        "rankable": False,
        "rankability_blockers": [
            "complete three-channel content corpus and audited ontology are not yet bound",
            "one-minute stop-first replay must be replaced by event-tape execution for a survivor",
            "historical observed bid/ask and depth are not present in this coarse screen",
        ],
        "decision": "POSITIVE_PRE2024_OPENED_2024H1_COARSE" if positive_basic else "ECONOMIC_FAIL_SWITCH_ALPHA",
        "parent_failed_routes": [
            "YT_TRINITY_CISD_BPR_IFVG_ACTION_VALUE_V1",
            "YT_TRINITY_COMPRESSION_BPR_CONTINUATION_ACTION_VALUE_V1",
        ],
    }
    path = args.output / "RUN_SUMMARY.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "RUN_SUMMARY.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  RUN_SUMMARY.json\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-start", default="2022-01-01T00:00:00Z")
    parser.add_argument("--pre2024-start", default="2023-01-01T00:00:00Z")
    parser.add_argument("--official-start", default="2024-01-01T00:00:00Z")
    parser.add_argument("--official-end-exclusive", default="2024-07-01T00:00:00Z")
    args = parser.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
