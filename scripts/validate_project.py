from __future__ import annotations

import csv
import json
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
    "schemas/source.schema.json",
    "schemas/run-report.schema.json",
    "schemas/work-claim.schema.json",
    "schemas/result.schema.json",
    "schemas/validation-attestation.schema.json",
]

RUNTIME_FILES = [
    "instructions/project-instructions.md",
    "prompts/goal-worker.md",
    "prompts/reconcile-state.md",
    "AGENTS.md",
    "control/current-state.md",
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
]


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

    for rel in RUNTIME_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_RUNTIME_PHRASES:
            if phrase.lower() in text:
                fail(f"runtime meta-commentary in {rel}: {phrase}", errors)

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
