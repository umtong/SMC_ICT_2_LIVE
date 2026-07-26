# 2023-only ML UTC-state selection and official 2024H1 result

This experiment repairs the selection boundary of the provisional future-selected XRP route. It uses only information available through 2023-12-31 to select one fixed causal ML route and then immediately opens the first official interval, 2024H1.

## Trader-readable mechanism

One pooled Ridge model estimates each permitted contract's next 24-hour return from completed trend, volatility, quote-volume, taker-flow, cross-sectional breadth and asset-specific UTC hour state. The global account may hold one position. A selected route enters at the next hourly open and exits only when its signed expected edge is no longer positive; there is no elapsed-time liquidation.

## Selection before 2024

- fit one fixed model on 2023H1;
- calculate one Q3 95th-percentile absolute prediction scale;
- replay a fixed 720-route session/side/asset/threshold tournament on Q3;
- require the identical route to pass unchanged Q4 confirmation and winner removal;
- refit the identical model on all eligible 2023 rows before reading 2024H1.

Fifty routes survived Q3. Exactly one survived Q4:

`SOLUSDT / SHORT / UTC00-11 / 0.75 × Q3 threshold`.

Its absolute short-entry threshold was `-0.013466328577653525`.

## Official 2024H1 result

The all-2023 refit produced a minimum SOLUSDT prediction of only `-0.01119145604313856` during the frozen UTC00-11 session. Therefore it generated zero eligible entries.

- 12/18/24bp completed trades: `0 / 0 / 0`;
- 12/18/24bp geometric daily growth: `0 / 0 / 0`;
- later half-years opened: none;
- credentials or orders: none.

## Decision

Retire this exact pre-2024-selected route. Do not lower its threshold, widen the session, switch the asset or direction, alter features or retune Ridge alpha after observing 2024H1. The provisional future-selected XRP route remains a ranking benchmark, not causal official evidence. Research moves to materially distinct external inventory and forced-flow information sources.
