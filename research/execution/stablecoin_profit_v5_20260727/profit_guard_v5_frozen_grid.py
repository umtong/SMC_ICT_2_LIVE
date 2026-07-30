from __future__ import annotations

import profit_guard_v5 as v5

# Correction 005 explicitly freezes the registered risk/notional grid.
# Keep every original value from the strict causal base; do not substitute
# adjacent values or remove intermediate caps before seeing any outcome.
FROZEN_RISKS = (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.30, 0.60)
FROZEN_CAPS = (1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 35.0, 50.0, 75.0, 100.0)


def main() -> int:
    v5.RISKS = FROZEN_RISKS
    v5.CAPS = FROZEN_CAPS
    assert len(v5.RISKS) * len(v5.CAPS) == 99
    return v5.main()


if __name__ == "__main__":
    raise SystemExit(main())
