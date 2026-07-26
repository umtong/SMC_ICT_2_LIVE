# Retained sources

## Bybit execution-market data

- Bybit public historical MT4 kline archive root: `https://public.bybit.com/kline_for_metatrader4/`
- BTCUSDT archive directory: `https://public.bybit.com/kline_for_metatrader4/BTCUSDT/`
- ETHUSDT archive directory: `https://public.bybit.com/kline_for_metatrader4/ETHUSDT/`

The implementation records URL, byte count and SHA-256 for every monthly file.

## External risk-market data

- Dukascopy historical data API: `https://www.dukascopy.com/swiss/english/marketwatch/historical/`
- `dukascopy-node` documentation: `https://www.dukascopy-node.app/`
- USA 100 Technology instrument: `https://www.dukascopy-node.app/instrument/usatechidxusd`
- USA 500 instrument: `https://www.dukascopy-node.app/instrument/usa500idxusd`
- Source repository: `https://github.com/Leo4815162342/dukascopy-node`

The workflow pins `dukascopy-node@1.46.4`. It downloads one-minute bid OHLCV as a signal source only. The two index instruments have minute history before 2022. Their prices are never used as Bybit execution prices.

## Model

- scikit-learn `HistGradientBoostingClassifier`: `https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html`
- scikit-learn `IsotonicRegression`: `https://scikit-learn.org/stable/modules/generated/sklearn.isotonic.IsotonicRegression.html`

HGBT is used because the frozen input is a small tabular event state. No deep architecture or model-family search is introduced before the external information unit proves economic value.
