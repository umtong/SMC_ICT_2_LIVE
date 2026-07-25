# RUN-20260725-2045-CROSSVENUE-FWD-001 — cross-venue recovery and forward evidence layer

## Current Champion

`CHAMPION-20260725-HIGH-RESISTANCE-SWEEP-C232AE43` remains the current strategy comparison leader. This run does not challenge it.

## Identifiers

- Claim: `CLM-20260725-2045-CROSSVENUE-FWD-001`
- Historical result: `RES-20260725-2045-CROSSVENUE-HIST-001`
- Forward component result: `RES-20260725-2045-CROSSVENUE-FWD-COMP-001`
- Base revision: `6`
- Source implementation commit: `9194d734e45e83e07fa921276a1e329d1126ea3f`
- Branch: `agent/crossvenue-forward-capture-r6`
- Pull request: `https://github.com/umtong/SMC_ICT_2_LIVE/pull/31`

## Scope and reuse

The run reused the successful Phase 35 GitHub Actions artifact rather than rebuilding its 101 MB 1-second panel. It also reused the merged L1 execution-routing component. Active spot/perpetual, flow-size-impact, dynamic-factor and lifecycle claims were not modified.

## Historical strategy result

The recovered snapshot covers BTC across Binance Futures, Bybit and OKX from 2026-07-14 through 2026-07-23. It contains 843,634 1-second rows, 89 Bybit liquidation events and 21,200 candidate rows.

The evaluation replayed 7,760 original continuation, reclaim and venue-transfer policies plus 680 low-dimensional mechanism policies. Decisions used fixed confirmation delays and information available by each decision second; entries and exits used the next observed bid/ask; one global position was enforced; 8, 12, 16, 20 and 24 bp costs and top-trade-removal gates were applied.

Result: zero strict and zero exploratory survivors. The tested specification is valid negative evidence, not a Champion challenge.

## Forward evidence component

The source bundle implements observation-only Binance/Bybit public capture and Bybit private execution/order/position capture with local wall and monotonic receive timestamps, raw payload hashes, append-only chain hashes, sequence and clock checks, environment-only authentication, execId-authoritative reconciliation, exact-capture-prefix dynamic-gate versus always-taker Shadow A/B, capture-quality reporting and automatic risk-state mapping.

The deterministic 36,180-byte source bundle contains 29 files and is fixed by SHA-256 `ebd83c20abaf6bf3ab7c9c467e63bd1d1129db813ddad9fa2fd3fdcca5ffcaa2`. The extracted suite passed 16 tests and compileall. It contains no order-placement path and no credentials.

## Decision

- Historical cross-venue strategy specification: `TESTED_BELOW_GATE`.
- Forward evidence implementation: `CANDIDATE` component pending real observations.
- Strategy Champion: unchanged.
- Live permission: unchanged.
- Account risk: unchanged.

## Remaining evidence

1. At least 30 days of local-receive-time Binance and Bybit BTC/ETH public capture.
2. Private execution, order and position streams from the same Shadow account.
3. Actual fee, partial-fill, queue and post-fill markout calibration.
4. Exact-prefix Shadow A/B for the merged dynamic maker/taker gate and active alpha signals.
5. A separate validation cycle before any Paper or Live decision.
