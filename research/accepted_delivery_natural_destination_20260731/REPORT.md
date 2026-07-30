# Natural-destination lifecycle audit for sponsored 96h accepted delivery

## Decision

`RETIRED_PRE2024_WINNER_CONCENTRATED_NATURAL_DESTINATION_LIFECYCLE`.

This audit did not add a filter to the parent event. It replaced the fixed `+1.5R` / `2ATR` payoff template with one scenario-native lifecycle: the nearest causally live directional external-liquidity destination, the breakout-hour opposite extreme as protective invalidation, and the first later completed reacceptance inside the consumed 96h boundary as premise loss. Risk was fixed at 3% of entry NAV including expected normal-stop costs. No arbitrary nominal cap, score multiplier, fixed-R target, runner, or elapsed-time exit was used.

## Event and code parity

The exact parent event yielded 334 eligible sponsored 96h acceptance observations in 2021-2023: 182 BTCUSDT and 152 ETHUSDT. The natural lifecycle retained 303 events. The 31 flat decisions were explained by causal state, not result filters: 12 had no live directional destination, 10 lost outside acceptance before the first executable minute, 5 could not pay unavoidable 24bp/funding cost even at the full destination, 3 had the destination already behind the entry, and 1 destination was consumed before entry.

## Frozen pre-2024 results

| Cost | Period | Multiple | Geometric/day | Trades | PF | Median trade | Daily MDD | Winner-deleted multiple |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 12bp | 2021_DIAGNOSTIC | 1.898230x | 0.175749% | 62 | 2.582 | 0.832% | 11.23% | 1.305657x |
| 12bp | 2022_FORWARD | 1.804318x | 0.161825% | 56 | 2.125 | 1.120% | 7.91% | 1.214986x |
| 12bp | 2023_CONFIRMATION | 1.510382x | 0.113040% | 87 | 1.412 | 0.300% | 19.31% | 0.778985x |
| 12bp | 2022_2023 | 2.725209x | 0.137429% | 143 | 1.585 | 0.583% | 19.31% | 0.894102x |
| 18bp | 2021_DIAGNOSTIC | 1.807354x | 0.162286% | 62 | 2.433 | 0.763% | 11.31% | 1.255623x |
| 18bp | 2022_FORWARD | 1.715568x | 0.147984% | 56 | 2.022 | 1.045% | 7.92% | 1.167843x |
| 18bp | 2023_CONFIRMATION | 1.366814x | 0.085648% | 87 | 1.309 | 0.199% | 22.75% | 0.723425x |
| 18bp | 2022_2023 | 2.344862x | 0.116812% | 143 | 1.492 | 0.494% | 22.75% | 0.855053x |
| 24bp | 2021_DIAGNOSTIC | 1.724755x | 0.149450% | 62 | 2.297 | 0.691% | 11.50% | 1.122968x |
| 24bp | 2022_FORWARD | 1.635551x | 0.134880% | 56 | 1.927 | 0.974% | 7.93% | 1.114752x |
| 24bp | 2023_CONFIRMATION | 1.246033x | 0.060283% | 87 | 1.216 | 0.103% | 25.78% | 0.676578x |
| 24bp | 2022_2023 | 2.037951x | 0.097574% | 143 | 1.407 | 0.398% | 25.78% | 0.754216x |


At the primary 24bp path, 2022 forward remained positive after exact winner deletion and complete one-slot rerouting (`1.114752x`). Unchanged 2023 did not: the ordinary path was `1.246033x`, but the winner-deleted path was `0.676578x`. Its largest five winners supplied 43.63% of positive PnL. The failure persisted when risk was only 0.5% (`0.939469x` after deletion), proving that 3% sizing amplified but did not create the weak base distribution.

The 2023 ordinary result came mainly from a few large BTC long deliveries. The largest trade returned 24.16% of account NAV toward the October 2023 prior-day high destination. In contrast, unchanged 2023 BTC shorts and ETH shorts were negative as groups. Selecting the profitable side after seeing 2023 would be a forbidden rescue, so no side, pool-type, target, stop, or threshold adjustment was attempted.

Maximum required leverage at 3% risk was `6.200007x`, so the result was not constrained by an arbitrary cap. One trade lost 3.2159%, slightly more than planned 1R, from realized execution/funding effects; this was retained rather than clipped.

## Why official 2024-2026 stayed closed

The contract required both 2022 and unchanged 2023 to remain positive after deleting the largest 10% of winners and rerouting the global slot. 2023 failed. Opening 2024 would provide no decision value and would expose another weak variant to the official interval. No ML was trained because the deterministic scenario did not establish a robust base Core.

## Interpretation

The parent sponsored 96h accepted-delivery mechanism can produce valuable long-duration Expansion. Replacing its fixed-R realization with the nearest natural external pool creates attractive aggregate returns, but it does not create the missing frequent independent Core: profitability remains concentrated in a few large deliveries and changes materially with the 2023 direction mix. This exact lifecycle is retired without adjacent rescue. The parent Expansion remains separate and unchanged.

No credentials, paper/testnet/live orders, ranking change, or live authority were created.
