from __future__ import annotations

from pathlib import Path
from typing import Any

import run_stablecoin_profit_v5_authority as authority

ROOT = Path(__file__).resolve().parents[1]
GRID_WRAPPER = (
    ROOT
    / "research"
    / "execution"
    / "stablecoin_profit_v5_20260727"
    / "profit_guard_v5_frozen_grid.py"
)
ORIGINAL_RUN = authority.v4auth.run


def frozen_grid_run(command: list[str], *args: Any, **kwargs: Any) -> Any:
    rewritten = list(command)
    if (
        len(rewritten) >= 3
        and Path(rewritten[1]).name == "profit_guard_v5.py"
        and rewritten[2] in {"self-test", "run"}
    ):
        rewritten[1] = str(GRID_WRAPPER)
    return ORIGINAL_RUN(rewritten, *args, **kwargs)


def main() -> int:
    if not GRID_WRAPPER.is_file():
        raise FileNotFoundError(GRID_WRAPPER)
    authority.v4auth.run = frozen_grid_run
    return authority.main()


if __name__ == "__main__":
    raise SystemExit(main())
