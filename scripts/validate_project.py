from __future__ import annotations

import csv
import json
import re
import subprocess
import tomllib
from pathlib import Path

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
    "bootstrap/template-manifest.toml",
    "bootstrap/drive-blueprint.json",
    "bootstrap/bootstrap-contract.md",
    "prompts/bootstrap-new-project.md",
    "scripts/instantiate_project.py",
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
    "docs/reusable-bootstrap.md",
    "bootstrap/bootstrap-contract.md",
    "prompts/bootstrap-new-project.md",
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


def is_git_tracked(path: Path) -> bool:
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--error-unmatch", str(path.relative_to(ROOT))],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return completed.returncode == 0
    except (FileNotFoundError, ValueError):
        return False


def validate_ranking(ranking: dict, state_text: str, errors: list[str]) -> None:
    if ranking.get("schema_version") != 1:
        fail("ranking schema_version", errors)
    match = re.search(r"(?m)^- revision:\s*(\d+)\s*$", state_text)
    if not match:
        fail("current state revision missing", errors)
        return
    if ranking.get("revision") != int(match.group(1)):
        fail("ranking revision does not match current state", errors)

    status = ranking.get("status")
    first = ranking.get("first_place")
    ranked = ranking.get("ranked_candidates", [])
    if status == "EMPTY":
        if first is not None:
            fail("EMPTY ranking must have first_place=null", errors)
        if ranked:
            fail("EMPTY ranking must have no ranked candidates", errors)
        if "current first place: none" not in state_text.lower():
            fail("EMPTY state must explicitly record no first place", errors)
    elif status == "ACTIVE":
        if not isinstance(first, dict) or first.get("rank") != 1:
            fail("ACTIVE ranking must contain first place", errors)
        metrics = first.get("metrics", {}) if isinstance(first, dict) else {}
        if metrics.get("target_geometric_daily_growth") != 0.01:
            fail("first-place target must remain 1%", errors)
        expected_gap = metrics.get("target_geometric_daily_growth", 0) - metrics.get("geometric_daily_growth", 0)
        if abs(metrics.get("target_gap", -999) - expected_gap) > 1e-12:
            fail("first-place target gap is inconsistent", errors)
        ranks = [row.get("rank") for row in ranked]
        gaps = [row.get("target_gap") for row in ranked]
        if ranks != sorted(ranks):
            fail("ranked candidates must be ordered by rank", errors)
        if gaps != sorted(gaps):
            fail("ranked candidates must primarily follow target gap", errors)
    else:
        fail("ranking status must be EMPTY or ACTIVE", errors)

    if not ranking.get("ranking_rule", {}).get("rank_does_not_determine_work_priority"):
        fail("rank must not anchor work selection", errors)
    if "Rank does not determine research priority" not in state_text:
        fail("current state must prevent rank from anchoring work selection", errors)


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

    for rel in ["config/evaluation.toml", "config/storage.toml", "config/workers.toml", "bootstrap/template-manifest.toml"]:
        try:
            tomllib.loads((ROOT / rel).read_text(encoding="utf-8"))
        except Exception as exc:
            fail(f"{rel}: {exc}", errors)

    try:
        blueprint = json.loads((ROOT / "bootstrap/drive-blueprint.json").read_text(encoding="utf-8"))
        if blueprint.get("schema_version") != 1:
            fail("drive blueprint schema_version", errors)
        if "00_CONTROL" not in blueprint.get("folders", []):
            fail("drive blueprint missing 00_CONTROL", errors)
    except Exception as exc:
        fail(f"drive blueprint: {exc}", errors)

    try:
        evaluation = tomllib.loads((ROOT / "config/evaluation.toml").read_text(encoding="utf-8"))
        if evaluation.get("validation", {}).get("mode") != "staged":
            fail("evaluation validation mode must be staged", errors)
        if not evaluation.get("validation", {}).get("depth_proportional_to_economic_promise_and_decision_value"):
            fail("validation depth must follow economic promise and decision value", errors)
        for stage in ["initial", "promising", "deep_validation"]:
            if not evaluation.get("stage", {}).get(stage, {}).get("required"):
                fail(f"evaluation stage missing requirements: {stage}", errors)
        ranking_policy = evaluation.get("ranking", {})
        if ranking_policy.get("primary_target") != 0.01:
            fail("ranking target must remain 1%", errors)
        if ranking_policy.get("rank_grants_research_priority") is not False:
            fail("rank must not grant research priority", errors)
    except Exception as exc:
        fail(f"evaluation.toml: {exc}", errors)

    try:
        workers = tomllib.loads((ROOT / "config/workers.toml").read_text(encoding="utf-8"))
        if workers["work"].get("state_update_protocol") != "optimistic_revision":
            fail("unexpected work state_update_protocol", errors)
        if not workers["work"].get("claim_required_for_costly_or_reusable_work"):
            fail("costly/reusable work must use claims", errors)
        if not workers["lookup"].get("targeted_related_records_only"):
            fail("lookup must be targeted to the intended scope", errors)
        if workers["lookup"].get("full_registry_scan_by_default") is not False:
            fail("full registry scan must not be the default", errors)
        if workers["validation"].get("mode") != "staged":
            fail("validation must be staged", errors)
    except Exception as exc:
        fail(f"workers.toml: {exc}", errors)

    try:
        ranking = json.loads((ROOT / "control/ranking.json").read_text(encoding="utf-8"))
        state_text = (ROOT / "control/current-state.md").read_text(encoding="utf-8")
        validate_ranking(ranking, state_text, errors)
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
            header = set(reader.fieldnames or [])
            claims = list(reader)
        required_claim_columns = {"claim_id", "worker_id", "scope_fingerprint", "base_revision", "status", "lease_until"}
        if not required_claim_columns.issubset(header):
            fail("work-claims header", errors)
        unique([row.get("claim_id", "") for row in claims], "claim_id", errors)
    except Exception as exc:
        fail(f"work claims: {exc}", errors)

    try:
        results = read_jsonl(ROOT / "control/result-registry.jsonl")
        unique([str(row.get("result_id", "")) for row in results], "result_id", errors)
    except Exception as exc:
        fail(f"result registry: {exc}", errors)

    try:
        attestations = read_jsonl(ROOT / "control/validation-cache.jsonl")
        unique([str(row.get("attestation_id", "")) for row in attestations], "attestation_id", errors)
    except Exception as exc:
        fail(f"validation cache: {exc}", errors)

    for rel in AI_FACING_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_RUNTIME_PHRASES:
            if phrase.lower() in text:
                fail(f"AI-facing meta-commentary or legacy terminology in {rel}: {phrase}", errors)

    for rel, fragments in EFFICIENCY_REQUIREMENTS.items():
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        for fragment in fragments:
            if fragment.lower() not in text:
                fail(f"missing efficiency or ranking rule in {rel}: {fragment}", errors)

    local_binding = ROOT / "config/project.local.toml"
    if local_binding.exists() and is_git_tracked(local_binding):
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
