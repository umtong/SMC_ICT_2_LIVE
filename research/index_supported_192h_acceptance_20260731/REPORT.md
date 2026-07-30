# Index-supported 192h sponsored acceptance Core component audit

## Decision

`RETIRED_INDEX_CONFIRMATION_NOT_NECESSARY_OR_NOT_SUFFICIENT`.

This audit did not change the accepted-delivery event or action. It asked one programization/economic question: after a high-participation trade-price close accepts beyond a prior 192-hour external range, does same-scale confirmation by the Bybit index basket identify genuine broader price discovery rather than perpetual-only chasing?

BTCUSDT and ETHUSDT are test markets. The thesis is the same in any liquid derivative market with an independently calculated spot/index reference.

## Frozen logic

The parent event and account are unchanged: all BTC/ETH long/short sponsored 192h parents, decision +500ms, first later minute entry, structural stop, full +1.5R, first completed trade-price close back inside the exact boundary as state loss, actual signed funding, one global slot, fixed 0.5% NAV planned loss, 3x cap and 12/18/24bp. No elapsed-time close exists.

The only component was:

- construct an index hour from exactly 60 observed canonical index-price minutes;
- exclude the decision hour from the prior 192-hour index range;
- confirm a long only when the completed index close also exceeds its prior index high, and a short only when it is below its prior index low;
- compare the exact baseline, confirmed subset and nonconfirmed complement without a buffer or model.

## Programization audit

- Six canonical index-price members were verified against each ZIP's internal manifest.
- Every retained index hour contained 60 consecutive observed minutes and became available only at hour end.
- All 337 parent decisions mapped one-to-one to an index decision hour.
- Every entry remained strictly later than decision +500ms.
- The exact 24bp parent baseline reproduced at `1.158589923x`.
- Two fresh processes produced all 39 outputs byte-identically.
- Focused validation passed `677` checks.

## Information result

The component was almost constant:

- baseline parents: `337`;
- index-confirmed: `335`;
- index-nonconfirmed: `2`.

Only two short events failed same-scale index confirmation: one profitable BTC event in 2021 and one losing ETH event in 2022. This is not enough breadth to define a separate causal state.

## 24bp continuous 2021-2023 accounts

| Policy | Multiple | Daily geometric | Trades | PF | Median | MDD | Winner-deleted/rerouted |
|---|---:|---:|---:|---:|---:|---:|---:|
| All sponsored 192h | `1.158590x` | `0.013444%` | 195 | 1.3675 | `-0.1587%` | `3.07%` | `1.101411x` |
| Index confirmed | `1.150898x` | `0.012836%` | 194 | 1.3518 | `-0.1595%` | `3.07%` | `1.094099x` |
| Index nonconfirmed | `1.003782x` | `0.000345%` | 2 | 2.3032 | `0.1900%` | `0.29%` | `0.997118x` |

The confirmed subset remained positive and winner-resistant only because it retained 99.4% of the parent events. It underperformed the baseline: `1.150898x` versus `1.158590x`. The minimum annual return also did not improve.

## Interpretation

The intended economic distinction is sound in principle, but this exact implementation adds no information. At the one-hour/192-hour scale, Bybit trade price and its index reference are so tightly coupled that a high-volume trade-price acceptance almost always implies same-direction index acceptance. The filter therefore does not distinguish spot-supported repricing from perpetual chasing; it merely restates the parent event.

This is an overfilter, not a necessary confirmation. Requiring it would discard two events without improving the account. A distance buffer, premium cutoff or nonlinear model would be a new exposed hypothesis and is not authorized by this result.

## Final classification

Retire `INDEX_CONFIRMED` as a component. Preserve the deterministic sponsored 192h parent only as weak, broad, winner-resistant Core evidence. Official 2024-2026, ML, risk/leverage and adjacent index/premium tuning remain closed. No credentials or orders were used.
