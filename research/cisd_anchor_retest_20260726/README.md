# ICT liquidity-raid CISD anchor-retest fatal screen

This strategy is stated exactly as an SMC/ICT trader would execute it, but every state transition has a causal timestamp and an executable Bybit price.

## Trader-readable rule

For a bearish setup:

1. price trades above completed external buy-side liquidity;
2. the last bullish delivery candle's opening price—or its body midpoint—is frozen as the **Change in State of Delivery (CISD) anchor**;
3. within three completed bars, a bearish candle closes through that anchor; this is the actual delivery-state change, not a wick labelled after the outcome;
4. the first later retest of the anchor from below must close back below it;
5. sell at the next executable Bybit bid;
6. stop beyond the complete raid extreme;
7. target untouched opposing sell-side liquidity from the pre-raid range.

The bullish rule is symmetric. The position ends only at the stop, opposing external liquidity, a completed close that invalidates the CISD anchor, or a sample-end NAV mark. There is no elapsed-time liquidation.

## Frozen objective-first screen

- Bybit BTCUSDT linear perpetual;
- immutable completed **100 ms** causal BBO/trade states from Actions artifact `8626169763`;
- exact complete 5/15/30-second bars with a hard reset after every missing state;
- fit `2022-07-01`; untouched development `2023-07-01` only after a fit survivor;
- 486 policies: 3 bar durations × 3 liquidity horizons × 3 raid distances × 3 confirmation-body thresholds × price-only/raid-flow/dual-flow × open/body-midpoint anchors;
- next-bar executable BBO entry, adverse same-bar stop priority, one global slot;
- 12/18/24 bp all-in replay;
- 0.5%-8% planned-risk paths only after the underlying trade path is formed;
- largest 10% of positive 12 bp event keys removed before complete rerouting;
- 2024-2026 mechanically prohibited.

The fit gate requires at least 20 accepted trades, positive 24 bp mean and median, PF above one, at least 1% sample-day NAV growth at 1% planned risk, and the same after winner removal. A zero survivor closes the exact setup immediately.

## Source-frequency correction

The first run incorrectly treated the source rows as 500 ms states even though PR #72 explicitly emits every completed 100 ms state. It therefore rejected every bar before any valid strategy event could exist. `amendment_001_source_frequency_correction.json` invalidates that zero-event output and applies only two checksum-verified implementation corrections: ten rows per second and 100,000 µs spacing. The market rule, candidate grid, dates, costs and account logic are unchanged.

## Non-overlap

This is not Silver Bullet because no fixed time window or FVG is used. It is not OTE because no Fibonacci retracement is required. It is not Unicorn because no order block, breaker or FVG overlap is required. The information unit is the completed close through a frozen delivery-candle price and its first retest.
