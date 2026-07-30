# Cross-sectional perpetual basis allocation Core fatal screen

## Decision

`RES-20260730-XSEC-PERP-BASIS-ALLOCATION-CORE-001` is `RETIRED_PRE2024_CROSS_SECTIONAL_BASIS_ALLOCATION_FAILURE`.

This study tested the literature-supported cross-sectional direction—long the relatively highest completed prior-day perpetual/index basis and short the relatively lowest—rather than the already-retired absolute three-sigma basis fade. All routes used one common four-asset policy, fixed 500 ms execution, actual funding, one global slot, 0.5% planned NAV loss, 3x cap and no elapsed-time exit.

Common complete basis days were 78 in the partial 2021 four-asset history, 365 in 2022 and 365 in 2023.

## 24-bp results

| Route | 2022 multiple | entries | PF | median | H1 | H2 | winner-reroute | 2023 multiple | entries | PF | median | H1 | H2 | winner-reroute |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LONG_HIGH_BASIS | 0.629848x | 248 | 0.438 | -0.4995% | -23.22% | -17.97% | 0.573406x | 1.226876x | 182 | 1.242 | -0.4585% | 1.95% | 20.34% | 0.917670x |
| SHORT_LOW_BASIS | 0.890080x | 222 | 0.812 | -0.4936% | -4.06% | -7.22% | 0.752233x | 0.784711x | 237 | 0.653 | -0.4903% | -13.28% | -9.51% | 0.708852x |
| DOMINANT_BASIS_LEG | 0.780344x | 271 | 0.674 | -0.3620% | -9.42% | -13.85% | 0.695064x | 0.886025x | 247 | 0.836 | -0.4931% | -6.91% | -4.82% | 0.702778x |

No fixed route survived the 2022 gate at both 18 and 24 bp. `LONG_HIGH_BASIS` became positive in 2023, but its median trade remained near the full planned loss and exact top-five deletion/full rerouting fell below one even at 12 bp. It therefore represents a regime-specific, winner-dependent diagnostic rather than Core.

ML, price-volume admission, risk/leverage research and official 2024-2026 remained closed.

## Programization audit

A preliminary run applied all funding events in a daily processing chunk before locating an earlier hard-stop timestamp. That could charge or credit funding after the position had already exited. Every preliminary output was invalidated. The corrected engine first determines the actual stop/state-exit minute and applies only funding strictly before that observed exit. Two corrected fresh-process runs produced byte-identical JSON and deterministic gzip ledgers.

An impossible no-hard-stop diagnostic separated lifecycle implementation from factor economics. At 24 bp:

- `LONG_HIGH_BASIS`: 0.527484x in 2022 and 1.412389x in 2023;
- `SHORT_LOW_BASIS`: 1.137911x in 2022 and 0.783804x in 2023;
- `DOMINANT_BASIS_LEG`: 0.645913x in 2022 and 0.588503x in 2023.

The hard stop impaired the 2022 short-low path, but removing it did not create a stable common mechanism. The profitable leg reversed across years. This is an economic regime-instability failure after a real implementation correction, not merely a bad stop implementation.

## Consequence

Do not rescue this family with another basis average, normalization, rebalance clock, threshold, side subset, stop, target, price-volume filter, cost, risk, leverage or ML model. A paper-level cross-sectional association is insufficient when the allowed one-slot account has negative medians, cross-year sign reversal and winner-removal collapse.

No credentials, paper orders, testnet orders or live orders were used.
