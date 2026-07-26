# Sources and mechanism

## Market data

- Tardis downloadable normalized CSV files.
- Binance Futures `book_snapshot_5` and `trades` are signal-only.
- Bybit `quotes` and `trades` define the causal sweep, executable bid/ask, structural barriers and account path.
- `local_timestamp` is the information-availability clock.
- Every downloaded gzip file is recorded with its exact URL, byte count, SHA-256, CSV header and parsed row count.

## Why this information unit is distinct

Same-venue Bybit cancellation/refill rules previously produced only a fraction of one basis point before additional cost. This study does not tune those rules. It asks whether the deeper and more active Binance Futures displayed book contains independent evidence about whether a Bybit liquidity raid is accepted or rejected.

Limit-order submissions and cancellations are economically meaningful because they change available liquidity before or during market-order execution. The external book is used only through named, signed features; SMC/ICT supplies the pre-known liquidity pool, raid, structural target and invalidation.
