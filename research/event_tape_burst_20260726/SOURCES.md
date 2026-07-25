# YouTube and source synthesis

## Pre-2024 concepts used

The historical rule structure uses only sources available by 2023-12-31.

1. **Humbled Trader — “How to Read Level 2 Time and Sales, Tape Reading”** (`g6WZyHwd7oY`, 2020-05-13). Useful primitive: trade sequencing and tape pace can reveal a change in active participation. The study does not copy discretionary chart calls; it maps the idea to inter-trade activity episodes and notional-per-second.
2. **Orderflows / Michael Valtos — “Everything You Wanted To Know About Orderflows Part 1”** (`ZWBslSS1h1A`, 2021-03-07). Useful primitive: distinguish aggressive transactions from passive response. The archive’s exchange aggressor side supplies the observable transaction side; no hidden intent is inferred.
3. **MBoxWave — “5D ORDER FLOW” webinar** (2022-06-09) and the contemporaneous XPace/XKontrol material. Useful primitive: combine pace with which side controls aggressive flow, and distinguish strong effort that produces a directional result from climactic effort that does not.
4. **Optimus Futures — “Absorption | Advanced Order Flow Strategy Using Footprint Charts”** (`61K5sJVe0Ic`, 2023-01-06). Useful primitive: unusually strong aggressive activity that fails to move price can indicate absorption and possible reversal.

These are hypothesis sources, not evidence that a strategy is profitable. Every claim is translated into exchange-native variables and subjected to a frozen after-cost screen.

## Quantitative translation

| Source vocabulary | Frozen observable |
|---|---|
| tape pace | total episode aggressor notional / causal episode duration |
| buyer/seller control | absolute signed aggressor notional / total episode notional, with sign retained |
| initiative | high pace/control plus high positive direction-adjusted displacement efficiency |
| effort versus result | direction-adjusted displacement / `log(1 + notional)` |
| absorption | high effort/control, low efficiency and material end-of-episode retracement |
| confirmation timing | only after quiet-time or duration-cap closure, then an additional 100 ms latency |

## Material reviewed but not used to define historical rules

- Later English footprint/order-flow videos (`ljk9BovCSqI`, `Tdac8U1qpTU`) reinforced the same vocabulary but postdate the 2023 information cutoff, so they do not define the 2024 historical contract.
- Chinese-language Bookmap/time-and-sales heatmap material emphasized order-book liquidity. It was not pursued because the project already has active L2 maker and cross-venue scopes, while free full-history depth reconstruction is materially harder than native trade-tape reconstruction.
- Dealer-gamma and options-pinning videos suggested a structurally different state variable, but free historical strike-by-strike open interest and Greeks sufficient for the full causal period were not established. The idea remains separate from this claim rather than being approximated with current snapshots.
- The project’s existing Korean transcript corpus had already generated and tested sweep, breaker, fakeout, PO3 and engulfing families in earlier PRs. Those rules were not renamed or retuned here.

## Market data source

Bybit’s public archive directories expose daily BTCUSDT and ETHUSDT trade files for every preregistered 2023 date. The workflow records each compressed byte count, full gzip CRC read and SHA-256. Required fields are `timestamp`, `side`, `size` and `price`; later periods remain unopened unless the preregistered development gate passes.
