from __future__ import annotations

import argparse
from datetime import datetime

from common import ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an append-only peer worker Run Report stub")
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--claim-id", required=True)
    parser.add_argument("--base-revision", required=True, type=int)
    args = parser.parse_args()

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%z")
    name = f"RUN__{args.worker_id}__{args.claim_id}__{stamp}.md"
    destination = ROOT / "runs" / args.worker_id / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    template = (ROOT / "templates/run-report.md").read_text(encoding="utf-8")
    template = template.replace("RUN__WORKER__CLAIM__YYYYMMDD-HHMM-KST", name.removesuffix(".md"))
    template = template.replace("- worker_id:", f"- worker_id: {args.worker_id}")
    template = template.replace("- claim_id:", f"- claim_id: {args.claim_id}")
    template = template.replace("- base_revision:", f"- base_revision: {args.base_revision}")
    destination.write_text(template, encoding="utf-8")
    print(destination.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
