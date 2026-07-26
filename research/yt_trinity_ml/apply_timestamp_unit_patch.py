#!/usr/bin/env python3
"""One-shot branch migration for pandas 3 DatetimeIndex unit compatibility."""

from __future__ import annotations

from pathlib import Path


REPLACEMENTS = {
    Path("research/yt_trinity_ml/system/coarse.py"): (
        (
            "self.time_ns = self.times.asi8",
            'self.time_ns = self.times.as_unit("ns").asi8',
        ),
    ),
    Path("research/yt_trinity_ml/system/event_tape.py"): (
        (
            "self.time_ns = {symbol: frame.index.asi8 for symbol, frame in self.tapes.items()}",
            'self.time_ns = {symbol: frame.index.as_unit("ns").asi8 for symbol, frame in self.tapes.items()}',
        ),
    ),
}


def main() -> int:
    changed = 0
    for path, replacements in REPLACEMENTS.items():
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in replacements:
            old_count = text.count(old)
            new_count = text.count(new)
            if old_count == 1 and new_count == 0:
                text = text.replace(old, new)
            elif old_count == 0 and new_count == 1:
                continue
            else:
                raise RuntimeError(
                    f"unexpected replacement state for {path}: old={old_count}, new={new_count}"
                )
        if text != original:
            path.write_text(text, encoding="utf-8", newline="\n")
            changed += 1
    print(f"timestamp-unit files changed: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
