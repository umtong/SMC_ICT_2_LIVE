from __future__ import annotations

import csv
import json
import re
import tomllib
from pathlib import Path

from common import ROOT, read_jsonl

REQUIRED = [
    "README.md",
    "AGENTS.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/work-claim.yml",
    "config/project.toml",
    "config/evaluation.toml",
    "config/storage.toml",
    "config/workers.toml",
    "config/folder-contract.github.toml",
    "config/folder-contract.drive.toml",
    "config/action-contract.toml",
    "instructions/project-instructions.md",
    "docs/folder-action-contract.md",
    "control/current-state.md",
    "control/champion.json",
    "control/work-claims.csv",
    "control/result-registry.jsonl",
    "control/validation-cache.jsonl",
    "data/catalog/source-registry.jsonl",
    "data/catalog/dataset-registry.jsonl",
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
    "AGENTS.md",
    "README.md",
    "config/storage.toml",
    "control/current-state.md",
    "control/decisions.md",
    "control/README.md",
    "data/README.md",
    "runs/README.md",
    "research/hypotheses/README.md",
    "research/experiments/README.md",
    "research/reports/README.md",
    "research/invalidated/README.md",
    "docs/architecture.md",
    "docs/data-retention.md",
    "docs/drive-layout.md",
    "docs/operating-playbook.md",
    "docs/folder-action-contract.md",
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
]

FOLDER_FIELDS = {
    "id",
    "system",
    "path",
    "canonical_role",
    "purpose",
    "inputs",
    "outputs",
    "consumers",
    "use_when",
    "done_when",
    "retention",
    "empty_policy",
    "required",
}
ACTION_FIELDS = {
    "id",
    "purpose",
    "trigger",
    "required_inputs",
    "steps",
    "outputs",
    "done_when",
    "evidence",
}
ALLOWED_EMPTY_POLICIES = {
    "must_not_be_empty",
    "ready_on_demand",
    "prefer_empty",
    "prefer_absent",
}
REQUIRED_ACTIONS = {
    "read_current_context",
    "claim_work",
    "register_source",
    "register_dataset",
    "promote_claim_to_hypothesis",
    "run_experiment",
    "register_result",
    "attest_validation",
    "write_run_report",
    "update_state_or_champion",
    "snapshot_material_state",
    "archive_or_quarantine",
    "build_context_bundle",
}


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def unique(values: list[str], label: str, errors: list[str]) -> None:
    cleaned = [value for value in values if value]
    if len(cleaned) != len(set(cleaned)):
        fail(f"duplicate {label}", errors)


