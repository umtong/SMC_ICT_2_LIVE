# Fresh leveraged-inventory cost-basis Core — duplicate corroboration

- Claim: `CLM-20260730-FRESH-INVENTORY-COST-BASIS-CORE-001`
- Result: `RES-20260730-FRESH-INVENTORY-COST-BASIS-CORE-CORROBORATION-001`
- Status: `RETIRED_DUPLICATE_CORROBORATION_PROGRAMIZATION_CORRECTED_SUBCOST_OR_SIGN_UNSTABLE`

## Logic tested

Native Bybit 500ms aggressive flow and completed five-minute OI increases were combined to infer a fresh leveraged-inventory packet and aggressive-side VWAP cost basis. A profitable packet whose origin remained intact and whose first cost-basis retest rejected in its direction prescribed continuation. An underwater packet reaccepted through cost basis after failed reclaim prescribed reversal.

BTCUSDT 2023 was only the fatal testbed. January-April froze normalization thresholds; May-August was untouched development. September-December, ML, risk optimization and official 2024-2026 stayed sealed.

## Programization correction

The first implementation was quarantined because protected continuation did not require the packet origin to remain intact and entry used the next one-minute open rather than the first native observed 500ms price after decision+500ms. The corrected result uses both required semantics.

## Corrected development economics

The screen generated 1,929 qualifying packets and 309 state events: 212 protected continuations and 97 trapped reversals.

Protected continuation had only +4.90bp mean and +4.62bp median gross movement at 240 minutes; after the principal 24bp cost the mean was -19.10bp. Its May-August 240-minute mean varied from -0.10bp to +10.53bp, never approaching realistic cost.

Trapped reversal had +1.30bp mean at 15 minutes but became -15.06bp by 240 minutes. Its monthly 240-minute sign changed from -50.48bp in June to +15.85bp in August.

The combined 240-minute mean was -1.36bp gross and -25.36bp after 24bp.

This is not a sparse-jackpot failure: events were reasonably distributed and protected top-five positive contribution was about 20% at 240 minutes. The problem is that the broad gross relation is much smaller than cost and the reversal state is sign-unstable.

## Duplicate discovery and decision

After the independent screen was complete, issue #617 / `RES-20260730-FRESH-INVENTORY-COST-BASIS-001` was found to have already tested the same core proxy in 2022 and reached the same observability conclusion. Public aggressive buys can represent fresh longs or short covers; passive sells may be fresh shorts; net OI reports only pair count. Aggressive-side VWAP therefore is not a causal cost basis of the party expected to be protected or trapped.

This result is retained only as independent corroboration. Do not create another PR or reopen the family with windows, thresholds, buffers, SMC nouns, symbols, lower costs, ML, risk or leverage. No ranking or live-permission change. No orders.
