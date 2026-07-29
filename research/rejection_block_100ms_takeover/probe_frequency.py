from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

KEY_PATTERNS = (
    r"bar_seconds",
    r"500_?000",
    r"100_?000",
    r"spacing",
    r"cadence",
    r"np\.diff",
    r"\.diff\(",
    r"arange",
    r"date_range",
    r"timedelta",
    r"source_state",
)


def inspect_file(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, object]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in KEY_PATTERNS):
            rows.append({"line": lineno, "text": line})
    return {
        "path": str(path),
        "bytes": len(text.encode("utf-8")),
        "matches": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    targets = [args.source_dir / "run_screen.py", args.source_dir / "test_run_screen.py"]
    missing = [str(path) for path in targets if not path.is_file()]
    if missing:
        raise SystemExit(f"missing reconstructed sources: {missing}")

    payload = {
        "status": "PROBE_ONLY_NO_MARKET_OUTCOME",
        "targets": [inspect_file(path) for path in targets],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
