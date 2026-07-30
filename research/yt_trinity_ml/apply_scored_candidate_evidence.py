#!/usr/bin/env python3
"""Persist the exact scored/action candidates consumed by event-tape replay."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"anchor missing in {path}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    full = ROOT / "research/yt_trinity_ml/run_full_sequential_survivor.py"
    replace(
        full,
        '''    realistic_config = engine.DEFAULT_EXECUTION\n    zero_config = CoarseExecutionConfig(''',
        '''    scored_for_tape = engine.score_predictions(predictions, risk_fraction, model_spec.confidence_penalty)\n    scored_rows = []\n    for scored in scored_for_tape:\n        candidate = scored.candidate\n        scored_rows.append({\n            "timestamp": candidate.timestamp,\n            "symbol": candidate.symbol,\n            "family": candidate.family.value,\n            "side": candidate.side,\n            "decision_price": candidate.decision_price,\n            "entry_reference": candidate.entry_reference,\n            "stop_reference": candidate.stop_reference,\n            "target_reference": candidate.target_reference,\n            "structural_level": candidate.structural_level,\n            "feature_row": dict(candidate.feature_row),\n            "win_probability": scored.win_probability,\n            "expected_net_r": scored.expected_net_r,\n            "passive_fill_probability": scored.passive_fill_probability,\n            "expected_log_growth": scored.expected_log_growth,\n            "lower_confidence_score": scored.lower_confidence_score,\n            "chosen_action": scored.chosen_action.value,\n        })\n    scored_sha = write_jsonl(args.output / "SCORED_CANDIDATES.jsonl", scored_rows)\n\n    realistic_config = engine.DEFAULT_EXECUTION\n    zero_config = CoarseExecutionConfig(''',
    )
    replace(
        full,
        '''            "fills_sha256": fill_sha,\n            "daily_nav_rows": len(daily_rows),''',
        '''            "fills_sha256": fill_sha,\n            "scored_candidates_sha256": scored_sha,\n            "scored_candidate_rows": len(scored_rows),\n            "daily_nav_rows": len(daily_rows),''',
    )

    pooled = ROOT / "research/yt_trinity_ml/run_pooled_trinity_system.py"
    replace(
        pooled,
        '''            realistic_config, zero_config, stressed_config = full_execution_triplet()\n            realistic_metrics, realistic_account = full.replay_with_contract(''',
        '''            scored_for_tape = engine.score_predictions(\n                official_predictions, float(selected_risk["risk_fraction"]), spec.confidence_penalty\n            )\n            scored_rows = []\n            for scored in scored_for_tape:\n                candidate = scored.candidate\n                scored_rows.append({\n                    "timestamp": candidate.timestamp,\n                    "symbol": candidate.symbol,\n                    "family": candidate.family.value,\n                    "side": candidate.side,\n                    "decision_price": candidate.decision_price,\n                    "entry_reference": candidate.entry_reference,\n                    "stop_reference": candidate.stop_reference,\n                    "target_reference": candidate.target_reference,\n                    "structural_level": candidate.structural_level,\n                    "feature_row": dict(candidate.feature_row),\n                    "win_probability": scored.win_probability,\n                    "expected_net_r": scored.expected_net_r,\n                    "passive_fill_probability": scored.passive_fill_probability,\n                    "expected_log_growth": scored.expected_log_growth,\n                    "lower_confidence_score": scored.lower_confidence_score,\n                    "chosen_action": scored.chosen_action.value,\n                })\n            scored_sha = full.write_jsonl(args.output / "SCORED_CANDIDATES.jsonl", scored_rows)\n            realistic_config, zero_config, stressed_config = full_execution_triplet()\n            realistic_metrics, realistic_account = full.replay_with_contract(''',
    )
    replace(
        pooled,
        '''                    "fills_sha256": fill_sha,\n                    "daily_nav_rows": len(daily_rows),''',
        '''                    "fills_sha256": fill_sha,\n                    "scored_candidates_sha256": scored_sha,\n                    "scored_candidate_rows": len(scored_rows),\n                    "daily_nav_rows": len(daily_rows),''',
    )
    print("scored candidate evidence integrated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
