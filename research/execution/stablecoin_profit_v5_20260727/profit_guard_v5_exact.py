from __future__ import annotations

import profit_guard_v5 as v5

# Preserve the preregistered risk/notional domain exactly. The profit-first
# correction changes only advancement semantics, never the search values.
v5.RISKS = (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.30, 0.60)
v5.CAPS = (1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 35.0, 50.0, 75.0, 100.0)


def self_test() -> None:
    assert len(v5.RISKS) == 9
    assert len(v5.CAPS) == 11
    assert len(v5.RISKS) * len(v5.CAPS) == 99
    assert max(v5.RISKS) == 0.60
    assert max(v5.CAPS) == 100.0
    v5.self_test()
    print("stablecoin exact-grid profit-first V5 self-test passed")


def main() -> int:
    args = v5.parse_args()
    v5._load_correction()
    v5.v4._load_correction()
    v5.v4._patch()
    if args.command == "self-test":
        self_test()
        return 0
    outcome = v5.run_profit_first(args)
    print(v5.json.dumps(outcome["guards"], indent=2, sort_keys=True))
    return (
        0
        if outcome["result"].get("status")
        == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
