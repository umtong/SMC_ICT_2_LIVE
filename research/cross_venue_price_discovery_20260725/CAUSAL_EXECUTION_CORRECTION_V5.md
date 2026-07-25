# Causal execution correction V5

Status: frozen before any V5 price or PnL screen.

Claim: `CLM-20260725-1850-XVENUE-001`.

## Why V1–V4B cannot promote a result

The earlier engines bucketed quotes at 100 ms and retained the last quote in each bucket. Entry then searched those retained quote timestamps, so it did not necessarily use the first actual Binance quote after the latency boundary. More importantly, a Binance execution event could evaluate convergence with the last Bybit quote from the same 100 ms bucket even when that Bybit quote arrived later in local time. V3/V4/V4B repaired exit-capacity survivorship, executable-stop marking, concentration and drawdown handling, but did not repair this intra-bucket information-order defect. Their strategy/PnL outputs remain diagnostic only and are hard-invalid for ranking, selection or deployment.

A second ordering defect is also removed: account competition must be resolved by actual potential entry time, not only by signal-decision time. A signal with an earlier decision but a later first executable quote cannot reserve the global account slot before it can actually enter.

## Frozen V5 contract

- `local_timestamp` is parsed and ordered at microsecond precision. Exchange timestamps remain diagnostic only.
- Signal features remain completed 100 ms buckets. A bucket `[t,t+100ms)` is unavailable until `t+100ms`.
- The first actual Binance quote at or after an aligned entry boundary is retained separately from the bucket-closing quote. Same-local-timestamp quote ambiguity is resolved adversely for the requested side.
- Signal state uses the last unambiguous locally observed quote in a completed bucket. An ambiguous final timestamp group is ignored rather than ordered favorably.
- Protective-stop and mark-to-market checks use the adverse executable Binance extrema of a completed bucket.
- Convergence is tested only from completed-bucket Binance and Bybit state. It cannot use a later same-bucket Bybit quote at an earlier Binance event time.
- Stop has priority over convergence. A bucket containing both a horizon boundary and an adverse stop excursion is treated as a stop.
- Entry, stop, convergence and horizon orders all apply the configured latency. A non-aligned horizon is rounded up to the next 100 ms boundary before latency, adding at most 100 ms rather than using an unavailable intra-bucket path.
- Entry capacity remains capped at 5% of observed Binance top-quote quantity. Every accepted entry must exit; exit-capacity overruns receive the punitive V3 impact rule and unusable exit data fail the run closed.
- Competing signals are sorted by first executable local-arrival time, then by already-known score and stable identifiers. One global BTC/ETH account slot is enforced.
- Signals too close to the fixed daily source boundary to complete their maximum hold and latency are excluded by a date-boundary rule, not by realized PnL.
- Account sizing, risk fraction, leverage, fees, dates, symbols, economic families, parameter grid and promotion gates are unchanged.
- 2024 selection, 2025 confirmation and 2026 data remain sealed until an authoritative V5 development survivor exists.
- No credentials, paper/testnet/live orders or deployment permission are used.

## Promotion boundary

Only V5 outputs may challenge the strategy ranking. V1, V2, V3, V4 and V4B outputs may be retained as failure/audit evidence but must not open later samples or change the first-place strategy.
