from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from common import ROOT

HOT = [
    "instructions/project-instructions.md",
    "config/project.toml",
    "config/evaluation.toml",
    "config/workers.toml",
    "control/current-state.md",
    "control/champion.json",
    "control/work-claims.csv",
    "control/result-registry.jsonl",
    "control/validation-cache.jsonl",
    "data/README.md",
    "prompts/goal-worker.md",
]


def main() -> int:
    out = ROOT / "dist/context"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    manifest = []
    for rel in HOT:
        src = ROOT / rel
        dst = out / Path(rel).name
        shutil.copy2(src, dst)
        manifest.append({
            "source": rel,
            "file": dst.name,
            "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        })
    (ROOT / "dist/context-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"built {len(manifest)} hot-context files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
