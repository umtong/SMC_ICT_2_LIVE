from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from common import ROOT

MANIFEST_PATH = ROOT / "bootstrap/template-manifest.toml"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError("project name does not contain a usable slug")
    return slug


def normalize_repo(value: str) -> str:
    raw = value.strip().rstrip("/")
    if raw.startswith("git@github.com:"):
        raw = raw.split(":", 1)[1]
    elif "://" in raw:
        parsed = urlparse(raw)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise ValueError("GitHub repository URL must use github.com")
        raw = parsed.path.strip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", raw):
        raise ValueError("GitHub repository must be owner/name or a github.com repository URL")
    return raw


def parse_drive_id(value: str) -> str | None:
    raw = value.strip()
    for pattern in [
        r"/folders/([A-Za-z0-9_-]+)",
        r"[?&]id=([A-Za-z0-9_-]+)",
        r"^([A-Za-z0-9_-]{10,})$",
    ]:
        match = re.search(pattern, raw)
        if match:
            return match.group(1)
    return None


def git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unresolved"


def copy_entry(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(
            source,
            destination,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "dist"),
        )
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def render_text(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    unresolved = sorted(set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", text)))
    if unresolved:
        raise ValueError(f"unresolved template variables: {', '.join(unresolved)}")
    return text


def write_rendered(template: Path, destination: Path, values: dict[str, str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_text(template.read_text(encoding="utf-8"), values), encoding="utf-8")


def ensure_output(output: Path, allow_existing: bool) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if list(output.iterdir()) and not allow_existing:
        raise ValueError(f"output directory is not empty: {output}; pass --allow-existing to merge")


def local_binding(values: dict[str, str]) -> str:
    return (
        "# Private local binding. This file is ignored by Git.\n"
        "[google_drive]\n"
        f'root_folder_url = "{values["DRIVE_ROOT_URL"]}"\n'
        f'root_folder_id = "{values["DRIVE_ROOT_ID"]}"\n'
        f'root_folder_name = "{values["DRIVE_ROOT_NAME"]}"\n'
    )


def validate_target(output: Path, commands: list[str]) -> None:
    for command in commands:
        completed = subprocess.run(command, cwd=output, shell=True, text=True)
        if completed.returncode != 0:
            raise SystemExit(f"validation failed: {command}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Instantiate a fresh SMC/ICT research project from the reusable template")
    p.add_argument("--github-repository", required=True)
    p.add_argument("--drive-root-url", required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--project-name")
    p.add_argument("--project-id")
    p.add_argument("--drive-root-name")
    p.add_argument("--template-source-ref")
    p.add_argument("--allow-existing", action="store_true")
    p.add_argument("--skip-validation", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    manifest = tomllib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    repository = normalize_repo(args.github_repository)
    repo_name = repository.split("/", 1)[1]
    project_name = args.project_name or repo_name
    project_id = args.project_id or slugify(project_name)
    drive_id = parse_drive_id(args.drive_root_url) or "UNRESOLVED_BY_LOCAL_SCRIPT"
    drive_name = args.drive_root_name or project_name
    now = datetime.now().astimezone()
    template_ref = args.template_source_ref or git_head(ROOT)

    values = {
        "PROJECT_NAME": project_name,
        "PROJECT_ID": project_id,
        "GITHUB_REPOSITORY": repository,
        "DRIVE_ROOT_URL": args.drive_root_url.strip(),
        "DRIVE_ROOT_ID": drive_id,
        "DRIVE_ROOT_NAME": drive_name,
        "TEMPLATE_SOURCE_REPOSITORY": manifest["source_repository"],
        "TEMPLATE_SOURCE_REF": template_ref,
        "TEMPLATE_VERSION": manifest["template_version"],
        "INITIALIZED_AT": now.isoformat(timespec="seconds"),
        "INITIALIZED_DATE": now.date().isoformat(),
    }

    output = args.output.resolve()
    ensure_output(output, args.allow_existing)

    for rel in manifest["copy"]["required_paths"]:
        source = ROOT / rel
        if not source.exists():
            raise FileNotFoundError(f"required template path missing: {rel}")
        copy_entry(source, output / rel)
    for rel in manifest["copy"].get("optional_paths", []):
        source = ROOT / rel
        if source.exists():
            copy_entry(source, output / rel)

    for item in manifest["render"]:
        write_rendered(ROOT / item["template"], output / item["destination"], values)

    for rel in manifest["reset"]["empty_jsonl_paths"]:
        path = output / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for rel in manifest["reset"]["marker_paths"]:
        path = output / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    local_path = output / "config/project.local.toml"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(local_binding(values), encoding="utf-8")

    instantiation = {
        "schema_version": 1,
        "template_version": manifest["template_version"],
        "template_source_repository": manifest["source_repository"],
        "template_source_ref": template_ref,
        "target_github_repository": repository,
        "project_id": project_id,
        "project_name": project_name,
        "initialized_at": values["INITIALIZED_AT"],
        "initial_revision": manifest["completion"]["initial_revision"],
        "initial_ranking_status": manifest["completion"]["initial_ranking_status"],
        "inherited_state": false
    }
    report_path = output / "bootstrap/instantiation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(instantiation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.skip_validation:
        validate_target(output, manifest["completion"]["validate_commands"])

    print(json.dumps(instantiation, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
