from __future__ import annotations

import csv
import json
import re
import tomllib

from common import ROOT, read_jsonl


REQUIRED = [
    "README.md",
    "AGENTS.md",
    "config/project.toml",
    "config/evaluation.toml",
    "config/storage.toml",
    "config/workers.toml",
    "instructions/project-instructions.md",
    "control/current-state.md",
    "control/ranking.json",
    "control/work-claims.csv",
    "control/result-registry.jsonl",
    "control/validation-cache.jsonl",
    "data/catalog/source-registry.jsonl",
    "data/catalog/dataset-registry.jsonl",
    "schemas/ranking.schema.json",
    "schemas/source.schema.json",
    "schemas/run-report.schema.json",
    "schemas/work-claim.schema.json",
    "schemas/result.schema.json",
    "schemas/validation-attestation.schema.json",
]

AI_FACING_FILES = [
    "instructions/project-instructions.md",
    "prompts/goal-worker.md",
    "prompts/reconcile-state.md",
    "prompts/source-intake.md",
    "prompts/time-limit-checkpoint.md",
    "AGENTS.md",
    "README.md",
    "config/storage.toml",
    "control/current-state.md",
    "control/decisions.md",
    "data/README.md",
    "docs/architecture.md",
    "docs/data-retention.md",
    "docs/drive-layout.md",
    "docs/operating-playbook.md",
    "docs/ranking-policy.md",
]

FORBIDDEN_RUNTIME_PHRASES = [
    "동등한 독립 작업자",
    "총괄 채팅의 배정",
    "다른 채팅의 완료를 기다리지",
    "모델명",
    "구독 플랜",
    "규칙 작성 배경",
    "과거 대화의 해설",
    "자료별 저장 허가",
    "storage-permission investigation",
    "no mandatory coordinator",
    "fixed epoch",
    "serial handoff",
    "peer worker",
    "central_coordinator_required",
    "fixed_sequence",
    "mandatory_coordinator",
    "storage_permission_classification_required",
    "every chat is an independent goal worker",
    "all chats are peer workers",
    "no chat waits",
    "any chat may",
    "별도 총괄",
    "champion",
]

EFFICIENCY_REQUIREMENTS = {
    "instructions/project-instructions.md": [
        "전체 기록을 일괄 검토하지 않는다",
        "중복될 때 손실이 크거나 산출물의 재사용 가치가 높은 작업에만",
        "검증 깊이는 후보의 경제적 가능성과 의사결정 중요도에 비례",
        "사용하지 않은 검색 결과는 등록하지",
        "공용·재사용 가능한 코드",
        "완전한 run report는 목표 달성, 시간제한",
        "순위의 가장 중요한 기준은 현실적인 비용과 체결 후 일평균 기하 복리성장률의 1% 목표 격차",
        "순위는 연구 우선권",
        "현재 1위를 개선하거나 보호해야 한다는 이유",
        "순위 변경이나 접근 전환 때 이미 기록된 결과를 다시 백업·복제·재검증하지 않는다",
        "목표 달성 여부나 최종 검증 통과를 기다려 1위 선정을 미루지 않는다",
    ],
    "prompts/goal-worker.md": [
        "관련된 활성 work claim",
        "중복 비용이 크거나 산출물의 재사용 가치가 높은 작업에만",
        "검증 깊이를 후보의 경제적 가능성과 의사결정 중요도에 맞춘다",
        "공용·재사용 가능한 저장소 변경에만",
        "순위의 1차 기준은 현실 비용 후 일평균 기하성장률의 1% 목표 격차",
        "순위는 작업 우선순위",
        "이미 기록된 결과를 다시 백업·복제·재검증하지 않는다",
    ],
}


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def unique(values: list[str], label: str, errors: list[str]) -> None:
    cleaned = [value for value in values if value]
    if len(cleaned) != len(set(cleaned)):
        fail(f"duplicate {label}", errors)


