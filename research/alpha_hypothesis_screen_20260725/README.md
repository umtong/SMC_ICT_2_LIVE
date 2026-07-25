# Transcript-derived alpha hypothesis screen

## Claim

- claim_id: `CLAIM-20260725-1501-ALPHA-HYP`
- worker: `gpt-5.6-pro`
- base state revision: `3`
- branch: `agent/alpha-hypothesis-screen-20260725`
- scope: extract distinct falsifiable mechanisms from the 20 registered Korean YouTube transcripts, run a causal preliminary rejection screen, and move surviving mechanisms to checksum-verified official Binance USD-M continuous 5-minute data.

## Extracted mechanism families

The immutable bundle contains ten distinct causal hypotheses, including:

1. low-resistance liquidity run,
2. matched-scale high-resistance sweep reversal,
3. flow-efficiency continuation,
4. absorption reversal,
5. accumulation-manipulation-distribution session delivery,
6. invalidated order-block breaker first retest,
7. confirmed structure-break first retest,
8. fakeout/trap first retest,
9. macro-time delivery window,
10. engulfing-body order-block first touch.

Each hypothesis records source IDs and transcript timestamps, the information-availability boundary, execution point, invalidation and failure conditions. External claims of profitability were not accepted as evidence.

## Preliminary quarter-hour rejection screen

A registered Binance Vision USD-M 1-minute dataset covering BTCUSDT and ETHUSDT was used only for a coarse sequential screen:

- development: 2021-2022,
- fixed selection: 2023,
- 2024 opened only after a selection pass,
- 2025 and 2026 never opened.

Two candidates passed development but both failed the fixed 2023 selection interval:

| family | development 12bp | development 24bp | 2023 12bp | 2023 24bp |
|---|---:|---:|---:|---:|
| cross-asset liquidity run | +28.54% | +6.85% | -14.15% | -22.94% |
| high-resistance sweep reversal | +29.06% | +1.65% | -21.23% | -31.05% |

This is a negative result: a quarter-hour opening-minute summary is insufficient to classify resistance state or cross-asset propagation robustly. No 2024 confirmation data was opened and no candidate is Champion-eligible.

## Full continuous 5-minute follow-up

`src/liquidity_state_5m.py` performs a higher-information causal screen with official Binance Vision monthly archives and adjacent checksum verification. It compares incompatible mechanism families rather than retuning the failed quarter-hour candidates:

- low-resistance run,
- high-resistance sweep,
- breaker first retest,
- fakeout first retest,
- PO3 session delivery.

Execution and evaluation constraints:

- completed signal bar only;
- entry at the next five-minute open;
- one global BTC/ETH slot;
- stop priority on an ambiguous bar;
- risk-based size at 0.5% NAV, maximum 3x notional leverage;
- 0.1% prior quote-volume capacity limit;
- 12/18/24 bps round-trip cost screens;
- development 2021-2022, selection 2023, physical 2024 acquisition only after a selection pass;
- 2025 and 2026 never opened;
- no credentials, private endpoints, orders, paper or live operation.

The screen is not Champion-eligible even if a candidate passes. Promotion requires account-level mark-to-market accounting, actual funding, exchange-specific execution and an independent later-data contract.

## Immutable identities

- combined Base64 SHA-256: `846da9aef976f43d1a42d3639ce3de7f0c5ca95b65b1f4cf88dc671b1147f81e`
- decoded tar.gz SHA-256: `0be627c4161af1940b41ec660b27d09b6b7f642199cb5f02b36f073de39585ad`
- transcript hypothesis JSONL SHA-256: `592cee51cfc404074d94c78b353111b1742e6c932e01302d8550f058c4c50b7c`
- preliminary summary SHA-256: `1bca1b19ca0bf0ee2caf5592ab9def83497e2578d263c619b88940aaea4e971b`
- full 5m research source SHA-256: `a50075e4b6b236ae7b70002952c234e233b12f22dd05177cd589dc6639b0fe65`
- full 5m test SHA-256: `61786d423b7807feddddeff89a9bf3770089a9bd728bc4f170dc226f52d4bdc1`

This directory is research-only and is not a deployable trading system.
