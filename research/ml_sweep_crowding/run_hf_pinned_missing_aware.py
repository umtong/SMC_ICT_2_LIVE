"""Execute the sealed pinned-source route with correction 006 only."""
from __future__ import annotations

from . import run_hf_pinned as base
from .strategy_missing_aware import build_candidates_for_symbol

# The pinned price, funding and metric loaders are already bound by
# run_hf_pinned. Replace only the incompatible complete-case event gate.
base.sealed_run.build_candidates_for_symbol = build_candidates_for_symbol


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
