# Sequential external-liquidity evidence action policy

**Result:** `RES-20260730-SEQUENTIAL-LIQUIDITY-EVIDENCE-001`  
**Decision:** `RETIRED_2022_SEQUENTIAL_EVIDENCE_SUBCOST_COMPARATOR_INFERIOR`  

## Question

A pre-known external-liquidity interaction was treated as the start of a causal evidence process, not as an entry signal. At every informationally distinct completed five-minute state, one common model compared continuation, reversal and wait/flat by direct fixed-risk 24bp account return. BTCUSDT and ETHUSDT were test markets for the same normalized mechanism.

## Programization audit

All preliminary outputs were quarantined. The final authority corrected same-timestamp touch availability, hidden absolute-price scale, first-state comparator training, duplicate state emission, omitted new-excursion decisions, omitted funding state, causal expanding constants and positive-only winner deletion. The final source retains strict decision+500ms/first-later-minute execution, actual funding, adverse ambiguity, one global slot and no elapsed-time strategy close.

Two fresh symbol builds produced identical scientific action fingerprints, all three model prediction arrays were byte-identical, and the independent full-policy 24bp replay reproduced the final account exactly. Eleven focused tests passed.

## Breadth

- Pools: BTC `4,412`, ETH `4,096`.
- Episodes: BTC `2,083`, ETH `1,934`.
- Action rows: `242,660` across `3,901` parent events.
- Eligible 2021 training rows: `69,796`.
- 2022: `1,383` parent episodes and `81,421` emitted states.

This is not event scarcity.

## Raw action surface

At zero added cost, 2022 continuation action rows had mean fixed-risk account return `0.023996%`; after 24bp it was `-0.030528%`. Reversal was already negative at zero cost (`-0.002337%`) and remained negative at 24bp (`-0.049462%`).

## 2022 one-slot account comparison

| Policy | 0bp | 12bp | 18bp | 24bp | 24bp trades | 24bp PF | 24bp median | Winner-deleted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Continue | 1.038451x | 0.707185x | 0.617638x | 0.551224x | 466 | 0.537 | -0.2831% | 0.480926x |
| Reverse | 0.810922x | 0.528985x | 0.459409x | 0.409280x | 461 | 0.484 | -0.4826% | 0.310207x |
| Expanding action constants | 1.160529x | 0.694233x | 0.572749x | 0.484983x | 833 | 0.579 | -0.1748% | 0.416218x |
| First-state HGBT | 0.998551x | 0.735665x | 0.656586x | 0.595664x | 429 | 0.547 | -0.2799% | 0.523767x |
| Structural/location HGBT | 1.065764x | 0.841618x | 0.760931x | 0.694129x | 618 | 0.730 | -0.2067% | 0.659046x |
| Full sequential HGBT | 1.015918x | 0.793817x | 0.716827x | 0.653977x | 601 | 0.680 | -0.2175% | 0.619536x |

The full model was only `1.015918x` before added cost and fell to `0.793817x` at 12bp. At 24bp it ended `0.653977x`, with PF `0.680`, median `-0.2175%`, MDD `38.58%`, H1/H2 `0.776106x / 0.864391x`, and exact positive-winner deletion/full rerouting `0.619536x`.

## ML diagnosis

The full model's 2022 Spearman was `0.1682`, below the structural-only comparator `0.1816`. It predicted positive value for `50,991` action rows, but their realized 24bp mean was `-0.036922%` and median `-0.111651%`. The full one-slot path also underperformed structural/location-only at every realistic cost.

Sequential dwell, reclaim, excursion, OI, funding, FVG and peer state therefore did not add executable action value to location and geometry. The weak gross continuation tendency had no realistic cost headroom.

## Decision

Retire this exact sequential evidence information unit. Do not tune pool sources, state emissions, feature windows, model, threshold, action geometry, target, stop, cost, risk, leverage, session, symbol side or add SMC Boolean gates. Calendar 2023 and official 2024-2026 remain sealed. Ranking and order authority are unchanged. No credentials or orders were used.
