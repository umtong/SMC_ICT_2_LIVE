# Source and concept boundaries

The strategy is defined in mechanical project language. External educational material supplies vocabulary and falsifiable sequencing ideas only; it is not evidence of profitability.

## SMC/ICT concepts translated into observables

- **External liquidity:** a causally confirmed 15-minute swing high or low. No unconfirmed pivot is visible to the strategy.
- **Liquidity raid:** completed wick through the confirmed level followed by a close back through it.
- **Market-structure shift:** completed displacement close through a previously confirmed one-minute internal pivot.
- **Order Block failure / Breaker:** the last opposite candle before displacement is not called a Breaker until a completed close crosses its far edge.
- **Fair Value Gap:** classic three-candle same-direction gap produced by the displacement leg.
- **Unicorn:** the exact intersection of the converted Breaker and the FVG, not the mere presence of both objects.
- **Consequent encroachment:** the midpoint of the overlap, used only by the frozen retracement-acceptance variant.
- **Draw on liquidity:** opposing external liquidity confirmed before the entry decision.

## Historical educational sources

The pre-2024 rule vocabulary was cross-checked against ICT material on liquidity runs, short-term market-structure shifts, Fair Value Gaps and Breakers, and against a 2023 public explanation of the Unicorn model. These sources are hypothesis inputs only. The project code supplies the exact availability times, invalidation rules, execution assumptions and account logic.

## Market-data sources

- Bybit public historical MetaTrader 4 kline archive: native BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT one-minute files.
- Bybit official V5 market-kline documentation: current field-order and closed-kline semantics reference only; historical files remain the research input.

Every downloaded historical file is identified by URL, compressed SHA-256, decompressed SHA-256, row count, timestamp bounds and detected gaps. A future provider replacement must receive a new dataset revision.

## Interpretation boundary

A positive one-minute bar result does not prove live tradability. Before 2024 can open, a frozen survivor must be reconstructed with exact Bybit point-in-time BBO/depth, historical funding, tick/lot limits, realistic marketable-order rejection and partial-fill behavior. No source is used to justify a return claim without direct project evaluation.
