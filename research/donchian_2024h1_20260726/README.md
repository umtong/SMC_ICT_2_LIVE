# Official 2024H1 replay of the current Donchian rank-one

Claim: `CLM-20260726-2139-DONCHIAN-2024H1-001`  
Result: `RES-20260726-DONCHIAN-2024H1-001`

This is the immediate first official sequential evaluation of the pre-2024 rule currently ranked first. It does not preserve 2024H1 as a permanently sealed holdout. The unchanged strategy is evaluated now, and the observed result is used to decide whether to abandon the family or form the next hypothesis using information available through June 2024. A later modified strategy may not call this already-observed interval independent OOS.

## Frozen trader-readable rule

- The prior completed 96-hour high and low are external liquidity.
- A completed hourly close outside either boundary is accepted displacement.
- Entry is the next hourly open in the breakout direction.
- A two-ATR20 stop is structural invalidation.
- A completed close through the opposite prior 48-hour channel signals failed delivery; exit is the next hourly open.
- There is no maximum holding period or elapsed-time liquidation.
- BTC, ETH, SOL and XRP share one pending/open account slot.

## Evaluation

Official Bybit hourly archives from December 2023 through June 2024 supply warm-up and evaluation bars. The downloader first uses Bybit's public MT4 archive and falls back only to the official V5 linear-kline endpoint. Funding uses the official history endpoint when complete; otherwise the frozen adverse reserve charges both sides rather than assuming zero.

The account begins at 10,000 USDT on 2024-01-01, includes all 182 UTC calendar days, and replays identical 12/18/24-bp paths at 0.5% planned structural-stop risk and a 5x notional cap. A position still open at June 30 is marked at the boundary, not forcibly closed. Top 1%, 5% and 10% winning event keys are removed before a complete chronological slot and NAV rerun.

No credentials or orders are used.
