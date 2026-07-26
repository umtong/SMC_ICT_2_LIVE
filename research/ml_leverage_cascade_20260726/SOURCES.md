# Sources and availability contract

## Binance USDT-margined perpetual positioning metrics

Official archive template:

```text
https://data.binance.vision/data/futures/um/daily/metrics/{SYMBOL}/{SYMBOL}-metrics-YYYY-MM-DD.zip
```

Used fields:

- `create_time`
- `sum_open_interest_value`
- `count_toptrader_long_short_ratio`
- `sum_toptrader_long_short_ratio`
- `count_long_short_ratio`
- `sum_taker_long_short_vol_ratio`

The source loader accepts textual UTC timestamps or epoch seconds/milliseconds, requires all six numerical fields, rejects duplicate timestamps except for a deterministic last-row choice, never backfills a future row and allows at most ten minutes of metric staleness at an event.

The previously preserved project manifest established uninterrupted BTC files from 2021-10-01 and ETH files from 2021-12-01 through 2022-12-31. Those availability facts were used only to correct the preregistered training start before this run; no prior strategy result or fitted parameter is reused.

## Bybit USDT linear perpetual one-minute bars

Official archive template:

```text
https://public.bybit.com/kline_for_metatrader4/{SYMBOL}/{YYYY}/{SYMBOL}_1_YYYY-MM-01_YYYY-MM-lastday.csv.gz
```

Rows are parsed as:

```text
timestamp, open, high, low, close, base_volume
```

All signals, targets, stops, fills, liquidity participation estimates and account marks are based on Bybit. Monthly files are required; timestamps are reindexed to a complete UTC minute grid. Missing minutes are never forward-filled for signal or fill logic.

## Reproducibility

Every fetched file is retained only in the ephemeral workflow cache but is represented in `SOURCE_MANIFEST.json` by URL, local cache path, byte count, status and SHA-256. The artifact also includes exact code, preregistration, environment versions, frozen model objects and checksums. No API key, account data, order endpoint or private source is used.
