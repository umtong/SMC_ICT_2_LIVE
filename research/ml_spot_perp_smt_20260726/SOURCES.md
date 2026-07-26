# Immutable source contract

## Bybit execution market

Reused immutable GitHub Actions artifact:

- artifact ID: `8626087323`
- artifact SHA-256: `90594acc23e63e97e83347f9b07eb9ac260ba7bb1b87eb72052287a8328ad4a1`
- compact state clock: Tardis `local_timestamp`, completed 100 ms decisions
- compact files:
  - `output/compact_states/2022-07-01_BTCUSDT_state.parquet`
  - `output/compact_states/2023-07-01_BTCUSDT_state.parquet`

The upstream manifest fixes the corresponding raw Bybit trade files:

| Date | Bytes | SHA-256 |
|---|---:|---|
| 2022-07-01 | 36,158,133 | `fd1b225da124666f1411b53c4537aba721ce443f715737135b89316f81d0146f` |
| 2023-07-01 | 7,480,525 | `0707925b9320626560a5aa2ce89c78666b27266c92626fc6a6ff5236a0d5b301` |

## Binance spot information market

Exact Tardis first-day monthly URLs are frozen in code:

- venue: `binance`
- symbol: `BTCUSDT`
- data types: `quotes`, `trades`
- fit date: `2022-07-01`
- conditional development date: `2023-07-01`

Known retained identity:

- 2023-07-01 Binance spot quotes: 6,823,455 bytes, SHA-256 `ce55eff4b96997ec9ad702c168bc9e4594f12f1d353a61fb06128b34be0bacc6`.

All newly acquired files are gzip-read, byte-counted and SHA-256 recorded before parsing. A row is usable only at its `local_timestamp`. No exchange timestamp is substituted for arrival time.

No private endpoint, credential or order is used.
