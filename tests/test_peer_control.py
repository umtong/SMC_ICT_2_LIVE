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


def test_champion_is_current_best_rank_pointer_not_goal_or_work_anchor():
    evaluation = tomllib.loads((ROOT / "config/evaluation.toml").read_text(encoding="utf-8"))
    policy = evaluation["champion"]
    champion = json.loads((ROOT / "control/champion.json").read_text(encoding="utf-8"))

    assert policy["definition"] == "current_best_hard_valid_strategy_or_portfolio_candidate"
    assert policy["role"] == "rank_pointer_to_registered_result"
    assert policy["select_when_any_comparable_hard_valid_candidate_exists"] is True
    assert policy["target_attainment_required"] is False
    assert policy["full_validation_required"] is False
    assert policy["economic_gate_failure_is_not_hard_invalidity"] is True
    assert policy["grants_research_priority"] is False
    assert policy["default_improvement_target"] is False
    assert policy["extra_preservation_on_switch_required"] is False
    assert policy["work_selection_criterion"] == "objective_impact_and_information_value"

    assert champion["status"] == "RESEARCH_CHAMPION"
    assert champion["champion_id"]
    assert champion["target_status"] == "NOT_MET"
    assert champion["qualification_stage"] == "EXPLORATORY"
    assert champion["metrics"]["target_geometric_daily_growth"] == 0.01
    assert champion["metrics"]["geometric_daily_growth"] < 0.01
    assert "current-rank pointer only" in champion["selection_reason"]


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


def test_runtime_instructions_apply_staged_validation_targeted_lookup_and_non_anchoring_champion_policy():
    text = (ROOT / "instructions/project-instructions.md").read_text(encoding="utf-8")
    assert "전체 기록을 일괄 검토하지 않는다" in text
    assert "검증 깊이는 후보의 경제적 가능성과 의사결정 중요도에 비례시킨다" in text
    assert "사용하지 않은 검색 결과는 등록하지" in text
    assert "공용·재사용 가능한 코드" in text
    assert "Champion은 목표 달성 인증이나 실사용 승인 상태가 아니라" in text
    assert "목표 달성 여부나 최종 검증 통과를 기다려 Champion 선정을 미루지 않는다" in text
    assert "Champion 지위는 연구 우선권" in text
    assert "다음 작업은 Champion 주변의 개선 여부가 아니라" in text
    assert "Champion 교체나 접근 전환 때 이미 기록된 결과를 다시 백업·복제·재검증하지 않는다" in text
    assert "현 Champion과 재현 조건을 보존한 뒤" not in text
    assert "Champion을 교체하거나 전략을 크게 변경하기 전에는 기존 Champion" not in text
