# L2 maker toxicity V1

Research-only implementation for `CLM-20260725-1958-L2-MAKER-001`.

The study estimates passive fill probability separately from conditional post-fill markout. It uses a pinned depth20 reconstruction for multi-level state, reconciles top-of-book prices against checksum-verified official Binance USD-M `bookTicker`, and admits fills only when official opposing `aggTrades` consume a fixed multiple of displayed queue plus the small research order. Touches and cancellations never create fills.

The final five common dates are sealed and are not downloaded by this stage. A positive result is a component-level discovery result only, because the depth20 source is third-party reconstructed data.
