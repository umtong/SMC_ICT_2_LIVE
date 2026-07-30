# Scale-matched daily liquidity transfer with exact 500 ms entry state

**Result:** `RES-20260730-SCALE-MATCHED-DAILY-TRANSFER-MICROFLOW-001`  
**Decision:** retire the exact implementation after unchanged 2022 forward economic failure. Target, ranking and live authority are unchanged.

## Logic before strategy

The symbols are testbeds, not the thesis. The tested thesis came from the recurring liquidity-delivery narrative:

1. order flow depends on which external liquidity has already been secured and which scale-matched liquidity price seeks next;
2. price delivers external -> internal -> external;
3. low-resistance same-direction pools should not force realization;
4. a protected internal imbalance can support delivery toward the paired external objective.

The concrete operationalization paired the previous completed UTC-day low and high. A one-sided raid and 15-minute reclaim began the narrative. A later completed five-minute displacement had to break a causally confirmed swing and create a genuine three-candle FVG. The raid extreme was the protected origin, the FVG midpoint the internal rebalance, and the untouched opposite prior-day boundary the scale-matched external objective.

This was not a generic `sweep -> reverse` rule and did not substitute candle bodies for missing FVGs.

## Competing actions

- **PASSIVE:** rest at the genuine FVG midpoint and require one-basis-point penetration.
- **CONFIRMED:** after the first midpoint interaction, observe ten full 500 ms buckets strictly after the touch bucket; enter only if the FVG remains intact and price recovers in the delivery direction.
- **FLAT:** no fill, origin loss or target consumption before entry.

Stops remained beyond the raid extreme. Targets remained the untouched opposite prior-day boundary. There was no elapsed-time exit. Actual funding, 12/18/24 bp, fixed 0.5% current-NAV planned loss, 3x cap and one global BTC/ETH slot were applied.

## Programization audit

The preliminary replay contained two material chronology defects:

1. the ten-second response included part of the 500 ms bucket in which the exact touch occurred;
2. a high or low formed before an exact intra-bucket fill could be treated as a post-entry barrier.

The final authority starts the sensor at the next complete 500 ms bucket and orders every entry-bucket first/high/low event by its stored exact offset. It also requires complete FVG source bars and releases the slot only after the fully observed exit minute.

Six focused semantic tests pass. Two fresh complete runs produced all 32 common output files byte-identically.

## Development diagnostic — 2021 quarterly months

At 24 bp:

| action | trades | multiple | PF | median | top-five share | winner reroute |
|---|---:|---:|---:|---:|---:|---:|
| PASSIVE | 82 | 1.01124x | 1.035 | -0.500% | 51.47% | 0.90329x |
| CONFIRMED | 27 | 1.04914x | 1.527 | -0.4979% | 72.65% | 1.02124x |

This was not a robust Core. PASSIVE failed winner rerouting; CONFIRMED had only 27 selected trades and a negative near-full-stop median.

## Unchanged forward screen — 2022 quarterly months

Raw action economics were negative before cost:

| action | candidates | filled | target rate | mean gross | median gross | median RR |
|---|---:|---:|---:|---:|---:|---:|
| PASSIVE | 183 | 151 | 18.54% | -21.07 bp | -82.42 bp | 5.05 |
| CONFIRMED | 40 | 40 | 17.50% | -58.48 bp | -89.94 bp | 5.24 |

One-slot account:

| action | 12 bp | 24 bp | PF at 24 bp | median | winner reroute |
|---|---:|---:|---:|---:|---:|
| PASSIVE | 0.90721x | 0.87689x | 0.633 | -0.500% | 0.84899x |
| CONFIRMED | 0.94525x | 0.93502x | 0.501 | -0.500% | 0.91861x |

The failure was not caused by realistic costs. Confirmation selected a still more winner-dependent subset rather than repairing the state.

## Logic-to-code diagnosis

Scale matching was explicit, but two chart observations were asked to prove unobserved inventory facts:

- a prior-day raid and reclaim was treated as evidence that meaningful inventory had been secured;
- a later genuine FVG was treated as evidence that the internal rebalance was institutionally protected.

The forward gross result rejects those assumptions. The pattern identifies a recognizable narrative but does not identify the payer, ownership of new inventory or actual acceptance of the rebalance.

The cross-testbed result reinforces this point. In the 2022 24-bp passive path, BTC was strongly negative while ETH was locally positive; the confirmed action was negative in both. A universal mechanism should not require an after-the-fact BTC exclusion or side exception.

## Decision

Retire the exact daily raid/reclaim -> genuine 5m FVG midpoint -> opposite daily boundary route. Do not tune FVG, pivot span, session, side, symbol, target, stop, cost, risk, leverage or ML after observing the result.

The broader SMC/ICT principle is not rejected: order flow should be interpreted through liquidity already secured and the next scale-matched draw. The narrower lesson is decisive:

> **Price touching the right levels in the right order is not sufficient evidence that the corresponding inventory transfer actually occurred.**

The next distinct Core information source must observe sponsorship, forced inventory or acceptance more directly rather than adding another chart noun. Calendar 2023 and official 2024–2026 remained sealed. No credentials or orders were used.
