from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RANKING = ROOT / "control" / "ranking.json"
STATE = ROOT / "control" / "current-state.md"
RESULT = ROOT / "research_results" / "rank_contract_reconcile_20260726" / "RESULT.json"
DECISION = ROOT / "research_results" / "rank_contract_reconcile_20260726" / "DECISION.json"
CORRECTION = (
    ROOT
    / "research_results"
    / "rank_contract_reconcile_20260726"
    / "CORRECTION_001_ALL_BREAKOUT_CANONICAL_FIRST.json"
)

FIRST_ID = "FIRST-20260726-DONCHIAN-ALL-A70626D9E484"
FIRST_CANDIDATE = "a70626d9e484285f2cb4|all"
SECOND_CANDIDATE = "a70626d9e484285f2cb4|after_loser"
GROWTH_12 = 0.0009008544402622221
GROWTH_24 = 0.0007001887213879954
AFTER_LOSER_12 = 0.0008299955525170599
AFTER_LOSER_24 = 0.0006318446194384375
TOL = 1e-15


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def close(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= TOL


def main() -> int:
    ranking = load(RANKING)
    result = load(RESULT)
    decision = load(DECISION)
    correction = load(CORRECTION)
    state = STATE.read_text(encoding="utf-8")

    assert ranking["revision"] == 14
    assert ranking["ranking_id"] == "STRATEGY-RANKING-20260726-R14"
    first = ranking["first_place"]
    assert first["first_place_id"] == FIRST_ID
    assert first["metrics"]["candidate_id"] == FIRST_CANDIDATE
    assert close(first["metrics"]["geometric_daily_growth"], GROWTH_12)
    assert close(first["metrics"]["geometric_daily_growth_at_24bps"], GROWTH_24)
    assert first["comparison_confidence"] == "VERY_LOW"
    assert first["metrics"]["complete_risk_metrics_available"] is False
    assert first["target_status"] == "NOT_MET"

    ranked = ranking["ranked_candidates"]
    assert [row["rank"] for row in ranked] == list(range(1, len(ranked) + 1))
    assert ranked[0]["candidate_label"].endswith(FIRST_CANDIDATE)
    assert close(ranked[0]["geometric_daily_growth"], GROWTH_12)
    assert close(ranked[0]["geometric_daily_growth_at_24bps"], GROWTH_24)
    assert ranked[1]["candidate_label"].endswith(SECOND_CANDIDATE)
    assert close(ranked[1]["geometric_daily_growth"], AFTER_LOSER_12)
    assert close(ranked[1]["geometric_daily_growth_at_24bps"], AFTER_LOSER_24)
    assert ranked[0]["geometric_daily_growth"] > ranked[1]["geometric_daily_growth"]

    durable_first = result["new_current_first_place"]
    assert durable_first["first_place_id"] == FIRST_ID
    assert durable_first["candidate_id"] == FIRST_CANDIDATE
    assert close(durable_first["geometric_daily_growth"], GROWTH_12)
    assert close(durable_first["geometric_daily_growth_24bps"], GROWTH_24)
    assert result["ranking_decision"]["new_first_place_id"] == FIRST_ID

    decision_first = decision["new_first"]
    assert decision_first["first_place_id"] == FIRST_ID
    assert decision_first["candidate_id"] == FIRST_CANDIDATE
    assert close(decision_first["geometric_daily_growth"], GROWTH_12)
    assert close(decision_first["geometric_daily_growth_at_24bps"], GROWTH_24)
    decision_second = decision["second_place_with_complete_metrics"]
    assert decision_second["candidate_id"] == SECOND_CANDIDATE
    assert close(decision_second["geometric_daily_growth"], AFTER_LOSER_12)

    canonical = correction["canonical_first_place"]
    assert canonical["first_place_id"] == FIRST_ID
    assert canonical["candidate_id"] == FIRST_CANDIDATE
    assert close(canonical["geometric_daily_growth_12bps"], GROWTH_12)
    assert close(canonical["geometric_daily_growth_24bps"], GROWTH_24)
    assert correction["authority"]["market_data_opened"] is False
    assert correction["authority"]["strategy_replayed"] is False
    assert correction["authority"]["orders_submitted"] is False

    assert "- revision: 14" in state
    assert f"- current first place: `{FIRST_ID}`" in state
    assert "0.0900854%" in state
    assert "0.0700189%" in state
    assert "live_order_permission: none" in state

    former = {
        row["source_result_id"]: row
        for row in ranking["unranked_results"]
        if "source_result_id" in row
    }["RES-20260725-DYNAMIC-FACTOR-001"]
    assert "elapsed-time liquidation" in former["reason"]

    print(
        json.dumps(
            {
                "status": "PASS",
                "ranking_revision": ranking["revision"],
                "first_place_id": FIRST_ID,
                "growth_12bps": GROWTH_12,
                "growth_24bps": GROWTH_24,
                "second_candidate": SECOND_CANDIDATE,
                "market_data_opened": False,
                "orders_submitted": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
