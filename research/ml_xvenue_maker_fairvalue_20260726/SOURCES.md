# Source contract

The initial screen uses Tardis normalized downloadable CSV public first-day samples.

- Download pattern: `https://datasets.tardis.dev/v1/{exchange}/{dataType}/{year}/{month}/{day}/{symbol}.csv.gz`
- Binance venue identifier: `binance-futures`
- Bybit venue identifier: `bybit`
- Data types: `quotes`, `trades`
- Symbol: `BTCUSDT`
- Availability clock: `local_timestamp`
- Quotes fields: `ask_amount`, `ask_price`, `bid_price`, `bid_amount`
- Trades aggressor field: `side`

Provider references:

- https://docs.tardis.dev/api/downloadable-csv-files
- https://docs.tardis.dev/downloadable-csv-files
- https://docs.tardis.dev/historical-data-details

Only 2022-07-01, 2023-03-01 and 2023-07-01 are opened by the initial workflow. No 2024-2026 source URL exists in the workflow.
