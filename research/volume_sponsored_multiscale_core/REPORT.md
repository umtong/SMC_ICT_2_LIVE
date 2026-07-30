# Volume-sponsored Core scale-invariance extension

- Claim: `CLM-20260730-VOLUME-SPONSORED-MULTISCALE-CORE-001`
- Result: `RES-20260730-VOLUME-SPONSORED-MULTISCALE-CORE-001`
- Status: `RETIRED_SHORTER_SCALE_EXTENSION_ECONOMIC_FAILURE_60M_CORE_RETAINED`
- Official 2024–2026 extension: unopened
- Ranking: unchanged
- Credentials/orders: none

## Programization audit

The initial 15m→30m aggregation used a Python group loop and timed out before a decision. It was replaced with an exact vectorized UTC-pair aggregation. A first economic run was then quarantined because it reproduced 214 official 60m trades instead of the already-audited 121: it had omitted the frozen `funding_z90_signed <= 2021 q75` less-crowded state and the causal expanding adverse-funding q95 sizing reserve. Those omissions were corrected before any shorter-scale result was accepted.

The corrected 60m 2022 path reproduces the existing low-risk Core closely: 52 completed trades, 1.09198x NAV, PF 1.8246, median +0.5630%, MDD 3.66%, exact winner-deletion/rerouting 1.07024x.

## Corrected 2022 independent scale economics at 24bp

| Scale | Trades | NAV multiple | PF | Median | MDD | Winner-removed |
|---|---:|---:|---:|---:|---:|---:|
| 60m | 52 | 1.09198x | 1.8246 | +0.5630% | 3.66% | 1.07024x |
| 30m | 109 | 0.98702x | 0.9563 | −0.4547% | 7.54% | 0.96747x |
| 15m | 244 | 0.90764x | 0.8561 | −0.4837% | 13.57% | 0.84676x |

The shorter scales increased opportunity count but imported negative-median, sub-cost trades. They are not independent Core opportunities. Neither scale was allowed into the global slot, 2023 confirmation did not open for the extension, and official 2024–2026 remained sealed.

## Decision

Retain only the previously established 60m less-crowded `+1.5R` full-realization Core as a weak positive component. Retire 30m and 15m from this information unit. Do not rescue the extension with another bar size, lookback, volume/funding boundary, side subset, R target, stop, cost, risk, leverage, session or ML filter.
