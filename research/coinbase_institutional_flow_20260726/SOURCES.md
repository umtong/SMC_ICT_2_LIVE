# Source contract

## Durable signal source

Coinbase normalized `trades` and `quotes` CSV datasets provide exchange timestamp, capture timestamp, aggressor side, price, size and executable BBO state for `BTCUSD` and `ETHUSD`. Coinbase is signal-only.

## Execution source

Bybit normalized `trades`, `quotes` and `derivative_ticker` CSV datasets provide actual BTCUSDT/ETHUSDT BBO, local capacity and the final funding rate immediately preceding each funding timestamp. Bybit alone determines entry, exit, costs, funding and account NAV.

## Availability and ordering

- Every event uses only completed 15-second Coinbase windows.
- Row order is retained for equal exchange timestamps.
- Because capture locations differ, no sub-millisecond cross-provider ordering is claimed.
- Entry waits the frozen two-second or five-second delay and uses the first fresh Bybit BBO.
- The prior Bybit five-minute range ends before the Coinbase event window begins.

## Dataset URLs

The workflow downloads only first-day public files from `https://datasets.tardis.dev/v1/{exchange}/{data_type}/{YYYY}/{MM}/{DD}/{symbol}.csv.gz`, records SHA-256, byte count and parsed row count, and keeps later dates sealed unless the fit gate passes.

BitMEX is prohibited in every role.
