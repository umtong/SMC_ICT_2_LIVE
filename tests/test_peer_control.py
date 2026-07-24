import csv
import tomllib
from pathlib import Path

from scripts.common import read_jsonl

ROOT = Path(__file__).parents[1]


def test_peer_parallel_mode_has_no_mandatory_coordinator():
    project = tomllib.loads((ROOT / "config/project.toml").read_text(encoding="utf-8"))
    workers = tomllib.loads((ROOT / "config/workers.toml").read_text(encoding="utf-8"))
    assert project["chatgpt"]["execution_mode"] == "continuous_peer_parallel"
    assert project["chatgpt"]["central_coordinator_required"] is False
    assert workers["concurrency"]["fixed_sequence"] is False
    assert workers["concurrency"]["central_coordinator_required"] is False


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
    assert read_jsonl(ROOT / "control/result-registry.jsonl") == []
    assert read_jsonl(ROOT / "control/validation-cache.jsonl") == []
