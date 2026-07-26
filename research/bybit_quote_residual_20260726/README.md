# Bybit executable quote residual screen

Claim: `CLM-20260726-1031-QUOTE-RESIDUAL-001`

## Why this path exists

The preceding BTC-only and BTC+ETH trade-print screens could not produce repeatable development events. Their state was built from asynchronous last trades, so an apparent lag could be either a genuine price-discovery delay or simply a stale print that was never executable.

This study changes the observable information unit. Tardis `quotes` datasets reconstruct Bybit best bid and ask from L2 updates and order rows by local arrival timestamp. The fatal screen measures the residual gap from the first actual follower quote after 100 ms latency, with long entries at ask and short entries at bid, and deducts a conservative target-side half-spread before comparing the gap with 12/18/24 bp hurdles.

## Initial stage

Only first-day monthly samples are used:

- fit: 2023-01-01 and 2023-03-01;
- development: 2023-05-01 and 2023-07-01;
- frozen validation: 2023-09-01 and 2023-11-01.

The workflow downloads BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT quote files for the four opened dates, records their SHA-256 identities, validates schemas and local-timestamp ordering, builds causal 100 ms BBO states, and counts independent executable residual events. Raw files remain runner-temporary.

No PnL, validation, 2024–2026 data, funding, risk/leverage search or orders are opened unless the fatal event-availability gate passes.