def validate_nonempty_list(value: object, label: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value or not all(str(item).strip() for item in value):
        fail(f"{label} must be a non-empty list", errors)


def validate_folder_action_contract(errors: list[str]) -> None:
    folders: list[dict] = []
    actions: list[dict] = []
    for rel in ["config/folder-contract.github.toml", "config/folder-contract.drive.toml"]:
        try:
            contract = tomllib.loads((ROOT / rel).read_text(encoding="utf-8"))
            folders.extend(contract.get("folder", []))
        except Exception as exc:
            fail(f"folder contract {rel}: {exc}", errors)
    try:
        action_contract = tomllib.loads((ROOT / "config/action-contract.toml").read_text(encoding="utf-8"))
        actions.extend(action_contract.get("action", []))
    except Exception as exc:
        fail(f"action contract: {exc}", errors)
    if not folders:
        fail("folder-action contract has no folders", errors)
    if not actions:
        fail("folder-action contract has no actions", errors)

    unique([str(item.get("id", "")) for item in folders], "folder contract id", errors)
    unique([f"{item.get('system', '')}:{item.get('path', '')}" for item in folders], "folder contract path", errors)
    unique([str(item.get("canonical_role", "")) for item in folders], "folder canonical_role", errors)
    unique([str(item.get("id", "")) for item in actions], "action contract id", errors)

    for index, item in enumerate(folders):
        missing = FOLDER_FIELDS - set(item)
        if missing:
            fail(f"folder[{index}] missing fields: {sorted(missing)}", errors)
            continue
        if item["system"] not in {"github", "drive"}:
            fail(f"folder[{index}] invalid system", errors)
        if item["empty_policy"] not in ALLOWED_EMPTY_POLICIES:
            fail(f"folder[{index}] invalid empty_policy", errors)
        for field in ["inputs", "outputs", "consumers"]:
            validate_nonempty_list(item[field], f"folder[{index}].{field}", errors)
        for field in ["id", "path", "canonical_role", "purpose", "use_when", "done_when", "retention"]:
            if not str(item[field]).strip():
                fail(f"folder[{index}].{field} is empty", errors)
        if not isinstance(item["required"], bool):
            fail(f"folder[{index}].required must be boolean", errors)
        if item["system"] == "github" and item["required"] and not (ROOT / item["path"]).exists():
            fail(f"required GitHub folder missing: {item['path']}", errors)

    action_ids = {str(item.get("id", "")) for item in actions}
    missing_actions = REQUIRED_ACTIONS - action_ids
    if missing_actions:
        fail(f"missing required actions: {sorted(missing_actions)}", errors)
    for index, item in enumerate(actions):
        missing = ACTION_FIELDS - set(item)
        if missing:
            fail(f"action[{index}] missing fields: {sorted(missing)}", errors)
            continue
        for field in ["required_inputs", "steps", "outputs", "evidence"]:
            validate_nonempty_list(item[field], f"action[{index}].{field}", errors)
        for field in ["id", "purpose", "trigger", "done_when"]:
            if not str(item[field]).strip():
                fail(f"action[{index}].{field} is empty", errors)

    hypothesis_paths = [
        item["path"] for item in folders
        if item.get("canonical_role") == "hypothesis_library"
    ]
    if hypothesis_paths != ["03_RESEARCH/10_HYPOTHESES"]:
        fail("canonical hypothesis folder must be exactly 03_RESEARCH/10_HYPOTHESES", errors)

    drive_layout = (ROOT / "docs/drive-layout.md").read_text(encoding="utf-8")
    if "10_YOUTUBE/30_HYPOTHESES" in drive_layout:
        fail("duplicate YouTube hypothesis folder is still documented", errors)

    pr_template = (ROOT / ".github/PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    for marker in [
        "Work Claim",
        "Folder and action contract",
        "Result Registry entry",
        "Validation Cache entry",
        "Run Report",
    ]:
        if marker not in pr_template:
            fail(f"PR template missing contract marker: {marker}", errors)


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
        structure = project.get("structure", {})
        for rel in structure.get("folder_contract_paths", []):
            if not (ROOT / rel).exists():
                fail(f"invalid structure.folder_contract_paths: {rel}", errors)
        for key in ["action_contract_path", "folder_action_document_path", "pr_template_path"]:
            rel = structure.get(key)
            if not rel or not (ROOT / rel).exists():
                fail(f"invalid structure.{key}", errors)
    except Exception as exc:
        fail(f"project.toml: {exc}", errors)

    for rel in [
        "config/evaluation.toml",
        "config/storage.toml",
        "config/workers.toml",
    ]:
        try:
            tomllib.loads((ROOT / rel).read_text(encoding="utf-8"))
        except Exception as exc:
            fail(f"{rel}: {exc}", errors)

    try:
        workers = tomllib.loads((ROOT / "config/workers.toml").read_text(encoding="utf-8"))
        work = workers["work"]
        defaults = workers["defaults"]
        if work.get("state_update_protocol") != "optimistic_revision":
            fail("unexpected work state_update_protocol", errors)
        if not defaults.get("check_active_claims"):
            fail("active work claims must be checked", errors)
        if not defaults.get("reuse_registered_artifacts"):
            fail("registered artifacts must be reused", errors)
    except Exception as exc:
        fail(f"workers.toml: {exc}", errors)

    try:
        champion = json.loads((ROOT / "control/champion.json").read_text(encoding="utf-8"))
        if champion.get("schema_version") != 1:
            fail("champion schema_version", errors)
        state_text = (ROOT / "control/current-state.md").read_text(encoding="utf-8")
        match = re.search(r"(?m)^- revision:\s*(\d+)\s*$", state_text)
        if not match:
            fail("current state revision missing", errors)
        elif champion.get("revision") != int(match.group(1)):
            fail("Champion revision does not match current state", errors)
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

    validate_folder_action_contract(errors)

    for rel in AI_FACING_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_RUNTIME_PHRASES:
            if phrase.lower() in text:
                fail(f"AI-facing meta-commentary in {rel}: {phrase}", errors)

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
