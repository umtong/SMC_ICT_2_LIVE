import csv
import json
import tomllib
from pathlib import Path

from scripts.common import read_jsonl


ROOT = Path(__file__).parents[1]


def test_work_configuration_uses_conditional_efficiency_gates():
    project = tomllib.loads((ROOT / "config/project.toml").read_text(encoding="utf-8"))
    workers = tomllib.loads((ROOT / "config/workers.toml").read_text(encoding="utf-8"))
    evaluation = tomllib.loads((ROOT / "config/evaluation.toml").read_text(encoding="utf-8"))

    assert project["state"]["update_protocol"] == "optimistic_revision"
    assert project["state"]["ranking_path"] == "control/ranking.json"
    assert project["data"]["reuse_before_external_search"] is True

    assert workers["work"]["state_update_protocol"] == "optimistic_revision"
    assert workers["work"]["claim_required_for_costly_or_reusable_work"] is True
    assert workers["work"]["claim_optional_for_short_local_work"] is True

    assert workers["lookup"]["targeted_related_records_only"] is True
    assert workers["lookup"]["full_registry_scan_by_default"] is False

    assert workers["validation"]["mode"] == "staged"

    assert workers["records"]["register_used_or_reusable_sources_only"] is True
    assert workers["records"]["minimal_metadata_first"] is True
    assert workers["records"]["full_run_report_for_material_checkpoint_only"] is True
    assert workers["records"]["pull_request_for_shared_or_reusable_changes_only"] is True

    assert evaluation["validation"]["mode"] == "staged"
    assert evaluation["validation"]["depth_proportional_to_economic_promise_and_decision_value"] is True
    assert evaluation["stage"]["initial"]["purpose"] == "cheap_rejection"
    assert evaluation["stage"]["deep_validation"]["entry_condition"] == "material_strategy_account_or_practical_use_decision"
    assert evaluation["final_reporting"]["applies_to"] == "material_strategy_portfolio_or_practical_use_decision"


def test_ranking_uses_goal_proximity_and_is_not_a_work_anchor():
    evaluation = tomllib.loads((ROOT / "config/evaluation.toml").read_text(encoding="utf-8"))
    policy = evaluation["ranking"]
    ranking = json.loads((ROOT / "control/ranking.json").read_text(encoding="utf-8"))

    assert policy["definition"] == "ordered_hard_valid_strategy_or_portfolio_candidates"
    assert policy["first_place_role"] == "current_result_closest_to_full_project_objective"
    assert policy["primary_metric"] == "realistic_after_cost_geometric_daily_growth_gap_to_target"
    assert policy["primary_target"] == 0.01
    assert policy["first_place_target_attainment_required"] is False
    assert policy["first_place_full_validation_required"] is False
    assert policy["economic_gate_failure_is_not_hard_invalidity"] is True
    assert policy["rank_grants_research_priority"] is False
    assert policy["rank_creates_default_improvement_target"] is False
    assert policy["extra_preservation_on_rank_change_required"] is False
    assert policy["work_selection_criterion"] == "objective_impact_and_information_value"

    assert ranking["status"] == "ACTIVE"
    assert ranking["first_place"]["rank"] == 1
    assert ranking["first_place"]["target_status"] == "NOT_MET"
    assert ranking["first_place"]["qualification_stage"] == "EXPLORATORY"
    assert ranking["first_place"]["metrics"]["target_geometric_daily_growth"] == 0.01
    assert ranking["first_place"]["metrics"]["geometric_daily_growth"] < 0.01
    assert ranking["first_place"]["metrics"]["target_gap"] > 0
    assert ranking["ranking_rule"]["rank_does_not_determine_work_priority"] is True

    ranks = [row["rank"] for row in ranking["ranked_candidates"]]
    gaps = [row["target_gap"] for row in ranking["ranked_candidates"]]
    assert ranks == sorted(ranks)
    assert gaps == sorted(gaps)


def test_work_claim_registry_has_deduplication_fields():
    with (ROOT / "control/work-claims.csv").open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    required = {
        "claim_id",
        "worker_id",
        "objective_fingerprint",
        "scope_fingerprint",
        "base_revision",
        "lease_until",
        "overlap_reason",
    }
    assert required.issubset(header)


def test_reuse_registries_are_parseable():
    read_jsonl(ROOT / "control/result-registry.jsonl")
    read_jsonl(ROOT / "control/validation-cache.jsonl")


def test_runtime_instructions_use_first_place_and_goal_proximity():
    text = (ROOT / "instructions/project-instructions.md").read_text(encoding="utf-8")
    assert "전체 기록을 일괄 검토하지 않는다" in text
    assert "검증 깊이는 후보의 경제적 가능성과 의사결정 중요도에 비례시킨다" in text
    assert "사용하지 않은 검색 결과는 등록하지" in text
    assert "공용·재사용 가능한 코드" in text
    assert "순위의 가장 중요한 기준" in text
    assert "일평균 기하 복리성장률의 1% 목표 격차" in text
    assert "순위는 연구 우선권" in text
    assert "현재 1위를 개선하거나 보호해야 한다는 이유" in text
    assert "순위 변경이나 접근 전환 때 이미 기록된 결과를 다시 백업·복제·재검증하지 않는다" in text
    assert "목표 달성 여부나 최종 검증 통과를 기다려 1위 선정을 미루지 않는다" in text
    assert "Champion" not in text
