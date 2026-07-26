from __future__ import annotations

from pathlib import Path

import run_stablecoin_profit_v5_authority as authority

ORIGINAL_RUN = authority.v4auth.run
EXACT_ENTRY_NAME = "profit_guard_v5_exact.py"


def exact_grid_run(command: list[str], **kwargs):
    rewritten: list[str] = []
    for argument in command:
        path = Path(argument)
        if path.name == "profit_guard_v5.py":
            rewritten.append(str(path.with_name(EXACT_ENTRY_NAME)))
        else:
            rewritten.append(argument)
    return ORIGINAL_RUN(rewritten, **kwargs)


def main() -> int:
    # The profit-first authority remains unchanged except that every compile,
    # self-test and economic invocation enters through the exact 9x11 grid
    # adapter. This preserves the preregistered risk/notional domain.
    authority.v4auth.run = exact_grid_run
    return authority.main()


if __name__ == "__main__":
    raise SystemExit(main())
