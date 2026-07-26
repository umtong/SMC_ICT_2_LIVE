# Sources and data contract

## Market data

The workflow uses normalized downloadable CSV datasets from Tardis.dev.

- Coinbase exchange id: `coinbase`
- Coinbase signal file: `trades/BTCUSD`
- Bybit derivatives exchange id: `bybit`
- Bybit execution file: `quotes/BTCUSDT`
- URL contract: `https://datasets.tardis.dev/v1/:exchange/:dataType/:year/:month/:day/:symbol.csv.gz`
- Only the first day of each preregistered month is used.
- `local_timestamp` is the arrival-time information clock.
- Trade `side` is the liquidity-taker side.
- Quote rows contain executable top bid/ask prices and amounts.

Official documentation:

- `https://docs.tardis.dev/historical-data-details/coinbase`
- `https://docs.tardis.dev/historical-data-details/bybit`
- `https://docs.tardis.dev/downloadable-csv-files`

Coinbase data are collected in GCP London and Bybit data in GCP Tokyo. The strategy therefore does not assume co-located observation. It adds a fixed 500-ms relay delay and requires the unchanged signal to survive 1,000 ms.

## Mechanism evidence

External research is used only to motivate the hypothesis, never as evidence of profitability.

- Bitcoin metaorder research documents persistent impact during large order execution and distinguishes informed from decaying uninformed impact.
- High-frequency crypto order-flow research finds order flow can contain temporally stable price-formation information.
- Research on centralized crypto venues documents temporary cross-venue price-discovery discrepancies.

The project evaluates the exact information unit directly under the frozen Bybit account contract.
