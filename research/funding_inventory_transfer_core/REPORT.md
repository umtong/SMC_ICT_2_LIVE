# Funding-settlement inventory transfer Core — final report

Result ID: `RES-20260730-FUNDING-INVENTORY-TRANSFER-CORE-001`

Verdict: `RETIRED_FATAL_SCREEN_NOT_CORE`

## Economic question

Every actual nonzero Bybit funding settlement transfers cash between the crowded payer side and the receiving side. The tested policy asked whether the first fully completed post-settlement minute, native 500ms aggressive-flow/price-impact state, OI, account-ratio and market context could distinguish:

- `PERSIST`: continued delivery in the funding/crowding direction;
- `UNWIND`: reversal as crowded inventory is reduced and same-direction flow fails;
- `FLAT`.

This was an inventory cash-transfer hypothesis, not a chart-pattern or fixed clock seasonality rule.

## Data and chronology

- BTCUSDT and ETHUSDT canonical funding, one-minute, five-minute OI/account-ratio, and native `MICROBAR-SPARSE500-V5` files;
- January, April and July 2023 fit partitions;
- October and December 2023 confirmation;
- fixed 500ms activation after one complete post-settlement minute;
- one global slot, actual subsequent funding, 0.5% NAV planned loss, 3x cap and 12/18/24bp;
- structural stop and +1.5R target, with no elapsed-time exit.

The final source covered 922 funding events and 1,843 counterfactual action rows. The fit used 1,099 resolved action rows; confirmation contained 744 action rows.

## Confirmation account paths at 24bp

| Policy | Trades | NAV multiple | PF | Median trade | Positive trades | MDD |
|---|---:|---:|---:|---:|---:|---:|
| PERSIST | 174 | 0.77466x | 0.460 | -0.5000% | 80 | 22.98% |
| UNWIND | 175 | 0.63652x | 0.243 | -0.5000% | 56 | 36.35% |
| Fixed ML policy | 22 | 0.94804x | 0.291 | -0.5000% | 7 | 6.32% |
| ML winner-deleted/rerouted | 21 | 0.94345x | 0.227 | -0.5000% | 6 | 6.32% |
| Future-information oracle | 167 | 1.60422x | — | +0.2460% | 167 | 0.00% |

The model predicted positive value for only 23 of 744 confirmation actions and did not produce a stable confirmation rank relation. It reduced breadth without creating positive cost-net value.

## Interpretation

Funding settlement is a real cash transfer, but the public post-settlement state did not reveal which side retained vulnerable inventory with enough precision to exceed realistic costs.

- A payer debit can be prepaid, hedged or too small relative to available margin.
- OI change is net pair count and does not identify which cohort opened, closed or remained trapped.
- Native aggressive flow describes executed initiative but not the ownership and margin condition of the positions being reduced or rebuilt.
- The broad deterministic actions were already negative; ML could only suppress most events.

The positive future oracle demonstrates that ex-post action separation exists, not that a causal Core exists.

## Decision

Retire this exact settlement→one-minute state→PERSIST/UNWIND information unit. Do not rescue it with a funding threshold, different post-settlement wait, feature windows, target/stop, side/session, SMC gate, model, lower costs, risk or leverage.

Official 2024–2026 remained sealed. No credentials or orders were used. This compact result does not carry the original evaluator source and is therefore negative-evidence packaging rather than rank-eligible reproducibility authority.
