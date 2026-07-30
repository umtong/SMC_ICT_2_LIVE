from __future__ import annotations

"""Transport-only correction for the SQD GMX V1 source gate.

The parent source contract stores frozen windows as ``(start, end)`` tuples,
whereas the first SQD wrapper expected dictionaries.  This adapter changes
only that representation before executing the identical gate.
"""

import argparse
from pathlib import Path

import source_gate as gate


gate.base.PROBE_WINDOWS = tuple(
    {
        "name": f"{start}__{end}",
        "start": start,
        "end": end,
    }
    for start, end in gate.base.PROBE_WINDOWS
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        gate.self_test()
        raise SystemExit(0)
    if args.output is None:
        raise SystemExit("--output is required")
    raise SystemExit(gate.run(args.output))
