from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import ROOT


def replace(path: Path, substitutions: dict[str, str]) -> None:
    text=path.read_text(encoding="utf-8")
    for old,new in substitutions.items(): text=text.replace(old,new)
    path.write_text(text,encoding="utf-8")


def main() -> int:
    p=argparse.ArgumentParser(description="Rewrite project-specific bindings after copying this harness")
    p.add_argument("--project-id",required=True)
    p.add_argument("--project-name",required=True)
    p.add_argument("--github-repository",required=True)
    p.add_argument("--drive-root-name",required=True)
    args=p.parse_args()
    if not re.fullmatch(r"[^/]+/[^/]+",args.github_repository):
        raise SystemExit("--github-repository must be owner/name")
    substitutions={
        'id = "smc-ict-2-live"':f'id = "{args.project_id}"',
        'name = "SMC_ICT_2_LIVE"':f'name = "{args.project_name}"',
        'repository = "umtong/SMC_ICT_2_LIVE"':f'repository = "{args.github_repository}"',
        'root_folder_name = "SMC_ICT_2_LIVE"':f'root_folder_name = "{args.drive_root_name}"',
    }
    replace(ROOT/"config/project.toml",substitutions)
    print("updated config/project.toml; now create config/project.local.toml with the private Drive ID")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
