#!/usr/bin/env python3
"""Fix the GitHub step-output path in the frontend content workflow."""

from pathlib import Path

TARGET = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "yt-trinity-public-frontend-content.yml"
text = TARGET.read_text(encoding="utf-8")
old_import = "          import json\n          from pathlib import Path\n          candidates = []"
new_import = "          import json\n          import os\n          from pathlib import Path\n          candidates = []"
old_open = "          with open('${GITHUB_OUTPUT}', 'a', encoding='utf-8') as handle:"
new_open = "          with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as handle:"
changed = False
if new_import not in text:
    if old_import not in text:
        raise SystemExit("prepare import anchor missing")
    text = text.replace(old_import, new_import, 1)
    changed = True
if new_open not in text:
    if old_open not in text:
        raise SystemExit("GITHUB_OUTPUT anchor missing")
    text = text.replace(old_open, new_open, 1)
    changed = True
if changed:
    TARGET.write_text(text, encoding="utf-8")
    print("frontend content output fix applied")
else:
    print("frontend content output fix already present")
