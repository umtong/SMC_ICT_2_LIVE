# Cross-sectional positioning metrics research

## Mechanism

Historical Binance Futures `metrics` expose aggregate open-interest value, top-trader account and position long/short ratios, all-account long/short ratio, and taker buy/sell volume ratio at five-minute cadence. The study tests whether cross-sectional extremes and state transitions in these variables predict the next 2h/4h/8h market-neutral return.

The preregistered families distinguish:

- OI and price moving together versus diverging;
- OI expansion versus deleveraging;
- top-trader position size versus top-trader account count;
- top-trader positioning versus the wider crowd;
- taker flow versus outstanding positioning.

## Causal contract

- A metrics row is usable only after its recorded `create_time`.
- Price, return and liquidity features use the last kline whose close time is strictly before the metrics timestamp.
- Entry is the first five-minute open strictly after the metrics timestamp.
- Funding cashflows with `calc_time` in `(entry, exit]` are applied with the correct long/short sign.
- One market-neutral basket is opened per decision and held without overlap for 2h, 4h or 8h.
- Long and short gross exposures are each 0.5; no leverage is required.
- The same event ledger is replayed at 12, 18 and 24bp total round-trip costs.

## Staging

- 2021-10 through 2021-12: warm-up only.
- 2022: development over the immutable grid.
- 2023: downloaded and opened only for one frozen survivor per family.
- 2024: downloaded and opened only for selection survivors.
- 2025 and later: sealed.

No credential, private endpoint, paper/testnet/live order or deployment bundle is used.
