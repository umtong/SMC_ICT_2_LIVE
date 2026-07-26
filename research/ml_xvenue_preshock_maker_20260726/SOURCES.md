# Source contract

The initial screen uses Tardis normalized downloadable CSV public first-day samples.

- endpoint pattern: `https://datasets.tardis.dev/v1/{exchange}/{dataType}/{year}/{month}/{day}/{symbol}.csv.gz`
- Binance venue: `binance-futures`
- Bybit venue: `bybit`
- data types: `quotes`, `trades`
- symbol: `BTCUSDT`
- availability clock: `local_timestamp`
- quote fields: `ask_amount`, `ask_price`, `bid_price`, `bid_amount`
- trade aggressor field: `side`

Provider references:

- https://docs.tardis.dev/api/downloadable-csv-files
- https://docs.tardis.dev/downloadable-csv-files
- https://docs.tardis.dev/historical-data-details

Only 2022-07-01, 2023-03-01 and 2023-07-01 are opened by the first workflow. No 2024-2026 URL appears in the workflow.
