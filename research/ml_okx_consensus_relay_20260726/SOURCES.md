# Sources

## Tardis downloadable CSV datasets

- OKX Spot exchange id: `okex`; symbol: `BTC-USDT`.
- OKX Swap exchange id: `okex-swap`; symbol: `BTC-USDT-SWAP`.
- Bybit Derivatives exchange id: `bybit`; symbol: `BTCUSDT`.
- Data types: `trades`, `quotes`, and OKX Swap `derivative_ticker`.
- URL contract: `https://datasets.tardis.dev/v1/:exchange/:dataType/:YYYY/:MM/:DD/:symbol.csv.gz`.
- Historical first-day monthly CSV files are public without an API key.
- CSV files are split and ordered by `local_timestamp`; original row order is retained.

Official documentation:

- `https://docs.tardis.dev/downloadable-csv-files`
- `https://docs.tardis.dev/historical-data-details/okex`
- `https://docs.tardis.dev/historical-data-details/okex-swap`
- `https://docs.tardis.dev/historical-data-details/bybit`
- `https://docs.tardis.dev/api/instruments-metadata-api`

## Model implementation

`scikit-learn` `HistGradientBoostingClassifier` and `IsotonicRegression` are used only as fixed implementations of the preregistered single-model contract. No external performance claim is imported.
