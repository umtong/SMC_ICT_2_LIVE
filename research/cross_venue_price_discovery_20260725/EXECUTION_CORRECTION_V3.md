# Execution correction V3

V2 remains useful for source and signal screening, but its account-development result is not admissible for promotion.

## Defects found before any selection interval was opened

1. If visible Binance top-quote quantity fell below the position's registered 5% participation cap at exit, V2 could skip the whole trade rather than force an adverse liquidation. This creates favorable survivorship.
2. Maximum drawdown was updated only after a trade closed and omitted realistic intratrade liquidation value.
3. Protective-stop detection used midpoint rather than the executable bid for longs and executable ask for shorts.
4. Positive-PnL symbol concentration was calculated from net symbol PnL rather than the sum of positive trade contributions.

## V3 contract

- Entry still rejects orders exceeding 5% of observed Binance top-quote quantity.
- Every entered position must exit. If visible exit liquidity is below the entry capacity limit, V3 applies a punitive spread-multiple impact instead of omitting the trade.
- Intratrade equity is marked at executable adverse liquidation value on every actual Binance quote event.
- Long stops trigger on executable bid; short stops trigger on executable ask.
- Stop has priority over convergence on the same quote event.
- Positive-contribution concentration is computed from positive trade PnL by symbol.
- Signal definitions, dates, latency, fees, risk, leverage, candidate grid and gates are unchanged.
- V1 and V2 account-development outputs cannot promote a candidate. V3 is authoritative.
