# Frozen sources

## Tardis normalized Bybit public first-day datasets

The evaluator downloads only these data types for `BTCUSDT` and `ETHUSDT`:

- `quotes`: executable best bid/ask, displayed top quantities and local arrival timestamp;
- `trades`: aggressive side, price, amount and local arrival timestamp;
- `derivative_ticker`: mark price, index price, open interest, funding rate and local arrival timestamp.

Canonical pattern:

```text
https://datasets.tardis.dev/v1/bybit/{data_type}/YYYY/MM/DD/{symbol}.csv.gz
```

Every downloaded gzip is schema-checked, hashed and recorded in `SOURCE_MANIFEST.json`. Input replay follows `local_timestamp`; no missing quote, trade or derivative state is interpolated beyond the frozen two-second BBO and ten-second ticker staleness limits.

## Economic execution market

The signal and account path are Bybit USDT-linear perpetual BTCUSDT/ETHUSDT only. Other exchanges are not used in this claim.
