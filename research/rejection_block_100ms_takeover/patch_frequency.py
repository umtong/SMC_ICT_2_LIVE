from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path

REPLACEMENTS = (
    ("    expected = bar_seconds * 2\n", "    expected = bar_seconds * 10\n"),
    (
        "        if len(times) > 1 and not np.all(np.diff(times) == 500_000):\n",
        "        if len(times) > 1 and not np.all(np.diff(times) == 100_000):\n",
    ),
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--diff", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    before = args.source.read_text(encoding="utf-8")
    after = before
    counts: list[dict[str, object]] = []
    for old, new in REPLACEMENTS:
        old_count = after.count(old)
        new_count_before = after.count(new)
        if old_count != 1 or new_count_before != 0:
            raise SystemExit(
                f"fail-closed cadence patch mismatch: old={old!r} count={old_count}, "
                f"new_count_before={new_count_before}"
            )
        after = after.replace(old, new, 1)
        counts.append(
            {
                "old": old.rstrip("\n"),
                "new": new.rstrip("\n"),
                "old_count_before": old_count,
                "new_count_before": new_count_before,
            }
        )

    for old, new in REPLACEMENTS:
        if after.count(old) != 0 or after.count(new) != 1:
            raise SystemExit("post-patch cadence assertion failed")

    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{args.source}.archived_500ms_assumption",
            tofile=f"{args.source}.exact_100ms_source",
        )
    )
    removed = [line for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]
    added = [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    if len(removed) != 2 or len(added) != 2 or "@@" not in diff:
        raise SystemExit(f"unexpected cadence diff structure: {diff!r}")
    if {line[1:] + "\n" for line in removed} != {old for old, _ in REPLACEMENTS}:
        raise SystemExit("diff removed unexpected source lines")
    if {line[1:] + "\n" for line in added} != {new for _, new in REPLACEMENTS}:
        raise SystemExit("diff added unexpected source lines")

    before_bytes = before.encode("utf-8")
    after_bytes = after.encode("utf-8")
    args.source.write_text(after, encoding="utf-8")
    args.diff.parent.mkdir(parents=True, exist_ok=True)
    args.diff.write_text(diff, encoding="utf-8")

    result = {
        "status": "PASS_EXACT_TWO_SOURCE_FREQUENCY_REPLACEMENTS",
        "source": str(args.source),
        "before_sha256": sha256_bytes(before_bytes),
        "after_sha256": sha256_bytes(after_bytes),
        "replacement_count": len(REPLACEMENTS),
        "replacements": counts,
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
