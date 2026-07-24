from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from common import ROOT


def main() -> int:
    p = argparse.ArgumentParser(description="Create an append-only run report stub")
    p.add_argument("--epoch", required=True)
    p.add_argument("--lane", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--base-revision", required=True, type=int)
    args = p.parse_args()
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%z")
    name = f"RUN__{args.epoch}__{args.lane}__{args.task}__{stamp}.md"
    destination = ROOT / "runs" / args.epoch / args.lane / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    template = (ROOT / "templates/run-report.md").read_text(encoding="utf-8")
    template = template.replace("RUN__E000__LANE__TASK__YYYYMMDD-HHMM-KST", name.removesuffix(".md"))
    template = template.replace("- epoch_id:", f"- epoch_id: {args.epoch}")
    template = template.replace("- lane_id:", f"- lane_id: {args.lane}")
    template = template.replace("- task_id:", f"- task_id: {args.task}")
    template = template.replace("- base_revision:", f"- base_revision: {args.base_revision}")
    destination.write_text(template, encoding="utf-8")
    print(destination.relative_to(ROOT))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
