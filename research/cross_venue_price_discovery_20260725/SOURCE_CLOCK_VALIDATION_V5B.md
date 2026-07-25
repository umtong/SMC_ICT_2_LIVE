# Source-clock validation V5B

Status: frozen before any authoritative V5B price or PnL screen.

Claim: `CLM-20260725-1850-XVENUE-001`.

Reused Source Registry entries:

- `docs:tardis:data-faq` — https://docs.tardis.dev/faq/data
- `docs:tardis:downloadable-csv-api` — https://docs.tardis.dev/downloadable-csv-files/api
- `docs:tardis:binance-futures` — https://docs.tardis.dev/historical-data-details/binance-futures
- `docs:tardis:bybit-derivatives` — https://docs.tardis.dev/historical-data-details/bybit

## Findings

- Tardis records each received WebSocket message at arrival using a synchronized clock and states that `local_timestamp` values are directly comparable when exchanges are collected in the same server location.
- The downloadable daily CSVs are split and ordered by local arrival timestamp. The public no-key sample covers the first day of each month and omits disconnect events.
- Binance USDT Futures collection has been in GCP `asia-northeast1` (Tokyo) since 2020-05-14.
- Bybit Derivatives collection has been in GCP `asia-northeast1` (Tokyo) since 2020-05-28.
- Therefore the fixed 2022–2023 Binance/Bybit sample uses same-region arrival clocks under the vendor's documented comparison condition.

## Frozen interpretation boundary

This evidence permits the V5B engine to compare local arrival order across the two venues only at the preregistered completed-100-ms signal boundary with 100-ms or 500-ms modeled order latency. It does not establish same-host capture, deterministic network delay, or permission for sub-millisecond lead/lag inference.

CSV disconnect omission is not treated as continuous-book evidence. Quote staleness is bounded, missing/unusable execution data fail closed, accepted entries require a causal exit quote, and the monthly-first-day public sample cannot certify full-calendar daily growth.

Any change in collection location, timestamp semantics, source format, sample entitlement, or tested date range invalidates this cached evidence for the affected dependency and requires a new source-clock audit.
