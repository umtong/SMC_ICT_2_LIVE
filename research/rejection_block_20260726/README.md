# ICT rejection-block liquidity-raid fatal screen

This study tests an SMC/ICT setup that can be described directly to a discretionary trader while remaining fully causal and executable.

## Rule in trader language

A pre-existing rolling external-liquidity pool is raided. Aggressive flow continues toward the raid, but price closes back inside and leaves a large terminal wick: the wick/body segment is the **rejection block**. A later completed bar must displace away from the raid in the opposite direction. The first subsequent return into the rejection block must reject again; entry is at the next observed Bybit bid or ask.

For a bearish setup:

1. price runs buy-side liquidity above the completed rolling high;
2. aggressive buying is present, but the raid candle closes back below the pool and leaves a large upper wick;
3. a completed bearish displacement confirms that the wick represented absorption/rejection rather than acceptance;
4. the first return to the body edge, midpoint or deep part of the rejection wick closes back below the block;
5. sell at the next executable bid;
6. stop beyond the raid extreme;
7. target untouched opposing sell-side liquidity from the pre-raid range.

The bullish rule is symmetric. The position exits only by stop, opposing liquidity, completed rejection-block invalidation, or a sample-end NAV mark. There is no elapsed-time liquidation.

## Frozen screen

- Bybit BTCUSDT linear perpetual;
- immutable 500 ms BBO/trade states from Actions artifact `8626169763`;
- exact complete 5/15/30-second bars, reset after every missing 500 ms state;
- fit `2022-07-01`; conditional untouched development `2023-07-01`;
- 216 frozen policies across rolling-liquidity horizon, raid excess, wick/body ratio, confirming displacement and retest depth;
- next-bar executable BBO entry, adverse same-bar stop priority and one global slot;
- 12/18/24 bp replay;
- 0.5%-8% planned-risk account paths calculated only after the trade path exists;
- largest 10% of positive 12 bp event keys removed before complete rerouting;
- 2024-2026 mechanically prohibited.

The fit gate requires at least 12 accepted trades, positive 24 bp mean and median, PF above one, at least 1% sample-day NAV growth at 1% planned risk, and the same after winner removal. A zero survivor closes the exact setup without adjacent tuning.

## Non-overlap

This is not the active OTE sweep, Unicorn breaker/FVG, BPR, FVG-SMT, fixed-session range or L2 cancellation-prediction scope. The defining information unit is a flow-confirmed terminal rejection wick and its first retest.
