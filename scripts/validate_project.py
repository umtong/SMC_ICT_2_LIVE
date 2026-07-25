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
    "control/champion.json",
    "control/work-claims.csv",
    "control/result-registry.jsonl",
    "control/validation-cache.jsonl",
    "data/catalog/source-registry.jsonl",
    "data/catalog/dataset-registry.jsonl",
    "schemas/champion.schema.json",
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
    "fixed_epoch",
    "storage_permission_classification_required",
    "every chat is an independent goal worker",
    "all chats are peer workers",
    "no chat waits",
    "any chat may",
    "별도 총괄",
    "작업 시작 시 최신 project state, champion, 활성 work claim",
    "현 champion과 재현 조건을 보존한 뒤",
    "champion을 교체하거나 전략을 크게 변경하기 전에는 기존 champion",
]

EFFICIENCY_REQUIREMENTS = {
    "instructions/project-instructions.md": [
        "전체 기록을 일괄 검토하지 않는다",
        "중복될 때 손실이 크거나 산출물의 재사용 가치가 높은 작업에만",
        "검증 깊이는 후보의 경제적 가능성과 의사결정 중요도에 비례",
        "사용하지 않은 검색 결과는 등록하지",
        "공용·재사용 가능한 코드",
        "완전한 run report는 목표 달성, 시간제한",
        "champion은 목표 달성 인증이나 실사용 승인 상태가 아니라",
        "champion 지위는 연구 우선권",
        "다음 작업은 champion 주변의 개선 여부가 아니라",
        "champion 교체나 접근 전환 때 이미 기록된 결과를 다시 백업·복제·재검증하지 않는다",
        "목표 달성 여부나 최종 검증 통과를 기다려 champion 선정을 미루지 않는다",
    ],
    "prompts/goal-worker.md": [
        "관련된 활성 work claim",
        "중복 비용이 크거나 산출물의 재사용 가치가 높은 작업에만",
        "검증 깊이를 후보의 경제적 가능성과 의사결정 중요도에 맞춘다",
        "공용·재사용 가능한 저장소 변경에만",
        "champion은 최종 목표 달성 인증이 아니라",
        "champion 지위는 작업 우선순위",
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
            fail("deep validation must follow material decision value, not Champion status", errors)
        champion_policy = evaluation.get("champion", {})
        if champion_policy.get("definition") != "current_best_hard_valid_strategy_or_portfolio_candidate":
            fail("Champion definition must be current-best hard-valid candidate", errors)
        if champion_policy.get("role") != "rank_pointer_to_registered_result":
            fail("Champion role must be a rank pointer to a registered result", errors)
        if champion_policy.get("target_attainment_required") is not False:
            fail("Champion selection must not require target attainment", errors)
        if champion_policy.get("full_validation_required") is not False:
            fail("Champion selection must not require full validation", errors)
        if not champion_policy.get("select_when_any_comparable_hard_valid_candidate_exists"):
            fail("Champion must be selected when a comparable hard-valid candidate exists", errors)
        if champion_policy.get("grants_research_priority") is not False:
            fail("Champion must not grant research priority", errors)
        if champion_policy.get("default_improvement_target") is not False:
            fail("Champion must not become the default improvement target", errors)
        if champion_policy.get("extra_preservation_on_switch_required") is not False:
            fail("Champion switch must not require repeated preservation work", errors)
        if champion_policy.get("work_selection_criterion") != "objective_impact_and_information_value":
            fail("work selection must be independent of Champion status", errors)
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
        champion = json.loads((ROOT / "control/champion.json").read_text(encoding="utf-8"))
        if champion.get("schema_version") != 2:
            fail("champion schema_version", errors)
        state_text = (ROOT / "control/current-state.md").read_text(encoding="utf-8")
        match = re.search(r"(?m)^- revision:\s*(\d+)\s*$", state_text)
        if not match:
            fail("current state revision missing", errors)
        elif champion.get("revision") != int(match.group(1)):
            fail("Champion revision does not match current state", errors)
        if champion.get("status") == "NONE":
            fail("current project has comparable hard-valid candidates but Champion is NONE", errors)
        for key in [
            "champion_id",
            "candidate_type",
            "source_result_id",
            "qualification_stage",
            "target_status",
            "selection_reason",
            "comparison_confidence",
            "metrics",
            "known_weaknesses",
            "component_leaders",
        ]:
            if key not in champion:
                fail(f"Champion missing field: {key}", errors)
        if champion.get("target_status") != "NOT_MET":
            fail("current Champion target status must remain NOT_MET", errors)
        if "current-rank pointer only" not in champion.get("selection_reason", ""):
            fail("current Champion record must state rank-pointer-only semantics", errors)
        if "Champion status grants no research priority" not in state_text:
            fail("current state must prevent Champion from anchoring work selection", errors)
    except Exception as exc:
        fail(f"champion.json: {exc}", errors)

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
                fail(f"AI-facing meta-commentary or Champion fixation in {rel}: {phrase}", errors)

    for rel, fragments in EFFICIENCY_REQUIREMENTS.items():
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        for fragment in fragments:
            if fragment.lower() not in text:
                fail(f"missing efficiency or Champion rule in {rel}: {fragment}", errors)

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
