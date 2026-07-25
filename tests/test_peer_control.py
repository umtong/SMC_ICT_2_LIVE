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
    assert evaluation["final_reporting"]["applies_to"] == "current_champion_challenger_or_material_final_report"


def test_champion_is_current_best_not_goal_certification():
    evaluation = tomllib.loads((ROOT / "config/evaluation.toml").read_text(encoding="utf-8"))
    policy = evaluation["champion"]
    champion = json.loads((ROOT / "control/champion.json").read_text(encoding="utf-8"))

    assert policy["definition"] == "current_best_hard_valid_strategy_or_portfolio_candidate"
    assert policy["select_when_any_comparable_hard_valid_candidate_exists"] is True
    assert policy["target_attainment_required"] is False
    assert policy["full_validation_required"] is False
    assert policy["economic_gate_failure_is_not_hard_invalidity"] is True

    assert champion["status"] == "RESEARCH_CHAMPION"
    assert champion["champion_id"]
    assert champion["target_status"] == "NOT_MET"
    assert champion["qualification_stage"] == "EXPLORATORY"
    assert champion["metrics"]["target_geometric_daily_growth"] == 0.01
    assert champion["metrics"]["geometric_daily_growth"] < 0.01


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


def test_runtime_instructions_apply_staged_validation_targeted_lookup_and_champion_policy():
    text = (ROOT / "instructions/project-instructions.md").read_text(encoding="utf-8")
    assert "전체 기록을 일괄 검토하지 않는다" in text
    assert "검증 깊이는 후보의 경제적 가능성과 의사결정 중요도에 비례시킨다" in text
    assert "사용하지 않은 검색 결과는 등록하지" in text
    assert "공용·재사용 가능한 코드" in text
    assert "Champion은 목표 달성 인증이나 실사용 승인 상태가 아니라" in text
    assert "목표 달성 여부나 최종 검증 통과를 기다려 Champion 선정을 미루지 않는다" in text
