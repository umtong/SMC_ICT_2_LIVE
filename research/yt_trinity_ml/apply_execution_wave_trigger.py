#!/usr/bin/env python3
"""Attach one common trigger to the latest-head discovery and base alpha workflows."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = ROOT / ".github/workflows"
TRIGGER_RELATIVE = "control/yt-trinity-execution-wave-trigger.json"
TARGET_MARKERS = (
    "run_cisd_bpr_ifvg_research.py",
    "run_compression_bpr_continuation.py",
    "run_smt_cisd_research.py",
    "discover_event_tape_sources.py",
    "YT Trinity research integrity",
)


def add_path(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if TRIGGER_RELATIVE in text:
        return False
    if not any(marker in text for marker in TARGET_MARKERS):
        return False
    anchor = "    paths:\n"
    if anchor not in text:
        return False
    text = text.replace(
        anchor,
        anchor + f"      - {TRIGGER_RELATIVE}\n",
        1,
    )
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    changed = []
    for path in sorted(WORKFLOW_ROOT.glob("yt-trinity-*.yml")):
        if add_path(path):
            changed.append(str(path.relative_to(ROOT)))
    if len(changed) < 4:
        raise RuntimeError(f"too few latest-head workflows were linked: {changed}")
    trigger = ROOT / TRIGGER_RELATIVE
    trigger.parent.mkdir(parents=True, exist_ok=True)
    trigger.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
                "trigger_id": "LATEST-HEAD-EXECUTION-WAVE-20260727-01",
                "purpose": "Re-run base independent alphas, causal integrity, and event-tape source discovery on the fully integrated latest branch head.",
                "linked_workflows": changed,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"changed": changed}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