def main() -> int:
    errors: list[str] = []
    for rel in REQUIRED:
        if not (ROOT / rel).exists():
            fail(f"missing: {rel}", errors)

    try:
        project = tomllib.loads((ROOT / "config/project.toml").read_text(encoding="utf-8"))
        repo = project["github"]["repository"]
        if repo.count("/") != 1:
            fail("invalid github.repository", errors)
        if project["state"].get("update_protocol") != "optimistic_revision":
            fail("unexpected state.update_protocol", errors)
        if project["state"].get("ranking_path") != "control/ranking.json":
            fail("unexpected state.ranking_path", errors)
        if "champion_path" in project["state"]:
            fail("legacy champion_path must be removed", errors)
        if not project["data"].get("reuse_before_external_search"):
            fail("data reuse must precede external search", errors)
    except Exception as exc:
        fail(f"project.toml: {exc}", errors)

    for rel in ["config/evaluation.toml", "config/storage.toml", "config/workers.toml"]:
        try:
            tomllib.loads((ROOT / rel).read_text(encoding="utf-8"))
        except Exception as exc:
            fail(f"{rel}: {exc}", errors)

    try:
        evaluation = tomllib.loads((ROOT / "config/evaluation.toml").read_text(encoding="utf-8"))
        if evaluation.get("validation", {}).get("mode") != "staged":
            fail("evaluation validation mode must be staged", errors)
        if not evaluation.get("validation", {}).get("depth_proportional_to_economic_promise_and_decision_value"):
            fail("validation depth must follow economic promise and decision value", errors)
        for stage in ["initial", "promising", "deep_validation"]:
            if not evaluation.get("stage", {}).get(stage, {}).get("required"):
                fail(f"evaluation stage missing requirements: {stage}", errors)
        if evaluation.get("stage", {}).get("deep_validation", {}).get("entry_condition") != "material_strategy_account_or_practical_use_decision":
            fail("deep validation must follow material decision value, not rank", errors)

        ranking_policy = evaluation.get("ranking", {})
        if ranking_policy.get("definition") != "ordered_hard_valid_strategy_or_portfolio_candidates":
            fail("ranking definition must use ordered hard-valid candidates", errors)
        if ranking_policy.get("first_place_role") != "current_result_closest_to_full_project_objective":
            fail("first place must mean closest current result to the objective", errors)
        if ranking_policy.get("primary_metric") != "realistic_after_cost_geometric_daily_growth_gap_to_target":
            fail("ranking primary metric must be target-gap based", errors)
        if ranking_policy.get("primary_target") != 0.01:
            fail("ranking target must remain 1%", errors)
        if ranking_policy.get("first_place_target_attainment_required") is not False:
            fail("first-place selection must not require target attainment", errors)
        if ranking_policy.get("first_place_full_validation_required") is not False:
            fail("first-place selection must not require full validation", errors)
        if not ranking_policy.get("survival_qualified_candidate_cannot_be_outranked_by_forced_liquidation_raw_return"):
            fail("ranking must enforce the account-survival constraint", errors)
        if ranking_policy.get("rank_grants_research_priority") is not False:
            fail("rank must not grant research priority", errors)
        if ranking_policy.get("rank_creates_default_improvement_target") is not False:
            fail("rank must not create a default improvement target", errors)
        if ranking_policy.get("extra_preservation_on_rank_change_required") is not False:
            fail("rank changes must not require repeated preservation", errors)
        if ranking_policy.get("work_selection_criterion") != "objective_impact_and_information_value":
            fail("work selection must be independent of rank", errors)
        if evaluation.get("final_reporting", {}).get("applies_to") != "material_strategy_portfolio_or_practical_use_decision":
            fail("final reporting scope is not materiality-gated", errors)
    except Exception as exc:
        fail(f"evaluation.toml: {exc}", errors)

    try:
        workers = tomllib.loads((ROOT / "config/workers.toml").read_text(encoding="utf-8"))
        work = workers["work"]
        lookup = workers["lookup"]
        validation = workers["validation"]
        records = workers["records"]
        defaults = workers["defaults"]

        if work.get("state_update_protocol") != "optimistic_revision":
            fail("unexpected work state_update_protocol", errors)
        if not work.get("claim_required_for_costly_or_reusable_work"):
            fail("costly/reusable work must use claims", errors)
        if not work.get("claim_optional_for_short_local_work"):
            fail("short local work must not require a new claim", errors)
        if not lookup.get("targeted_related_records_only"):
            fail("lookup must be targeted to the intended scope", errors)
        if lookup.get("full_registry_scan_by_default") is not False:
            fail("full registry scan must not be the default", errors)
        if validation.get("mode") != "staged":
            fail("validation must be staged", errors)
        if not records.get("register_used_or_reusable_sources_only"):
            fail("source registration must be use/reuse based", errors)
        if not records.get("minimal_metadata_first"):
            fail("source registration must start with minimal metadata", errors)
        if not records.get("full_run_report_for_material_checkpoint_only"):
            fail("full Run Reports must be limited to material checkpoints", errors)
        if not records.get("pull_request_for_shared_or_reusable_changes_only"):
            fail("PRs must be limited to shared or reusable changes", errors)
        if not defaults.get("check_active_claims"):
            fail("active work claims must be checked", errors)
        if not defaults.get("reuse_registered_artifacts"):
            fail("registered artifacts must be reused", errors)
    except Exception as exc:
        fail(f"workers.toml: {exc}", errors)

    try:
        ranking = json.loads((ROOT / "control/ranking.json").read_text(encoding="utf-8"))
        if ranking.get("schema_version") != 1:
            fail("ranking schema_version", errors)
        state_text = (ROOT / "control/current-state.md").read_text(encoding="utf-8")
        match = re.search(r"(?m)^- revision:\s*(\d+)\s*$", state_text)
        if not match:
            fail("current state revision missing", errors)
        elif ranking.get("revision") != int(match.group(1)):
            fail("ranking revision does not match current state", errors)
        if ranking.get("status") != "ACTIVE":
            fail("current project must have an active strategy ranking", errors)
        first = ranking.get("first_place")
        if not isinstance(first, dict) or first.get("rank") != 1:
            fail("ranking must contain first place", errors)
        if first and first.get("target_status") != "NOT_MET":
            fail("current first-place target status must remain NOT_MET", errors)
        metrics = first.get("metrics", {}) if isinstance(first, dict) else {}
        if metrics.get("target_geometric_daily_growth") != 0.01:
            fail("first-place target must remain 1%", errors)
        expected_gap = metrics.get("target_geometric_daily_growth", 0) - metrics.get("geometric_daily_growth", 0)
        if abs(metrics.get("target_gap", -999) - expected_gap) > 1e-12:
            fail("first-place target gap is inconsistent", errors)
        ranked = ranking.get("ranked_candidates", [])
        ranks = [row.get("rank") for row in ranked]
        gaps = [row.get("target_gap") for row in ranked]
        if ranks != sorted(ranks):
            fail("ranked candidates must be ordered by rank", errors)
        if gaps != sorted(gaps):
            fail("ranked candidates must primarily follow target gap", errors)
        if not ranking.get("ranking_rule", {}).get("rank_does_not_determine_work_priority"):
            fail("rank must not anchor work selection", errors)
        if "Rank does not determine research priority" not in state_text:
            fail("current state must prevent rank from anchoring work selection", errors)
    except Exception as exc:
        fail(f"ranking.json: {exc}", errors)

    try:
        rows = read_jsonl(ROOT / "data/catalog/source-registry.jsonl")
        unique([str(row.get("source_id", "")) for row in rows], "source_id", errors)
        unique([str(row.get("canonical_url", "")) for row in rows], "canonical_url", errors)
        unique([str(row.get("sha256", "")) for row in rows], "source sha256", errors)
    except Exception as exc:
        fail(f"source registry: {exc}", errors)

    try:
        with (ROOT / "control/work-claims.csv").open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = list(reader.fieldnames or [])
            claims = list(reader)
        required_claim_columns = {
            "claim_id",
            "worker_id",
            "scope_fingerprint",
            "base_revision",
            "status",
            "lease_until",
        }
        if not required_claim_columns.issubset(header):
            fail("work-claims header", errors)
        unique([row.get("claim_id", "") for row in claims], "claim_id", errors)
    except Exception as exc:
        fail(f"work claims: {exc}", errors)

    try:
        results = read_jsonl(ROOT / "control/result-registry.jsonl")
        unique([str(row.get("result_id", "")) for row in results], "result_id", errors)
        pairs = [
            f"{row.get('artifact_fingerprint', '')}:{row.get('dependency_fingerprint', '')}"
            for row in results
            if row.get("artifact_fingerprint") and row.get("dependency_fingerprint")
        ]
        unique(pairs, "result artifact/dependency fingerprint", errors)
    except Exception as exc:
        fail(f"result registry: {exc}", errors)

    try:
        attestations = read_jsonl(ROOT / "control/validation-cache.jsonl")
        unique([str(row.get("attestation_id", "")) for row in attestations], "attestation_id", errors)
    except Exception as exc:
        fail(f"validation cache: {exc}", errors)

    for rel in AI_FACING_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_RUNTIME_PHRASES:
            if phrase.lower() in text:
                fail(f"AI-facing meta-commentary or legacy terminology in {rel}: {phrase}", errors)

    for rel, fragments in EFFICIENCY_REQUIREMENTS.items():
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        for fragment in fragments:
            if fragment.lower() not in text:
                fail(f"missing efficiency or ranking rule in {rel}: {fragment}", errors)

    if (ROOT / "config/project.local.toml").exists():
        fail("config/project.local.toml must not be committed", errors)

    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("VALIDATION OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
