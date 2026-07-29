# Validation

- New York windows use `America/New_York` with DST-aware wall-clock conversion.
- Prior range ends before the window.
- Internal pivot must be fully right-confirmed before the raid.
- Order activates after fixed 500 ms.
- Unfilled order expires at window end; filled position has no time exit.
- Same-minute stop/target is adverse stop-first.
- Exact signed Bybit funding and one global slot are applied.
- 2021 fit / 2022 forward; 2023 and official 2024-2026 remain unopened.
- Focused DST and pivot-availability tests: 2 passed.
- Strongest programization objections were rerun: FVG-invalidating exit removed; nearest still-unconsumed internal liquidity added as a competing target.
