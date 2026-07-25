import json
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_bootstrap_manifest_has_only_two_required_inputs():
    manifest = tomllib.loads((ROOT / "bootstrap/template-manifest.toml").read_text(encoding="utf-8"))
    assert manifest["required_inputs"] == ["target_github_repository", "target_google_drive_root"]
    assert manifest["completion"]["initial_revision"] == 1
    assert manifest["completion"]["initial_ranking_status"] == "EMPTY"
    assert manifest["completion"]["inherit_strategy_results"] is False
    assert manifest["completion"]["inherit_ranking"] is False
    assert manifest["completion"]["inherit_sources"] is False


def test_drive_blueprint_has_required_control_and_registry_surfaces():
    blueprint = json.loads((ROOT / "bootstrap/drive-blueprint.json").read_text(encoding="utf-8"))
    folders = set(blueprint["folders"])
    assert {"00_CONTROL", "01_RUNS", "02_DATA/00_INBOX", "03_RESEARCH", "04_ARTIFACTS", "05_SNAPSHOTS", "90_ARCHIVE"}.issubset(folders)
    document_paths = {row["path"] for row in blueprint["documents"]}
    assert {"00_START_HERE", "00_CONTROL/00_PROJECT_BINDING", "00_CONTROL/01_PROJECT_STATE", "00_CONTROL/02_STRATEGY_RANKING", "00_CONTROL/06_GOAL_WORKER_PROMPT"}.issubset(document_paths)
    sheet_paths = {row["path"] for row in blueprint["sheets"]}
    assert {"00_CONTROL/03_WORK_CLAIMS", "00_CONTROL/08_RESULT_REGISTRY", "00_CONTROL/09_VALIDATION_CACHE"}.issubset(sheet_paths)


def test_instantiator_creates_fresh_state(tmp_path: Path):
    output = tmp_path / "new-project"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/instantiate_project.py"),
            "--github-repository",
            "example/NEW_RESEARCH_PROJECT",
            "--drive-root-url",
            "https://drive.google.com/drive/folders/DRIVE_TEST_123456789",
            "--output",
            str(output),
            "--skip-validation",
        ],
        cwd=ROOT,
        check=True,
    )

    project = tomllib.loads((output / "config/project.toml").read_text(encoding="utf-8"))
    ranking = json.loads((output / "control/ranking.json").read_text(encoding="utf-8"))
    state = (output / "control/current-state.md").read_text(encoding="utf-8")
    local = (output / "config/project.local.toml").read_text(encoding="utf-8")
    report = json.loads((output / "bootstrap/instantiation.json").read_text(encoding="utf-8"))

    assert project["project"]["name"] == "NEW_RESEARCH_PROJECT"
    assert project["project"]["id"] == "new-research-project"
    assert project["github"]["repository"] == "example/NEW_RESEARCH_PROJECT"
    assert ranking["revision"] == 1
    assert ranking["status"] == "EMPTY"
    assert ranking["first_place"] is None
    assert ranking["ranked_candidates"] == []
    assert "- revision: 1" in state
    assert "current first place: none" in state
    assert "DRIVE_TEST_123456789" in local
    assert report["inherited_state"] is False
    for rel in [
        "control/result-registry.jsonl",
        "control/validation-cache.jsonl",
        "data/catalog/source-registry.jsonl",
        "data/catalog/dataset-registry.jsonl",
        "data/catalog/entity-registry.jsonl",
    ]:
        assert (output / rel).read_text(encoding="utf-8") == ""
