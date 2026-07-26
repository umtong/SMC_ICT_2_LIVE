# Immutable sources

## Upstream artifact

- GitHub Actions artifact: `8626087323`
- Artifact SHA-256: `90594acc23e63e97e83347f9b07eb9ac260ba7bb1b87eb72052287a8328ad4a1`
- Reused compact state:
  - `output/compact_states/2022-07-01_BTCUSDT_state.parquet`
  - `output/compact_states/2023-07-01_BTCUSDT_state.parquet`
- Availability clock: `local_timestamp`
- Decision clock: completed 100 ms bins

The compact state supplies causally available top-five book state and prior flow features. It does not contain price-level trade consumption; therefore raw trades are mandatory for queue depletion. Raw `book_snapshot_5` is downloaded and hash-verified as the parent state source.

## SHA-fixed raw files

| Date | Type | Bytes | SHA-256 |
|---|---:|---:|---|
| 2022-07-01 | `book_snapshot_5` | 50,953,798 | `7787c36c35a591c8fcf1bf629d8b82624ac61a6b970f09cdbcff01c9afb624b6` |
| 2022-07-01 | `trades` | 36,158,133 | `fd1b225da124666f1411b53c4537aba721ce443f715737135b89316f81d0146f` |
| 2023-07-01 | `book_snapshot_5` | 15,194,559 | `4ed34a4de337e276e8e58df96780bbb8868d1ead3b9c49839d295fe532aa2753` |
| 2023-07-01 | `trades` | 7,480,525 | `0707925b9320626560a5aa2ce89c78666b27266c92626fc6a6ff5236a0d5b301` |

The exact URLs are frozen in `maker.py` and `preregistration.json`. Calendar 2023 raw files are not downloaded unless every 2022 confirmation gate passes. Any request for 2024–2026 is rejected before URL construction.

No private endpoint, credential, order or live permission is used.
