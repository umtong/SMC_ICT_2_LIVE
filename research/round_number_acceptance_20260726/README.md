# Bybit round-number acceptance / rejection fatal screen

This work claim tests an absolute-price state that is not represented by the active event-tape, movement-hazard OCO, auction-profile, liquidation, cross-venue or term-structure claims.

## Economic hypothesis

Pre-2024 cryptocurrency microstructure studies consistently document that transactions cluster at round prices and immediately adjacent strategic prices. The earliest Bitcoin result also reports no unconditional return pattern after a round number. Therefore this screen does **not** assume that a round level is always support, resistance or a breakout point.

Instead, every signal begins with a causal trade-price crossing of an adaptive significant-digit grid:

- BTC near 20,000 uses a 100-USDT base grid; ETH near 1,500 uses a 10-USDT base grid.
- The tested levels are integer multiples of 0.5x, 1x and 2x that base grid.
- The UTC-day base grid is fixed from the first observed trade and never revised with later prices.
- A continuation is eligible only when the price remains on the destination side after a fixed 1/3/10-second confirmation window, aggressive flow is aligned and destination-side traded notional dominates.
- A reversal is eligible only when the crossed level was actually reached but the price, aggressive flow and traded-notional location return to the origin side before the decision.

The rules use dimensionless fractions of the grid so that BTC and ETH share one economic specification rather than symbol-specific price thresholds.

## Causal and execution contract

The public Bybit archive is replayed in timestamp order. A decision is made only after the confirmation window closes. Entry is the first later trade at or after an additional 100-ms latency. Every candidate enforces one global BTC/ETH slot through the first observed 2/5/15/30-minute diagnostic exit mark. Missing marks are unavailable rather than favorably filled. The same gross ledger is replayed at 12, 18 and 24bp all-in round-trip costs.

Fixed horizons are only a fatal payoff-persistence diagnostic. They are not a proposed deployment exit rule. A survivor cannot enter the cumulative strategy ranking; it must first receive exact Bybit BBO/depth reconstruction, funding, structural exits, risk sizing, broader pre-2024 coverage and a new causal gate before any 2024 opening.

## Frozen stages

- Fit/mechanism replay: 2023-01-15, 2023-03-19, 2023-05-21.
- Independent development screen: 2023-07-16, 2023-09-17, 2023-11-19.
- 2024, 2025 and 2026 remain sealed.
- Candidate grid: exactly 576 policies.
- No runtime threshold or model fitting is performed.

## Gate

At 18bp the candidate must have at least 60 trades, positive mean net markout, positive top-10%-removed return, positive results on at least two of three dates and on at least half of the six symbol-date cells, while the five largest positive trades contribute no more than half of positive PnL. Median net markout must be positive at 12bp and total return must remain positive at 24bp.

## Sources used to define the historical rule

- Urquhart (2017), *Price clustering in Bitcoin*, DOI `10.1016/j.econlet.2017.07.035`.
- Hu, McInish, Miller and Zeng (2019), *Intraday price behavior of cryptocurrencies*, DOI `10.1016/j.frl.2018.06.002`.
- Ma and Tanizaki (2022), *Intraday patterns of price clustering in Bitcoin*, DOI `10.1186/s40854-021-00307-4`.
- Quiroga-Garcia, Pariente-Martinez and Arenas-Parra (2022), *Evidence for round number effects in cryptocurrencies prices*, DOI `10.1016/j.frl.2022.102811`.

No post-2023 publication is used to define a historical decision rule.
