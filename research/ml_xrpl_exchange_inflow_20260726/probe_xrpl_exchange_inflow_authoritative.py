from __future__ import annotations

import probe_xrpl_exchange_inflow as base

# Publicly labeled exchange-owned consolidation counterparties observed before any
# Bybit market outcome was opened. They are exclusion-only: no additional
# destination account is queried and no source-density threshold is relaxed.
KNOWN_INTERNAL_EXCLUSION_ACCOUNTS = frozenset(
    {
        # Binance consolidation/hot wallet counterparty.
        "rDAE53VfMvftPB4ogpWGWvzkQxfht6JPxr",
        # Bybit consolidation/hot wallet counterparty.
        "raQxZLtqurEXvH5sgijrif7yXMNwvFRkJN",
    }
)

base.FROZEN_ACCOUNTS = frozenset(
    set(base.FROZEN_ACCOUNTS) | set(KNOWN_INTERNAL_EXCLUSION_ACCOUNTS)
)


def self_test() -> None:
    if not KNOWN_INTERNAL_EXCLUSION_ACCOUNTS.issubset(base.FROZEN_ACCOUNTS):
        raise AssertionError("known internal exchange accounts are not excluded")
    if len(base.FROZEN_ACCOUNTS) != len(base.WALLETS) + len(KNOWN_INTERNAL_EXCLUSION_ACCOUNTS):
        raise AssertionError("unexpected internal-exclusion cardinality")
    base.self_test()
    print("authoritative internal-transfer exclusion self-test passed")


def main() -> int:
    if "--self-test" in __import__("sys").argv:
        self_test()
        return 0
    # base.main parses the unchanged --output contract and uses the patched
    # FROZEN_ACCOUNTS global at every event-classification decision.
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
