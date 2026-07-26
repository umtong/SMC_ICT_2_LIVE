from __future__ import annotations

# Stable public entry point retained for the existing workflow and tests.
# The authoritative implementation is strict_guard.py.
import strict_guard as engine
from strict_guard import (  # noqa: F401
    CLAIM_ID,
    CORRECTION_ID,
    ENGINE,
    audit_result,
    main,
    run,
    self_test,
    strict_build_rows,
    strict_trade_from_row,
)

if __name__ == "__main__":
    raise SystemExit(main())
